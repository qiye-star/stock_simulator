"""情报卡（02 §7）：边强度 L1/L2 按用户永久揭示；传闻提示按存档每事件 1 次。

购买流程（经 tx.run_in_transaction）：policy 检查 → 先调 events 服务拿结果（未知边、非传闻
失败不扣费）→ 已拥有则 charged=0 → 日限额 → points.debit（幂等键 intel_edge / intel_hint）→
落库揭示状态。揭示 provider 在 main.create_app 中注册给 A 的 /supply-chain。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.predictions.constants import (
    INTEL_DAILY_LIMIT,
    INTEL_PRICE_EDGE_L1,
    INTEL_PRICE_EDGE_L2,
    INTEL_PRICE_RUMOR_HINT,
)
from stocksim.models import IntelEdgeReveal, IntelRumorHint, LedgerEntry, Save
from stocksim.services import event_hooks, points
from stocksim.services import events as events_service
from stocksim.services import titles as titles_service
from stocksim.services.predictions import card_policy
from stocksim.services.tx import run_in_transaction

# 累计价格：L0=0，L1=100，L2=200（已有 L1 再买 L2 补差价 100）
EDGE_TOTAL_PRICE = {0: 0, 1: INTEL_PRICE_EDGE_L1, 2: INTEL_PRICE_EDGE_L2}


def _require_enabled(save: Save) -> None:
    if not save.events_enabled:
        raise AppError(ErrorCode.EVENTS_DISABLED, {"save_id": str(save.id)})


def _day_start():
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def used_today(db: Session, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count()).where(
                LedgerEntry.user_id == user_id,
                LedgerEntry.reason == "intel_card",
                LedgerEntry.delta < 0,
                LedgerEntry.created_at >= _day_start(),
            )
        )
        or 0
    )


def _check_limit(db: Session, user_id: uuid.UUID) -> None:
    if used_today(db, user_id) >= INTEL_DAILY_LIMIT:
        raise AppError(ErrorCode.INTEL_LIMIT_REACHED, {"limit": INTEL_DAILY_LIMIT})


def reveal_levels_for_save(db: Session, save: Save) -> Mapping[str, int]:
    """揭示 provider：该用户的 {edge_id: level}；policy 不允许情报时返回 {}。"""
    if not card_policy(db, save).intel_allowed:
        return {}
    rows = db.execute(
        select(IntelEdgeReveal.edge_id, IntelEdgeReveal.level).where(
            IntelEdgeReveal.user_id == save.user_id
        )
    ).all()
    return {edge_id: int(level) for edge_id, level in rows}


def register_hooks() -> None:
    event_hooks.register_reveal_provider(reveal_levels_for_save)


def state(db: Session, save: Save) -> dict[str, Any]:
    _require_enabled(save)
    edges: list[dict[str, Any]] = []
    if card_policy(db, save).intel_allowed:
        for row in db.scalars(
            select(IntelEdgeReveal).where(IntelEdgeReveal.user_id == save.user_id)
        ):
            try:
                edges.append(events_service.reveal_edge(save, row.edge_id, row.level))
            except AppError:  # 边表变化：忽略已不存在的边
                continue
    hints: list[dict[str, Any]] = []
    if card_policy(db, save).intel_allowed:
        for row in db.scalars(select(IntelRumorHint).where(IntelRumorHint.save_id == save.id)):
            hints.append(events_service.rumor_hint(db, save, row.event_id))
    # 与 GET /points 一致：首次访问开户并发放欢迎积分
    balance = run_in_transaction(db, lambda: points.open_account(db, save.user_id).balance)
    return {
        "edges": edges,
        "rumor_hints": hints,
        "prices": {
            "edge_l1": INTEL_PRICE_EDGE_L1,
            "edge_l2": INTEL_PRICE_EDGE_L2,
            "rumor_hint": INTEL_PRICE_RUMOR_HINT,
        },
        "daily_limit": INTEL_DAILY_LIMIT,
        "used_today": used_today(db, save.user_id),
        "balance": balance,
    }


def _disabled_check(db: Session, save: Save, card: str) -> None:
    if not card_policy(db, save).intel_allowed:
        raise AppError(ErrorCode.INTEL_UNAVAILABLE, {"card": card, "reason": "disabled"})


def buy_edge_reveal(db: Session, save: Save, *, edge_id: str, level: int) -> dict[str, Any]:
    _require_enabled(save)
    _disabled_check(db, save, "edge")
    if level not in (1, 2):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "level"})
    uid = save.user_id
    state_out: dict[str, Any] = {}

    def work() -> None:
        detail = events_service.reveal_edge(save, edge_id, level)  # 未知边 → 404，不扣费
        row = db.scalar(
            select(IntelEdgeReveal).where(
                IntelEdgeReveal.user_id == uid, IntelEdgeReveal.edge_id == edge_id
            )
        )
        owned = row.level if row is not None else 0
        if owned == 2 and level == 2:
            raise AppError(ErrorCode.INTEL_UNAVAILABLE, {"card": "edge", "reason": "max_level"})
        if owned >= level:
            state_out.update(charged=0, edge=detail)
            return
        _check_limit(db, uid)
        amount = EDGE_TOTAL_PRICE[level] - EDGE_TOTAL_PRICE[owned]
        points.debit(
            db,
            user_id=uid,
            amount=amount,
            reason="intel_card",
            ref=f"edge:{edge_id}",
            idempotency_key=f"intel_edge:{uid}:{edge_id}:L{level}",
            save_id=save.id,
        )
        if row is None:
            db.add(IntelEdgeReveal(user_id=uid, edge_id=edge_id, level=level, points_spent=amount))
        else:
            row.level = level
            row.points_spent += amount
        db.flush()
        titles_service.evaluate_for_user(db, uid)
        state_out.update(charged=amount, edge=detail)

    run_in_transaction(db, work)
    return {
        "charged": state_out["charged"],
        "balance": points.balance(db, user_id=uid),
        "edge": state_out["edge"],
        "hint": None,
    }


def buy_rumor_hint(db: Session, save: Save, *, event_id: str) -> dict[str, Any]:
    _require_enabled(save)
    _disabled_check(db, save, "rumor")
    uid = save.user_id
    state_out: dict[str, Any] = {}

    def work() -> None:
        hint = events_service.rumor_hint(db, save, event_id)  # 非传闻/不存在 → 不扣费
        row = db.scalar(
            select(IntelRumorHint).where(
                IntelRumorHint.save_id == save.id, IntelRumorHint.event_id == event_id
            )
        )
        if row is not None:
            state_out.update(charged=0, hint=hint)
            return
        if hint["accuracy_pct"] == 100:
            raise AppError(ErrorCode.INTEL_UNAVAILABLE, {"card": "rumor", "reason": "resolved"})
        _check_limit(db, uid)
        points.debit(
            db,
            user_id=uid,
            amount=INTEL_PRICE_RUMOR_HINT,
            reason="intel_card",
            ref=f"event:{event_id}",
            idempotency_key=f"intel_hint:{save.id}:{event_id}",
            save_id=save.id,
        )
        db.add(
            IntelRumorHint(
                save_id=save.id,
                user_id=uid,
                event_id=event_id,
                points_spent=INTEL_PRICE_RUMOR_HINT,
            )
        )
        db.flush()
        titles_service.evaluate_for_user(db, uid)
        state_out.update(charged=INTEL_PRICE_RUMOR_HINT, hint=hint)

    run_in_transaction(db, work)
    return {
        "charged": state_out["charged"],
        "balance": points.balance(db, user_id=uid),
        "edge": None,
        "hint": state_out["hint"],
    }
