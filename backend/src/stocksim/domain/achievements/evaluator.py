"""成就判定（纯函数）：返回本次新解锁的成就 id（按目录顺序）。"""

from __future__ import annotations

from collections.abc import Iterable

from .catalog import CATALOG, AchievementDef, visible_catalog
from .stats import AchievementStats


def _passes(ach: AchievementDef, stats: AchievementStats, unlocked: frozenset[str]) -> bool:
    if ach.op == "all_others":
        required = {a.id for a in visible_catalog() if a.id != ach.id}
        return required <= unlocked
    value = getattr(stats, ach.stat)
    return value >= ach.threshold


def evaluate(
    stats: AchievementStats,
    unlocked: Iterable[str],
    catalog: tuple[AchievementDef, ...] = CATALOG,
) -> list[str]:
    """返回新解锁的成就 id 列表。隐藏成就永远不会新解锁；已解锁的不重复返回。"""
    unlocked_set = frozenset(unlocked)
    new: list[str] = []
    for ach in catalog:
        if ach.hidden or ach.id in unlocked_set:
            continue
        if _passes(ach, stats, unlocked_set):
            new.append(ach.id)
    return new
