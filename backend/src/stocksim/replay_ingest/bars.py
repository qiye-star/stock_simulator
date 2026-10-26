"""日 K 窗口构建：复权、停牌补齐、涨跌停与标志位、越限校验。只用标准库。

输出每行 ``[o, h, l, c, vol_shares, lim_bp, flags]``：价格为以 T0 为锚的复权价（分），
成交量为股数（手 x 100，不复权）。

复权因子取**分段常数**（见 ``adjust`` 模块文档）：只有检测到除权跳变才换段，
所以非除权日的复权涨跌幅与真实涨跌幅完全一致。
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from .adjust import (
    adjusted_cents,
    detect_ex_days,
    factor,
    round_half_up,
    segment_factors,
    yuan_to_cents,
)
from .errors import BuildError
from .limits import FLAG_SUSPENDED, TOLERANCE_CENTS, compute_flags, limit_pct_bp
from .spec import Window

LIMIT_TOLERANCE_BP = 10  # 越限校验的容差（05 §2.8）
EX_DAY_LIMIT_TOLERANCE_BP = 60  # 除权日参考价由因子估计（误差约 10–50bp），校验与封板判定放宽
EX_DAY_FLAG_TOLERANCE_BP = 30

Row = Mapping[str, Any]


@dataclass
class StockBars:
    bars: list[list[int]]
    ex_days: list[tuple[str, int]] = field(default_factory=list)  # (日期, 因子跳变 bp)，供人工核对


def index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按日期索引；同日重复取最后一行。"""
    return {str(r["d"]): r for r in rows if "d" in r}


def build_stock_bars(
    code: str,
    window: Window,
    rows_none: Mapping[str, Row],
    rows_hfq: Mapping[str, Row],
) -> StockBars:
    """返回与 ``window.dates`` 对齐的 bar 列表，以及检测到的除权日。"""
    if set(rows_none) != set(rows_hfq):
        diff = sorted(set(rows_none) ^ set(rows_hfq))[:5]
        raise BuildError(f"{code}: 不复权与后复权的日期不一致，例如 {diff}")
    traded = sorted(rows_none)
    if not traded:
        raise BuildError(f"{code}: 没有日 K 数据")

    raw_f = [factor(rows_hfq[d]["c"], rows_none[d]["c"]) for d in traded]
    ex_idx = detect_ex_days(raw_f)
    seg_f = dict(zip(traded, segment_factors(raw_f, ex_idx), strict=True))
    ex_dates = {traded[i] for i in ex_idx}
    notes = [(traded[i], round_half_up((raw_f[i] / raw_f[i - 1] - 1) * 10_000)) for i in ex_idx]

    def last_row_on_or_before(iso_date: str) -> str:
        i = bisect_right(traded, iso_date) - 1
        if i < 0:
            raise BuildError(f"{code}: {iso_date} 之前没有日 K（上市前？游戏期内的新股拒收）")
        return traded[i]

    f_anchor = seg_f[last_row_on_or_before(window.anchor_date)]

    def adj(row_date: str, field_name: str) -> int:
        return adjusted_cents(rows_none[row_date][field_name], seg_f[row_date], f_anchor)

    cal = window.calendar
    # 窗口首日之前一天的复权收盘，作为首日的“前收”
    prev_adj_close = adj(last_row_on_or_before(cal[window.start - 1]), "c")

    out: list[list[int]] = []
    for i in range(window.start, window.end):
        d = cal[i]
        lim_bp = limit_pct_bp(code, d, False)
        ex = d in ex_dates
        if d in rows_none:
            o, h, lo, c = (adj(d, k) for k in ("o", "h", "l", "c"))
            if not (lo <= min(o, c) and max(o, c) <= h):
                raise BuildError(f"{code} {d}: OHLC 不自洽 {o, h, lo, c}")
            vol = int(rows_none[d]["v_lot"]) * 100
            prev_row = last_row_on_or_before(cal[i - 1])
            prev_raw_cents = yuan_to_cents(rows_none[prev_row]["c"])
            ref = (
                round_half_up(prev_raw_cents * seg_f[prev_row] / seg_f[d]) if ex else prev_raw_cents
            )
            tol = (
                max(
                    TOLERANCE_CENTS, round_half_up(ref * Fraction(EX_DAY_FLAG_TOLERANCE_BP, 10_000))
                )
                if ex
                else TOLERANCE_CENTS
            )
            flags = compute_flags(
                open_cents=yuan_to_cents(rows_none[d]["o"]),
                close_cents=yuan_to_cents(rows_none[d]["c"]),
                ref_prev_cents=ref,
                lim_bp=lim_bp,
                ex_rights=ex,
                tolerance_cents=tol,
            )
        else:  # 停牌：没有行，补齐为前收
            o = h = lo = c = prev_adj_close
            vol = 0
            flags = FLAG_SUSPENDED
        # 越限校验（复权空间内与除权参考价口径一致）：|c/prev - 1| <= lim + 容差
        tol_bp = LIMIT_TOLERANCE_BP + (EX_DAY_LIMIT_TOLERANCE_BP if ex else 0)
        if abs(c - prev_adj_close) * 10_000 > prev_adj_close * (lim_bp + tol_bp):
            raise BuildError(
                f"{code} {d}: 涨跌幅超出 {lim_bp}bp 限制（c={c}, prev={prev_adj_close}）；"
                "可能漏标 ST、板块规则错误或数据异常"
            )
        out.append([o, h, lo, c, vol, lim_bp, flags])
        prev_adj_close = c
    window_dates = set(window.dates)
    return StockBars(out, [(d, bp) for d, bp in notes if d in window_dates])
