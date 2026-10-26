"""形状曲线（01 §5.4）：分段线性的累计冲击 S(τ)，τ 相对正式发布的交易 tick。

knots 是严格递增 τ 的 (τ, 满幅的 ppm 比例) 列表，第一个 knot 的值恒为 0。
S(τ)：τ 不超过第一个 knot 时为 0；两 knot 之间线性插值（四舍五入）；超过最后一个 knot 取最后的值。
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from ..money import round_half_up_div
from .constants import (
    BUILD_FIRST_HALF_PPM,
    DENY_FACTORS_PPM,
    DENY_SETTLE_TICKS,
    PRICED_IN_DROP_PPM,
    PRICED_IN_PEAK_PPM,
    PRICED_IN_RETAIN_PPM,
    PRICED_IN_START_PPM,
    RECOVER_FIRST_THIRD_NUM_DEN,
    REFERENCE_TICKS_PER_DAY,
)
from .timing import scale_ticks
from .types import Knot

FULL = 1_000_000


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _normalize(points: Sequence[Knot]) -> tuple[Knot, ...]:
    """去掉 τ 相同的重复点（保留最后一个），并断言严格递增。"""
    out: list[Knot] = []
    for tau, value in points:
        if out and out[-1][0] == tau:
            out[-1] = (tau, value)
        else:
            out.append((tau, value))
    for (a, _), (b, _) in pairwise(out):
        if b <= a:
            raise ValueError(f"knots not increasing: {out}")
    if out[0][1] != 0:
        raise ValueError("first knot must be 0")
    return tuple(out)


def _recovery(tau_start: int, hold: int, recover: int, retain: int) -> list[Knot]:
    """平台期结束后的两段恢复（BoARIO 凸恢复的分段近似）：前 1/3 完成 5/9。"""
    num, den = RECOVER_FIRST_THIRD_NUM_DEN
    mid = FULL - round_half_up_div((FULL - retain) * num, den)
    return [
        (tau_start + hold, FULL),
        (tau_start + hold + _ceil_div(recover, 3), mid),
        (tau_start + hold + recover, retain),
    ]


def surprise_knots(
    impulse: int, build: int, hold: int, recover: int, retain: int
) -> tuple[Knot, ...]:
    half = _ceil_div(build, 2)
    mid = impulse + round_half_up_div((FULL - impulse) * BUILD_FIRST_HALF_PPM, FULL)
    pts: list[Knot] = [(-1, 0), (0, impulse), (half, mid), (build, FULL)]
    pts += _recovery(build, hold, recover, retain)
    return _normalize(pts)


def priced_in_knots(lead: int, recover: int) -> tuple[Knot, ...]:
    """买预期、卖事实：铺垫期抢跑到 0.6M，正式发布时回落到 0.3M，最终保留 0.2M。"""
    return _normalize(
        [
            (-lead - 1, 0),
            (-lead, PRICED_IN_START_PPM),
            (-1, PRICED_IN_PEAK_PPM),
            (0, PRICED_IN_DROP_PPM),
            (recover, PRICED_IN_RETAIN_PPM),
        ]
    )


def rumor_knots(
    impulse: int,
    build: int,
    hold: int,
    recover: int,
    retain: int,
    credibility: int,
    resolve_tick: int,
    truth: bool,
    ticks_per_day: int = REFERENCE_TICKS_PER_DAY,
) -> tuple[Knot, ...]:
    """传闻：首发后按可信度 c 部分定价；证实则补足到满幅后恢复，辟谣则回吐并轻微反向过冲后归零。"""
    c = credibility
    half = _ceil_div(build, 2)
    pts: list[Knot] = [
        (-1, 0),
        (0, round_half_up_div(impulse * c, FULL)),
        (min(half, resolve_tick - 1), c),
        (resolve_tick - 1, c),
    ]
    if truth:
        pts.append((resolve_tick, c + round_half_up_div((FULL - c) * impulse, FULL)))
        pts.append((resolve_tick + half, FULL))
        pts += _recovery(resolve_tick + half, hold, recover, retain)
    else:
        for dt, factor in DENY_FACTORS_PPM:
            pts.append(
                (resolve_tick + scale_ticks(dt, ticks_per_day), round_half_up_div(c * factor, FULL))
            )
        pts.append((resolve_tick + scale_ticks(DENY_SETTLE_TICKS, ticks_per_day), 0))
    return _normalize(pts)


def eval_path(knots: Sequence[Knot], tau: int) -> int:
    """S(τ)，整数 ppm。"""
    if tau <= knots[0][0]:
        return 0
    if tau >= knots[-1][0]:
        return knots[-1][1]
    for (t0, v0), (t1, v1) in pairwise(knots):
        if tau <= t1:
            if tau == t1:
                return v1
            return v0 + round_half_up_div((v1 - v0) * (tau - t0), t1 - t0)
    return knots[-1][1]  # pragma: no cover


def max_step(knots: Sequence[Knot]) -> int:
    """相邻整数 τ 之间 |S(τ)-S(τ-1)| 的最大值（ppm，精确枚举）。"""
    best = 0
    prev = 0
    for tau in range(knots[0][0] + 1, knots[-1][0] + 2):
        cur = eval_path(knots, tau)
        best = max(best, abs(cur - prev))
        prev = cur
    return best


def span_ticks(knots: Sequence[Knot]) -> int:
    """曲线走完所需的 tick 数（最后一个 knot 的 τ）。"""
    return knots[-1][0]
