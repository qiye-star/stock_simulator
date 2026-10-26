"""排名与奖励纯函数（03 §8.3、§8.4，奖励数值取 06 §4.3）。纯函数，无时钟。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .constants import (
    REWARD_PARTICIPATION,
    REWARD_PLACE_POINTS,
    REWARD_PLACES_MIN_ELIGIBLE,
    REWARD_TOP_SHARE_MIN_ELIGIBLE,
    REWARD_TOP_SHARE_PCT,
    REWARD_TOP_SHARE_POINTS,
)


def competition_ranks(scores: Sequence[int]) -> list[int]:
    """标准竞赛排名（1,2,2,4）：分数降序，名次 = 1 + 严格高于它的人数。O(n log n)。"""
    first_pos: dict[int, int] = {}
    for i, value in enumerate(sorted(scores, reverse=True)):
        first_pos.setdefault(value, i)
    return [first_pos[s] + 1 for s in scores]


def top_share_cutoff(eligible_count: int) -> int:
    """前 10% 名次上限 ⌈eligible × 10%⌉。"""
    return -(-eligible_count * REWARD_TOP_SHARE_PCT // 100)


def reward_points(rank: int | None, eligible_count: int) -> int:
    """单人奖励积分（经 B 账本 reason=challenge 发放）。

    rank 为竞赛排名；None 表示不发奖（未合格，或未答题且无成交，由调用方判定）。
    参与 50；名次 ≤ ⌈eligible×10%⌉（eligible ≥ 10）再 +100；
    第 1/2/3 名（eligible ≥ 5）再 +300/200/100。
    """
    if rank is None:
        return 0
    points = REWARD_PARTICIPATION
    if eligible_count >= REWARD_TOP_SHARE_MIN_ELIGIBLE and rank <= top_share_cutoff(eligible_count):
        points += REWARD_TOP_SHARE_POINTS
    if eligible_count >= REWARD_PLACES_MIN_ELIGIBLE:
        points += REWARD_PLACE_POINTS.get(rank, 0)
    return points


def iso_week_key(d: date) -> str:
    """ISO 周键 'YYYY-Www'（按调用方传入的 UTC+8 日历日）。"""
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"
