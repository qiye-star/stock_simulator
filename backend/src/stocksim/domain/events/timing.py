"""tick 单位换算：本包所有“以 tick 计”的常量都按参考时钟（每交易日 20 tick）定义，
再按规则集的 ``ticks_per_day`` 线性换算。ticks_per_day=20 时恒等，结果与参考值逐位一致。

以“交易日”为单位的常量（回看/前瞻天数、每日小快讯条数）与 tick 常量同比例缩放后保持不变，
唯一例外是重大事件周期：它的目标是“约一个时钟日”，见 ``major_period_days``。
"""

from __future__ import annotations

from ..clock import CLOCK_RULES_V1
from ..money import round_half_up_div
from .constants import (
    MAJOR_OFFSET,
    MAJOR_OFFSET_V2,
    MAJOR_PERIOD_REF_TICKS,
    MINOR_OFFSET,
    MINOR_OFFSET_V2,
    REFERENCE_TICKS_PER_DAY,
)


def scale_ticks(ref_ticks: int, ticks_per_day: int) -> int:
    """把参考 tick 数换算为当前时钟的 tick 数（四舍五入；正数结果至少为 1）。"""
    if ticks_per_day == REFERENCE_TICKS_PER_DAY:
        return ref_ticks
    scaled = round_half_up_div(ref_ticks * ticks_per_day, REFERENCE_TICKS_PER_DAY)
    return max(1, scaled) if ref_ticks > 0 else scaled


def scale_bounds(bounds: tuple[int, int], ticks_per_day: int) -> tuple[int, int]:
    """区间 (lo, hi)（参考 tick）-> 当前时钟 tick。lo 允许为 0；保证 lo <= hi。"""
    lo, hi = bounds
    if ticks_per_day == REFERENCE_TICKS_PER_DAY:
        return lo, hi
    lo2 = round_half_up_div(lo * ticks_per_day, REFERENCE_TICKS_PER_DAY)
    hi2 = max(lo2, round_half_up_div(hi * ticks_per_day, REFERENCE_TICKS_PER_DAY))
    return lo2, hi2


def major_period_days(ticks_per_day: int) -> int:
    """重大事件周期（交易日数）：约 240 个 tick，即约一个时钟日。
    20 tick/日 -> 12 日，242 tick/日 -> 1 日。"""
    return max(1, round_half_up_div(MAJOR_PERIOD_REF_TICKS, ticks_per_day))


def publish_offsets(clock_rules: int, ticks_per_day: int, major: bool, day: int) -> tuple[int, ...]:
    """正式发布的日内偏移合法集（升序）。第 0 日不取偏移 0（该 tick 不推进）。

    v1：参考区间经 scale_bounds 换算后的连续整数（20 tick 时即原 ``lo..hi``）；
    v2：01 §4.2 的两段集合，排除 11:30 与 15:00 两个不接单的 tick，不做 scale。
    """
    if clock_rules == CLOCK_RULES_V1:
        lo, hi = scale_bounds(MAJOR_OFFSET if major else MINOR_OFFSET, ticks_per_day)
        intervals: tuple[tuple[int, int], ...] = ((lo, hi),)
    else:
        intervals = MAJOR_OFFSET_V2 if major else MINOR_OFFSET_V2
    offsets = [o for a, b in intervals for o in range(a, b + 1)]
    if day == 0:
        offsets = [o for o in offsets if o >= 1]
    return tuple(offsets)


def scale_magnitude(bounds: tuple[int, int], scale_ppm: int) -> tuple[int, int]:
    """源满幅区间乘以 scale_ppm（1e6 = 恒等），两端四舍五入，保持 lo <= hi 且 lo >= 1。"""
    if scale_ppm == 1_000_000:
        return bounds
    lo, hi = bounds
    lo2 = max(1, round_half_up_div(lo * scale_ppm, 1_000_000))
    hi2 = max(lo2, round_half_up_div(hi * scale_ppm, 1_000_000))
    return lo2, hi2
