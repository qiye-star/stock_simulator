"""旧版存档导入：解码 legacy/crypto.js 的 XOR+Base64 导出文本（或明文 JSON），严格校验后
落库为当前用户的新存档。

解码与 legacy/crypto.js 一致：`base64 -> UTF-8 -> 逐字符 XOR(key)`，key = 'stock-simulator-2024'。
映射规则（元 -> 分，legacy 记录 -> trades）见各函数注释；密码哈希与用户级偏好被忽略。
无法从旧数据恢复的字段（trade 的 tick / trading_day、市场种子）使用固定占位值，见 CLAUDE.md。
"""

import base64
import binascii
import hashlib
import json
import secrets
import uuid
from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.achievements.catalog import CATALOG_BY_ID
from stocksim.domain.clock import CLOCK_RULES_V1
from stocksim.models import (
    Holding,
    LegacyImport,
    Save,
    SaveAchievement,
    SaveSector,
    SaveStats,
    Stock,
    Trade,
    User,
    WatchlistItem,
)
from stocksim.schemas.legacy import (
    ImportedSaveOut,
    LegacyImportOut,
    LegacyRecord,
    LegacySave,
    LegacyUser,
)
from stocksim.services.market import init_market_for_save
from stocksim.services.saves import MAX_SAVES_PER_USER

LEGACY_XOR_KEY = "stock-simulator-2024"  # legacy/crypto.js 的 encrypt 默认 key
MAX_CONTENT_CHARS = 8 * 1024 * 1024  # 请求文本上限（Base64 膨胀约 4/3）
MAX_DECODED_BYTES = 5 * 1024 * 1024  # legacy importSave 的 5MB 上限
DEFAULT_CLOCK_MINUTE = 570  # 9:30 开盘
DEFAULT_TRADING_DAY = 0  # 行情交易日 0 即开局日（见 services/market.py 的 trading_tick）
LEGACY_TRADING_DAY = -1  # 旧成交统一记在开局日之前，不参与当日 T+1 判断
DEFAULT_TRADE_UNIT = 1


class LegacyFormatError(Exception):
    """导入文本不合法（解码/JSON/结构/一致性）。reason 为稳定短码，params 供前端定位。"""

    def __init__(self, reason: str, params: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.params: dict[str, Any] = dict(params or {})


def _fail(
    db: Session,
    user: User,
    *,
    sha: str,
    source_format: str,
    exc: LegacyFormatError | str,
    params: dict[str, Any] | None = None,
) -> AppError:
    """记录失败审计行并返回待抛出的 AppError（调用方 raise）。"""
    db.add(
        LegacyImport(
            id=uuid.uuid4(),
            user_id=user.id,
            save_id=None,
            source_format=source_format,
            source_sha256=sha,
            status="failed",
            created_at=utcnow(),
        )
    )
    db.commit()
    if isinstance(exc, LegacyFormatError):
        reason, extra = exc.reason, exc.params
    else:
        reason, extra = exc, {}
    return AppError(ErrorCode.LEGACY_IMPORT_INVALID, {"reason": reason, **extra, **(params or {})})


def _xor(text: str, key: str) -> str:
    return "".join(chr(ord(ch) ^ ord(key[i % len(key)])) for i, ch in enumerate(text))


def decode_content(content: str) -> tuple[str, str]:
    """返回 (JSON 文本, 来源格式)。格式：'legacy-xor' 或 'json'。失败抛 LegacyFormatError。"""
    if len(content) > MAX_CONTENT_CHARS:
        raise LegacyFormatError("too_large")
    text = content.strip()
    if not text:
        raise LegacyFormatError("empty")
    if text.startswith("{"):
        return text, "json"
    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LegacyFormatError("base64") from exc
    if len(raw) > MAX_DECODED_BYTES:
        raise LegacyFormatError("too_large")
    try:
        text = raw.decode("utf-8")  # legacy fromBase64 的首选路径
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # legacy fromBase64 的 atob 回退路径
    return _xor(text, LEGACY_XOR_KEY), "legacy-xor"


def parse_legacy(json_text: str) -> list[LegacySave]:
    """严格结构校验（已知字段类型严格，未知字段忽略）。返回待导入的全部存档。

    支持两种形态：
    - 单个用户对象 `{"username": ..., "saves": [...]}`（导出文件 / 样例）；
    - 整包用户映射 `{"<username>": {...}, ...}`（旧版 localStorage `stock_simulator_users`
      解密后的 `this.users`）。整包时各用户的存档按键顺序合并，密码与用户名不导入。
    失败抛 LegacyFormatError。
    """
    try:
        data = json.loads(json_text)
    except (ValueError, RecursionError) as exc:
        raise LegacyFormatError("json") from exc
    if not isinstance(data, dict):
        raise LegacyFormatError("json")
    users: list[Any]
    if isinstance(data.get("username"), str):
        users = [data]
    else:
        if not data or not all(isinstance(v, dict) for v in data.values()):
            raise LegacyFormatError("schema", {"errors": [{"loc": [], "msg": "expected user map"}]})
        users = list(data.values())
    saves: list[LegacySave] = []
    for user in users:
        try:
            saves.extend(LegacyUser.model_validate(user).saves)
        except ValidationError as exc:
            errors = [
                {"loc": [str(p) for p in err["loc"]], "msg": err["msg"]}
                for err in exc.errors()[:10]
            ]
            raise LegacyFormatError("schema", {"errors": errors}) from None
    return saves


def _cents(value: float | int) -> int:
    """元（float/int）-> 整数分，half up。"""
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rate(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _trade_rows(save_id: uuid.UUID, records: list[LegacyRecord], now: datetime) -> list[Trade]:
    """legacy records 为“新在前”的数组（unshift），这里按时间升序写入，seq 从 1 递增。

    由 legacy 记录还原：
    - 手续费 = 买入：-amount - gross；卖出：gross - amount（legacy 只存了已扣费金额）；
    - prev_close_cents 无法还原，取成交价；tick=0、trading_day=LEGACY_TRADING_DAY（-1）。
    """
    ordered = sorted(reversed(records), key=lambda r: (r.time is None, r.time or 0))
    rows: list[Trade] = []
    for seq, rec in enumerate(ordered, start=1):
        price = _cents(rec.price)
        gross = price * rec.quantity
        cash = _cents(rec.amount)
        fee = (-cash - gross) if rec.type == "buy" else (gross - cash)
        if fee < 0:
            raise ValueError("record_mismatch")  # 金额与成交价*数量不自洽
        rows.append(
            Trade(
                id=uuid.uuid4(),
                save_id=save_id,
                seq=seq,
                stock_code=rec.code,
                side=rec.type,
                source="manual",
                price_type="market",
                limit_price_cents=None,
                price_cents=price,
                quantity=rec.quantity,
                gross_cents=gross,
                fee_cents=fee,
                cash_delta_cents=cash,
                realized_pnl_cents=_cents(rec.pnl) if rec.type == "sell" else 0,
                prev_close_cents=price,
                tick=0,
                trading_day=LEGACY_TRADING_DAY,
                clock_minute=DEFAULT_CLOCK_MINUTE,
                auto_config_id=None,
                created_at=now,
            )
        )
    return rows


def _build_save(
    db: Session,
    user: User,
    legacy: LegacySave,
    stocks: dict[str, Stock],
    now: datetime,
) -> tuple[Save, dict[str, int]]:
    save_id = uuid.uuid4()
    records = legacy.records
    trades = _trade_rows(save_id, records, now)
    fund_cents = _cents(legacy.fund)
    settings = legacy.settings
    save = Save(
        id=save_id,
        user_id=user.id,
        name=legacy.name if legacy.name else "",
        mode="normal",
        initial_fund_cents=_cents(
            legacy.initialFund if legacy.initialFund is not None else legacy.fund
        ),
        cash_cents=fund_cents,
        buy_fee_rate=_rate(settings.buyFee),
        sell_fee_rate=_rate(settings.sellFee),
        t0_mode=settings.t0Mode,
        trade_unit=settings.tradeUnit or DEFAULT_TRADE_UNIT,
        market_seed=secrets.randbelow(2**63),
        tick=0,
        trade_seq=len(trades),
        trading_day=DEFAULT_TRADING_DAY,
        # 旧版导入的行情为全新生成，按新存档处理；规则版本固定 v1（v2 只在显式请求时启用）
        clock_rules=CLOCK_RULES_V1,
        events_enabled=False,  # 旧版导入一律关闭事件模式（01 §3）
        events_ruleset=0,
        clock_minute=DEFAULT_CLOCK_MINUTE,
        paused=False,
        auto_enabled=False,
        auto_paused=False,
        auto_max_total_trades=100,
        created_at=now,
        updated_at=now,
    )
    db.add(save)
    db.flush()  # 先落 saves 行，子表外键才可用

    holdings = [
        Holding(
            id=uuid.uuid4(),
            save_id=save_id,
            stock_code=code,
            quantity=h.quantity,
            avg_price_cents=_cents(h.avgPrice),
            total_cost_cents=_cents(h.totalCost),
            updated_at=now,
        )
        for code, h in legacy.holdings.items()
        if h.quantity > 0
    ]
    watch_codes = list(dict.fromkeys(legacy.watchlist))
    achievement_ids = [a for a in dict.fromkeys(legacy.achievements) if a in CATALOG_BY_ID]
    traded_codes = {r.code for r in records} | {h.stock_code for h in holdings}
    sectors = sorted({stocks[c].industry for c in traded_codes if c in stocks})
    gs = legacy.gameStats

    db.add_all(trades)
    db.add_all(holdings)
    db.add_all(
        WatchlistItem(id=uuid.uuid4(), save_id=save_id, stock_code=c, created_at=now)
        for c in watch_codes
    )
    db.add_all(
        SaveAchievement(id=uuid.uuid4(), save_id=save_id, achievement_id=a, unlocked_at=now)
        for a in achievement_ids
    )
    db.add_all(SaveSector(id=uuid.uuid4(), save_id=save_id, sector=s) for s in sectors)
    db.add(
        SaveStats(
            save_id=save_id,
            trade_count=max(gs.tradeCount if gs else 0, len(trades)),
            profit_count=gs.profitCount if gs else 0,
            loss_count=gs.lossCount if gs else 0,
            max_holdings=max(gs.maxHoldings if gs else 0, len(holdings)),
            updated_at=now,
        )
    )
    db.flush()
    summary = {
        "trades": len(trades),
        "holdings": len(holdings),
        "watchlist": len(watch_codes),
        "achievements": len(achievement_ids),
        "dropped_achievements": len(legacy.achievements) - len(achievement_ids),
    }
    return save, summary


def _referenced_codes(saves: Iterable[LegacySave]) -> set[str]:
    codes: set[str] = set()
    for s in saves:
        codes.update(s.holdings.keys())
        codes.update(s.watchlist)
        codes.update(r.code for r in s.records)
    return codes


def import_legacy(db: Session, user: User, content: str) -> LegacyImportOut:
    sha = hashlib.sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()
    source_format = "legacy-xor"
    try:
        json_text, source_format = decode_content(content)
        saves = parse_legacy(json_text)
    except LegacyFormatError as exc:
        raise _fail(db, user, sha=sha, source_format=source_format, exc=exc) from None
    if not saves:
        raise _fail(db, user, sha=sha, source_format=source_format, exc="no_saves")

    existing = db.scalar(select(func.count()).select_from(Save).where(Save.user_id == user.id))
    if (existing or 0) + len(saves) > MAX_SAVES_PER_USER:
        raise AppError(
            ErrorCode.SAVE_LIMIT_REACHED,
            {"limit": MAX_SAVES_PER_USER, "existing": existing or 0},
        )

    codes = _referenced_codes(saves)
    stocks = (
        {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))} if codes else {}
    )
    unknown = sorted(codes - set(stocks))
    if unknown:
        raise _fail(
            db,
            user,
            sha=sha,
            source_format=source_format,
            exc="unknown_stock",
            params={"codes": unknown[:5]},
        )

    now = utcnow()
    results: list[ImportedSaveOut] = []
    dropped = 0
    try:
        built = [_build_save(db, user, s, stocks, now) for s in saves]
        for save, summary in built:
            _seed_market(db, save)
            dropped += summary["dropped_achievements"]
            db.add(
                LegacyImport(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    save_id=save.id,
                    source_format=source_format,
                    source_sha256=sha,
                    status="imported",
                    created_at=now,
                )
            )
            results.append(
                ImportedSaveOut(
                    save_id=str(save.id),
                    name=save.name,
                    cash_cents=save.cash_cents,
                    holdings=summary["holdings"],
                    trades=summary["trades"],
                    watchlist=summary["watchlist"],
                    achievements=summary["achievements"],
                )
            )
        db.commit()
    except AppError:
        db.rollback()
        raise
    except ValueError as exc:  # 例如 record_mismatch（旧记录的金额与费用不自洽）
        db.rollback()
        raise _fail(db, user, sha=sha, source_format=source_format, exc=str(exc)) from None
    return LegacyImportOut(imported=results, skipped_achievements=dropped)


def _seed_market(db: Session, save: Save) -> None:
    """生成行情快照与历史日 K（复用 services.market.init_market_for_save）。"""
    init_market_for_save(db, save, utcnow().date())
