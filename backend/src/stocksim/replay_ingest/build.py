"""关卡包构建器：规格 + 原始数据 -> 关卡包 JSON。**只用标准库，不联网。**

确定性：同样的输入逐字节相同（键排序、紧凑分隔符、列表顺序固定、``built_at`` 不取墙钟）。
格式见 docs/10.26-plan/05-真实复盘.md §3.2。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from . import BUILDER_VERSION, PACK_FORMAT, PACK_FORMAT_VERSION, rawstore
from .adjust import round_half_up, yuan_to_cents
from .bars import build_stock_bars, index_rows
from .errors import BuildError
from .events import collect_candidates, compute_impact, finalize_events
from .questions import build_questions
from .rawstore import RawStore
from .reader import RawReader
from .redact import StockMask
from .spec import Spec, SpecError, Window, compute_window

ALIAS_CODE_BASE = 990001
MASK_TARGET_MIN_CENTS = 1000  # 第 0 日前收缩放后落在 10–50 元
MASK_TARGET_SPAN_CENTS = 4001
PACK_SIZE_WARN_BYTES = 400 * 1024


@dataclass
class BuildResult:
    pack: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def canonical_dumps(obj: Any) -> str:
    """规范化序列化：键排序、紧凑、保留中文、结尾换行。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _load_calendar(reader: RawReader) -> list[str]:
    data = reader.json(rawstore.calendar_path())
    rows = data.get("rows") if data else None
    if not isinstance(rows, list) or not rows:
        raise BuildError("缺少交易日历：先运行 `calendar` 子命令")
    return sorted({str(r) for r in rows})


def _mask_scale_ppm(slug: str, code: str, anchor_close_cents: int) -> int:
    """每只股票固定的匿名价格缩放：让第 0 日前收落在 10–50 元，目标价由 (slug, code) 哈希决定。"""
    h = int.from_bytes(hashlib.sha256(f"{slug}:{code}".encode()).digest()[:4], "big")
    target = MASK_TARGET_MIN_CENTS + h % MASK_TARGET_SPAN_CENTS
    if anchor_close_cents <= 0:
        raise BuildError(f"{code}: 锚日收盘价非正，无法缩放")
    return round_half_up(Fraction(target * 1_000_000, anchor_close_cents))


def _real_names(spec: Spec, reader: RawReader, window: Window) -> dict[str, str]:
    """规格里的 ``name`` 优先；否则回退到巨潮/东财原始数据里的简称。"""
    names = {s.code: s.name for s in spec.stocks if s.name}
    missing = [s.code for s in spec.stocks if s.code not in names]
    if not missing:
        return names
    ys = sorted({int(d[:4]) for d in window.dates})
    for code in missing:
        for year in ys:
            for q in (1, 2, 3, 4):
                for row in reader.rows(rawstore.cninfo_path(code, year, q)):
                    if row.get("简称"):
                        names.setdefault(code, str(row["简称"]))
        if code in names:
            continue
        for d in window.dates:
            for row in reader.rows(rawstore.gsrl_path(d)):
                if row.get("代码") == code and row.get("简称"):
                    names.setdefault(code, str(row["简称"]))
    still = [c for c in missing if c not in names]
    if still:
        raise BuildError(f"无法确定股票简称 {still}：请在规格 stocks[*].name 里填写")
    return names


def build_pack(
    spec: Spec,
    store: RawStore,
    *,
    version: int,
    built_at: str | None = None,
) -> BuildResult:
    """构建关卡包。``version`` 由作者指定（内容变化必须 +1）。"""
    if version < 1:
        raise BuildError("version 必须 >= 1")
    reader = RawReader(store)
    calendar = _load_calendar(reader)
    try:
        window = compute_window(calendar, spec)
    except SpecError as exc:
        raise BuildError(str(exc)) from exc
    cal_meta = reader.json(rawstore.calendar_path()) or {}

    # --- 股票元数据与别名 ---
    names = _real_names(spec, reader, window)
    key_of = {s.code: f"s{i}" for i, s in enumerate(spec.stocks, start=1)}
    industry_of = {s.code: s.industry for s in spec.stocks}
    per_industry: dict[str, int] = {}
    alias_names: dict[str, str] = {}
    for s in spec.stocks:
        n = per_industry.get(s.industry, 0)
        per_industry[s.industry] = n + 1
        alias_names[s.code] = f"{s.industry}{chr(ord('A') + n) if n < 26 else n + 1}"
    masks = [
        StockMask(
            key=key_of[s.code],
            real_code=s.code,
            real_name=names[s.code],
            alias_code=str(ALIAS_CODE_BASE + i),
            alias_name=alias_names[s.code],
            terms=s.redact_terms,
        )
        for i, s in enumerate(spec.stocks)
    ]

    # --- K 线 ---
    bars: dict[str, list[list[int]]] = {}
    closes: dict[str, list[int]] = {}
    ex_notes: list[str] = []
    for s in spec.stocks:
        rows_n = index_rows(reader.jsonl(rawstore.kline_path("none", s.code)))
        rows_h = index_rows(reader.jsonl(rawstore.kline_path("hfq", s.code)))
        if not rows_n:
            raise BuildError(f"{s.code}: 缺少日 K 原始数据：先运行 `fetch`")
        built = build_stock_bars(s.code, window, rows_n, rows_h)
        bars[key_of[s.code]] = built.bars
        closes[key_of[s.code]] = [b[3] for b in built.bars]
        ex_notes.extend(
            f"{s.code}: 检测到除权/复权跳变 {d}（因子 {bp:+d}bp），请对照公告核对"
            for d, bp in built.ex_days
        )

    # --- 基准指数 ---
    idx_rows = index_rows(reader.jsonl(rawstore.index_path(spec.benchmark_symbol)))
    if not idx_rows:
        raise BuildError(f"缺少基准指数 {spec.benchmark_symbol} 的原始数据：先运行 `fetch`")
    missing_idx = [d for d in window.dates if d not in idx_rows]
    if missing_idx:
        raise BuildError(f"基准指数缺少 {len(missing_idx)} 个交易日，例如 {missing_idx[:3]}")
    bench = [yuan_to_cents(idx_rows[d]["c"]) for d in window.dates]

    # --- 股票表 ---
    stocks_out = []
    for i, s in enumerate(spec.stocks):
        anchor_close = closes[key_of[s.code]][window.lookback - 1]
        stocks_out.append(
            {
                "key": key_of[s.code],
                "real_code": s.code,
                "real_name": names[s.code],
                "industry": s.industry,
                "alias_code": masks[i].alias_code,
                "alias_name": masks[i].alias_name,
                "mask_scale_ppm": _mask_scale_ppm(spec.slug, s.code, anchor_close),
                "role": s.role,
            }
        )

    # --- 事件 ---
    cands = collect_candidates(spec, window, reader, key_of, industry_of, names)
    events, redaction = finalize_events(cands, masks)
    focus_keys = [key_of[s.code] for s in spec.stocks if s.role == "focus"]
    for ev in events:
        ev["impact"] = compute_impact(ev, window, closes, bench, focus_keys)

    # --- 预测题 ---
    questions, q_report, warnings = build_questions(spec, window, closes, key_of, masks)
    warnings = [*ex_notes, *warnings]
    redaction = sorted(redaction + q_report, key=lambda r: (r["event_id"], r["field"], r["hit"]))

    pack: dict[str, Any] = {
        "format": PACK_FORMAT,
        "format_version": PACK_FORMAT_VERSION,
        "slug": spec.slug,
        "version": version,
        "title": spec.title,
        "title_masked": spec.title_masked,
        "teaser": spec.teaser,
        "teaser_masked": spec.teaser_masked,
        "tags": list(spec.tags),
        "difficulty": spec.difficulty,
        "kind": spec.kind,
        "masked_allowed": spec.masked_allowed,
        "calendar": list(window.dates),
        "lookback_days": spec.lookback_days,
        "play_days": spec.play_days,
        "reveal_days": spec.reveal_days,
        "anchor_date": window.anchor_date,
        "benchmark": {
            "symbol": spec.benchmark_symbol,
            "name": spec.benchmark_name,
            "closes_adj": bench,
        },
        "stocks": stocks_out,
        "bars": bars,
        "events": events,
        "questions": questions,
        "commentary": spec.commentary,
        "provenance": {
            "builder_version": BUILDER_VERSION,
            "akshare_version": str(cal_meta.get("akshare_version", "unknown")),
            "raw_files": reader.used_files(),
            "built_at": built_at or reader.latest_fetched_at() or "1970-01-01T00:00:00Z",
        },
        "redaction_report": redaction,
    }
    size = len(canonical_dumps(pack).encode("utf-8"))
    if size > PACK_SIZE_WARN_BYTES:
        warnings.append(f"包体积 {size} 字节超过 {PACK_SIZE_WARN_BYTES}")
    return BuildResult(pack, warnings)
