"""真实复盘（模式 E）：关卡列表、会话（建/推进/结束）、事件流、预测题、基准、揭示（05 §5.8）。"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from stocksim.api.deps import CurrentUser, DbSession, SettingsDep
from stocksim.schemas.replay import (
    AdvanceIn,
    AdvanceOut,
    AnswerIn,
    ReplayBenchmarkOut,
    ReplayFeedPageOut,
    ReplayLevelOut,
    ReplayLevelPageOut,
    ReplayQuestionOut,
    ReplayQuestionPageOut,
    ReplaySessionCreateIn,
    ReplaySessionOut,
    ReplaySessionPageOut,
    RevealOut,
)
from stocksim.services.replay import levels as levels_service
from stocksim.services.replay import reveal as reveal_service
from stocksim.services.replay import sessions as sessions_service

router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/levels", response_model=ReplayLevelPageOut)
def list_levels(
    user: CurrentUser,
    db: DbSession,
    tag: Annotated[str | None, Query(max_length=16)] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=3)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    return levels_service.list_levels(
        db, user, tag=tag, difficulty=difficulty, limit=limit, cursor=cursor
    )


@router.get("/levels/{slug}", response_model=ReplayLevelOut)
def get_level(slug: str, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return levels_service.level_detail(db, user, slug)


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ReplaySessionOut)
def create_session(
    body: ReplaySessionCreateIn, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    save = sessions_service.create_session(
        db,
        user,
        level_slug=body.level_slug,
        masked=body.masked,
        name=body.name,
        limit=settings.MAX_REPLAY_SESSIONS_PER_USER,
    )
    return sessions_service.get_session(db, user, save.id)


@router.get("/sessions", response_model=ReplaySessionPageOut)
def list_sessions(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return {"items": sessions_service.list_sessions(db, user)}


@router.get("/sessions/{save_id}", response_model=ReplaySessionOut)
def get_session(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return sessions_service.get_session(db, user, save_id)


@router.post("/sessions/{save_id}/advance", response_model=AdvanceOut)
def advance(
    save_id: uuid.UUID, body: AdvanceIn, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    return sessions_service.advance(
        db,
        user,
        save_id,
        to=body.to,
        expected_tick=body.expected_tick,
        skip_pending=body.skip_pending,
    )


@router.post("/sessions/{save_id}/finish", response_model=ReplaySessionOut)
def finish(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return sessions_service.finish(db, user, save_id)


@router.get("/sessions/{save_id}/feed", response_model=ReplayFeedPageOut)
def feed(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    cursor: Annotated[str | None, Query(max_length=12)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    return sessions_service.feed(db, user, save_id, cursor=cursor, limit=limit)


@router.get("/sessions/{save_id}/questions", response_model=ReplayQuestionPageOut)
def list_questions(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return sessions_service.list_questions(db, user, save_id)


@router.put(
    "/sessions/{save_id}/questions/{question_id}/answer",
    response_model=ReplayQuestionOut,
)
def answer_question(
    save_id: uuid.UUID,
    question_id: str,
    body: AnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    return sessions_service.answer(
        db, user, save_id, question_id, probs=body.probs, order=body.order
    )


@router.get("/sessions/{save_id}/benchmark", response_model=ReplayBenchmarkOut)
def benchmark(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return sessions_service.benchmark(db, user, save_id)


@router.get("/sessions/{save_id}/reveal", response_model=RevealOut)
def reveal(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return reveal_service.reveal(db, user, save_id)
