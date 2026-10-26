"""每日挑战 REST（03 §10.1）。全部需登录；CHALLENGE_ENABLED=false 时挑战接口一律 404。

/challenges 与 /challenge-leaderboard 合并在本模块的 `router`（自动发现只认 `router`），路径全写。
进入挑战路由先 runner.maybe_run_due（节流）；running 挑战再把 master 推到 tt(now)（03 §7.3）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.api.deps import CurrentUser, DbSession, SettingsDep
from stocksim.core.errors import AppError, ErrorCode
from stocksim.models import Challenge
from stocksim.schemas.challenges import (
    ChallengeAnswerIn,
    ChallengeEntryOut,
    ChallengeListOut,
    ChallengeOut,
    ChallengeRoundCardOut,
    ChallengeRoundListOut,
    LeaderboardOut,
    RevealOut,
    ReviewOut,
)
from stocksim.services.challenges import boards, entries, registry, rounds, runner, sync, timeutil
from stocksim.services.challenges import views as challenge_views
from stocksim.services.challenges.timeutil import local_date


def require_challenges_enabled(settings: SettingsDep) -> None:
    if not settings.CHALLENGE_ENABLED:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {})


router = APIRouter(tags=["challenges"], dependencies=[Depends(require_challenges_enabled)])

def _load(db: Session, challenge_id: uuid.UUID) -> Challenge:
    ch = db.get(Challenge, challenge_id)
    if ch is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(challenge_id)})
    return ch


def _prepare(db: Session, challenge_id: uuid.UUID, now: datetime) -> Challenge:
    """挑战路由的统一前置：懒触发 run_due → 懒迁移 → running 时推进 master 到 tt(now)。"""
    runner.maybe_run_due(db, now)
    ch = _load(db, challenge_id)
    db.refresh(ch)
    if registry.promote_if_due(db, ch, now):
        db.commit()
    if ch.status == "running":
        sync.advance_master(db, ch, now)
        db.refresh(ch)
    return ch


def _parse_cursor(cursor: str) -> date:
    try:
        return date.fromisoformat(cursor)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


@router.get("/challenges/today", response_model=ChallengeOut)
def get_today(user: CurrentUser, db: DbSession) -> dict:
    now = timeutil.now()
    runner.maybe_run_due(db, now)
    current = registry.current_challenge(db, now)
    if current is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"date": local_date(now).isoformat()})
    ch = _prepare(db, current.id, now)
    return challenge_views.challenge_out(db, ch, viewer=user.id, now=now)


@router.get("/challenges", response_model=ChallengeListOut)
def list_challenges(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=16)] = None,
) -> dict:
    now = timeutil.now()
    runner.maybe_run_due(db, now)
    stmt = select(Challenge).order_by(Challenge.challenge_date.desc()).limit(limit + 1)
    if cursor is not None:
        stmt = stmt.where(Challenge.challenge_date < _parse_cursor(cursor))
    rows = list(db.scalars(stmt))
    more = len(rows) > limit
    rows = rows[:limit]
    for row in rows:
        registry.promote_if_due(db, row, now)
    db.commit()
    items = [challenge_views.challenge_out(db, row, viewer=user.id, now=now) for row in rows]
    next_cursor = rows[-1].challenge_date.isoformat() if more and rows else None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/challenges/{challenge_id:uuid}", response_model=ChallengeOut)
def get_challenge(challenge_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    return challenge_views.challenge_out(db, ch, viewer=user.id, now=now)


@router.post(
    "/challenges/{challenge_id:uuid}/entry",
    response_model=ChallengeEntryOut,
    status_code=200,
)
def enter_challenge(
    challenge_id: uuid.UUID, user: CurrentUser, db: DbSession, response: Response
) -> dict:
    """报名：新建 201；已报名返回原报名 200（03 §7.4）。"""
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    entry, created = entries.join(db, ch, user, now)
    response.status_code = 201 if created else 200
    return challenge_views.entry_out(entry, ch)


@router.get("/challenges/{challenge_id:uuid}/rounds", response_model=ChallengeRoundListOut)
def list_rounds(challenge_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    """只含已打开（已到停顿时刻）的回合（03 §10.1）。"""
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    entry = registry.entry_for(db, ch, user.id)
    items = [
        challenge_views.round_card_out(db, ch, rnd, entry, now=now, lang=user.lang)
        for rnd in registry.visible_rounds(db, ch, now)
    ]
    return {"items": items}


@router.put(
    "/challenges/{challenge_id:uuid}/rounds/{round_index}/answer",
    response_model=ChallengeRoundCardOut,
)
def answer_round(
    challenge_id: uuid.UUID,
    round_index: Annotated[int, Path(ge=1, le=10)],
    body: ChallengeAnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    entry = registry.entry_for(db, ch, user.id)
    rnd = registry.round_by_index(db, ch, round_index)
    if ch.status == "running":
        master = registry.market_save_for(db, ch)
        rounds.answer_round(
            db,
            ch,
            master,
            entry,
            round_index,
            body.answers.model_dump(exclude_none=True),
            now=now,
            round_row=rnd,
        )
        db.commit()
    else:
        if entry is None:
            raise AppError(ErrorCode.CHALLENGE_NOT_ENTERED, {"challenge_id": str(ch.id)})
        if ch.status == "settled" and rnd is not None:
            raise AppError(
                ErrorCode.CHALLENGE_ROUND_CLOSED,
                {"round_index": round_index, "closes_at": rnd.closes_at.isoformat()},
            )
        raise AppError(ErrorCode.CHALLENGE_ROUND_NOT_FOUND, {"round_index": round_index})
    rnd = registry.round_by_index(db, ch, round_index)
    return challenge_views.round_card_out(db, ch, rnd, entry, now=now, lang=user.lang)


@router.get("/challenges/{challenge_id:uuid}/leaderboard", response_model=LeaderboardOut)
def day_leaderboard(
    challenge_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    board: Annotated[Literal["total", "forecast", "trade"], Query()] = "total",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    return boards.day_board(
        db, ch, board=board, limit=limit, cursor=cursor, viewer_id=user.id
    )


@router.get("/challenge-leaderboard", response_model=LeaderboardOut)
def period_leaderboard(
    user: CurrentUser,
    db: DbSession,
    scope: Annotated[Literal["week", "all"], Query()] = "week",
    week: Annotated[str | None, Query(max_length=8)] = None,
    sort: Annotated[Literal["sum", "avg"], Query()] = "sum",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    now = timeutil.now()
    runner.maybe_run_due(db, now)
    return boards.period_board(
        db,
        scope=scope,
        week=week,
        sort=sort,
        limit=limit,
        cursor=cursor,
        viewer_id=user.id,
        now=now,
    )


@router.get("/challenges/{challenge_id:uuid}/reveal", response_model=RevealOut)
def reveal(challenge_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    return challenge_views.reveal_out(db, ch)


@router.get("/challenges/{challenge_id:uuid}/review", response_model=ReviewOut)
def review(challenge_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    now = timeutil.now()
    ch = _prepare(db, challenge_id, now)
    if ch.status != "settled":
        raise AppError(ErrorCode.CHALLENGE_NOT_SETTLED, {"challenge_id": str(ch.id)})
    entry = registry.entry_for(db, ch, user.id)
    if entry is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_ENTERED, {"challenge_id": str(ch.id)})
    return challenge_views.review_out(db, ch, entry, now=now, lang=user.lang)
