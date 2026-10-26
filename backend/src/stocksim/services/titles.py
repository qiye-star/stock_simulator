"""用户级称号（02 §8）：统计从数据库取数，判定用 domain/predictions/titles.py 的纯函数。

- 解锁落库 `user_titles`，每个用户每个称号一行（UQ）。
- 佩戴写 `point_accounts.equipped_title`。
- 判定时机：预测卡结算入账后、情报卡购买后（调用方在同一事务内调用 `evaluate_for_user`）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.predictions import (
    TITLE_CATALOG,
    ScoredAnswer,
    ScoredCard,
    TitleStats,
    compute_title_stats,
    evaluate_titles,
)
from stocksim.models import LedgerEntry, PointAccount, PredictionAnswer, PredictionCard, UserTitle
from stocksim.services import points


def user_stats(db: Session, user_id: uuid.UUID) -> TitleStats:
    rows = db.execute(
        select(PredictionAnswer, PredictionCard.id, PredictionCard.settled_at)
        .join(PredictionCard, PredictionCard.id == PredictionAnswer.card_id)
        .where(PredictionAnswer.user_id == user_id, PredictionAnswer.scored_at.is_not(None))
        .order_by(PredictionCard.settled_at, PredictionCard.id, PredictionAnswer.qid)
    ).all()
    by_card: dict[uuid.UUID, list[ScoredAnswer]] = {}
    order: list[uuid.UUID] = []
    for ans, card_id, _settled in rows:
        if card_id not in by_card:
            by_card[card_id] = []
            order.append(card_id)
        by_card[card_id].append(
            ScoredAnswer(
                qid=ans.qid,
                score=int(ans.score or 0),
                baseline=int(ans.baseline or 0),
                hit=ans.hit,
                claimed_pct=ans.claimed_pct,
            )
        )
    records = [ScoredCard(answers=tuple(by_card[c])) for c in order]
    intel = int(
        db.scalar(
            select(func.count()).where(
                LedgerEntry.user_id == user_id,
                LedgerEntry.reason == "intel_card",
                LedgerEntry.delta < 0,
            )
        )
        or 0
    )
    acct = db.get(PointAccount, user_id)
    lifetime = acct.lifetime_earned if acct is not None else 0
    return compute_title_stats(records, intel_purchases=intel, lifetime_earned=lifetime)


def unlocked_ids(db: Session, user_id: uuid.UUID) -> dict[str, datetime]:
    return {
        t.title_id: t.unlocked_at
        for t in db.scalars(select(UserTitle).where(UserTitle.user_id == user_id))
    }


def evaluate_for_user(db: Session, user_id: uuid.UUID) -> list[str]:
    """判定并落库新解锁的称号（不 commit）。返回本次新解锁的 id（目录顺序）。"""
    done = unlocked_ids(db, user_id)
    new = evaluate_titles(user_stats(db, user_id), done.keys())
    for title_id in new:
        db.add(UserTitle(user_id=user_id, title_id=title_id))
    if new:
        db.flush()
    return new


def list_titles(db: Session, user_id: uuid.UUID) -> dict:
    done = unlocked_ids(db, user_id)
    acct = db.get(PointAccount, user_id)
    items = [{"id": t.id, "level": t.level, "unlocked_at": done.get(t.id)} for t in TITLE_CATALOG]
    return {"items": items, "equipped": acct.equipped_title if acct is not None else None}


def equip(db: Session, user_id: uuid.UUID, title_id: str | None) -> None:
    """佩戴（None 为卸下）。未知 id → VALIDATION_ERROR；未解锁 → TITLE_NOT_UNLOCKED。不 commit。"""
    if title_id is not None:
        if title_id not in {t.id for t in TITLE_CATALOG}:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "title_id", "reason": "unknown"})
        if title_id not in unlocked_ids(db, user_id):
            raise AppError(ErrorCode.TITLE_NOT_UNLOCKED, {"title_id": title_id})
    acct = points.open_account(db, user_id)
    acct.equipped_title = title_id
    db.flush()
