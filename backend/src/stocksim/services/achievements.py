"""成就服务：目录查询、已解锁列表、成交后判定并落库（判定逻辑在 domain.achievements）。"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.db.base import utcnow
from stocksim.domain.achievements.catalog import catalog_as_dicts
from stocksim.domain.achievements.evaluator import evaluate
from stocksim.domain.achievements.stats import compute_stats
from stocksim.domain.types import Holding
from stocksim.models import Save, SaveAchievement, WatchlistItem


def catalog() -> list[dict[str, Any]]:
    return catalog_as_dicts()


def unlocked_rows(db: Session, save: Save) -> list[SaveAchievement]:
    return list(
        db.scalars(
            select(SaveAchievement)
            .where(SaveAchievement.save_id == save.id)
            .order_by(SaveAchievement.unlocked_at, SaveAchievement.achievement_id)
        )
    )


def record_unlocks(
    db: Session,
    save: Save,
    *,
    trades: Sequence[Mapping[str, Any]],
    holdings: Mapping[str, Holding],
    prices: Mapping[str, int],
) -> list[str]:
    """用全部成交（含快照）与当前持仓判定成就；新解锁的写入 save_achievements 并返回其 id。

    调用方需在同一事务内提交。
    """
    watchlist_count = int(
        db.scalar(
            select(func.count()).select_from(WatchlistItem).where(WatchlistItem.save_id == save.id)
        )
        or 0
    )
    stats = compute_stats(
        trades=trades,
        holdings=holdings,
        prices=prices,
        fund_cents=save.cash_cents,
        initial_fund_cents=save.initial_fund_cents,
        watchlist_count=watchlist_count,
    )
    unlocked = set(
        db.scalars(select(SaveAchievement.achievement_id).where(SaveAchievement.save_id == save.id))
    )
    new_ids = evaluate(stats, unlocked)
    now = utcnow()
    for achievement_id in new_ids:
        db.add(
            SaveAchievement(
                id=uuid.uuid4(), save_id=save.id, achievement_id=achievement_id, unlocked_at=now
            )
        )
    return new_ids


__all__ = ["catalog", "record_unlocks", "unlocked_rows"]
