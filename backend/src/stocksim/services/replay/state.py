"""复盘行情状态（05 §5.3）：关卡包 + 存档位置 → 与 `market.decode_state` 同形的 state。

存档位置：`save.trading_day` 为游戏日（0 起），`save.clock_minute` 映射阶段（540/570/900/960）。
匿名（masked）模式下代码与名称取别名、价格按 `mask_scale_ppm` 缩放、日期取假日历。
本模块只读，不写库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from stocksim.domain.replay import SCALE_ONE, phase_flags, phase_of_minute, visible_quote
from stocksim.models import ReplaySession, Save
from stocksim.services.replay import levels
from stocksim.services.replay.pack import PackStock, ReplayPack
from stocksim.services.stocks import StockInfo

FAKE_EPOCH = date(2001, 1, 1)  # 周一：假日历从此起连续排工作日（05 §1.2）


@dataclass(frozen=True)
class Ctx:
    """一次请求内复盘会话的只读上下文。"""

    session: ReplaySession
    pack: ReplayPack
    masked: bool
    day: int
    phase: str
    lookback: int

    @property
    def settled(self) -> bool:
        return self.session.status == "settled"

    @property
    def save_id(self) -> Any:
        return self.session.save_id

    def index(self, day: int) -> int:
        """游戏日（可为负）→ calendar/bars 下标。"""
        return self.lookback + day


def load_ctx(db: Session, save: Save) -> Ctx:
    session = db.get(ReplaySession, save.id)
    if session is None:  # 调用方已校验 mode=replay；缺会话属于数据损坏
        raise RuntimeError(f"replay session missing for save {save.id}")
    pack = levels.get_pack(db, session.level_version_id)
    return Ctx(
        session=session,
        pack=pack,
        masked=session.masked,
        day=int(save.trading_day),
        phase=phase_of_minute(int(save.clock_minute)),
        lookback=pack.lookback_days,
    )


def fake_date(index: int) -> date:
    """假日历：第 index 个日历位置对应的第 index 个工作日（周一至周五连续，无节假日空档）。"""
    weeks, rest = divmod(index, 5)
    return FAKE_EPOCH + timedelta(days=7 * weeks + rest)


def date_iso(ctx: Ctx, day: int) -> str:
    idx = ctx.index(day)
    if ctx.masked:
        return fake_date(idx).isoformat()
    return ctx.pack.calendar[idx]


def date_label(ctx: Ctx, day: int) -> str:
    """匿名模式显示 T+k（T+0 为第 0 日），实名显示真实日期。"""
    if ctx.masked:
        return f"T{day:+d}"
    return ctx.pack.calendar[ctx.index(day)]


def stock_view(stock: PackStock, masked: bool) -> tuple[str, str]:
    """(会话内可见代码, 可见名称)。"""
    if masked:
        return stock.alias_code, stock.alias_name
    return stock.real_code, stock.real_name


def scale_of(stock: PackStock, masked: bool) -> int:
    return stock.mask_scale_ppm if masked else SCALE_ONE


def find_stock(ctx: Ctx, code: str) -> tuple[int, PackStock, str, str] | None:
    """会话可见代码 → (stock_idx, PackStock, code, name)。"""
    for i, stock in enumerate(ctx.pack.stocks):
        visible_code, name = stock_view(stock, ctx.masked)
        if visible_code == code:
            return i, stock, visible_code, name
    return None


def visible_codes(ctx: Ctx) -> list[str]:
    return [stock_view(s, ctx.masked)[0] for s in ctx.pack.stocks]


def code_of_key(ctx: Ctx, key: str) -> str:
    return stock_view(ctx.pack.stock(key), ctx.masked)[0]


def key_of_code(ctx: Ctx, code: str) -> str | None:
    hit = find_stock(ctx, code)
    return None if hit is None else hit[1].key


def display_bar_row(ctx: Ctx, stock: PackStock, day: int) -> tuple[list[int], int]:
    """(当日 bar, 前收复权价)。"""
    rows = ctx.pack.bars[stock.key]
    idx = ctx.index(day)
    return rows[idx], rows[idx - 1][3]


def build_state(ctx: Ctx, trading_tick: int) -> dict[str, Any]:
    """与 decode_state 同形（trading_tick / trading_day / breaker / stocks），另加 `_replay`。"""
    stocks: list[dict[str, Any]] = []
    for i, stock in enumerate(ctx.pack.stocks):
        bar, prev_adj = display_bar_row(ctx, stock, ctx.day)
        q = visible_quote(bar, prev_adj, scale_of(stock, ctx.masked), ctx.phase)
        code, name = stock_view(stock, ctx.masked)
        stocks.append(
            {
                "code": code,
                "name": name,
                "industry": stock.industry,
                "profile": "normal",
                "stock_idx": i,
                "key": stock.key,
                "price": q.price,
                "prev_close": q.prev_close,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "volume": q.volume,
                "daily_volume": q.volume,
                "prev_daily_volume": 0,
                "avg_volume": 0,
                "history": [],
                "limit_pct_bp": int(bar[5]),
                "replay_flags": phase_flags(int(bar[6]), ctx.phase),
            }
        )
    return {
        "trading_tick": trading_tick,
        "trading_day": ctx.day,
        "breaker": {},
        "stocks": stocks,
        "_replay": {
            "save_id": str(ctx.save_id),
            "phase": ctx.phase,
            "settled": ctx.settled,
        },
    }


def load_state(db: Session, save: Save) -> tuple[dict[str, Any], date]:
    """行情状态（不推进）。返回 (state, 当前日的日期)。"""
    ctx = load_ctx(db, save)
    state = build_state(ctx, int(save.tick))
    return state, date.fromisoformat(date_iso(ctx, ctx.day))


def stock_info(db: Session, save: Save, code: str) -> StockInfo | None:
    """复盘存档的股票信息（按模式返回别名或真名）。"""
    ctx = load_ctx(db, save)
    hit = find_stock(ctx, code)
    if hit is None:
        return None
    idx, stock, visible_code, name = hit
    return StockInfo(
        code=visible_code,
        name=name,
        industry=stock.industry,
        profile="normal",
        idx=idx,
    )


__all__ = [
    "Ctx",
    "build_state",
    "code_of_key",
    "date_iso",
    "date_label",
    "display_bar_row",
    "fake_date",
    "find_stock",
    "key_of_code",
    "load_ctx",
    "load_state",
    "scale_of",
    "stock_info",
    "stock_view",
    "visible_codes",
]
