"""事件行情：快讯、事件列表与详情（01 §8.1）。关闭事件模式的存档返回 409 EVENTS_DISABLED。"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.events import EventDetailOut, EventPageOut, NewsPageOut
from stocksim.services import events as events_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}", tags=["events"])

CodeQuery = Annotated[str | None, Query(pattern=r"^\d{6}$")]
IndustryQuery = Annotated[str | None, Query(max_length=16)]


@router.get("/news", response_model=NewsPageOut)
def list_news(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    major: bool | None = None,
    code: CodeQuery = None,
    industry: IndustryQuery = None,
    watchlisted: bool | None = None,
) -> dict:
    """快讯流，按发布时间倒序。watchlisted=true 取自选股票相关快讯的并集。"""
    save = open_save(db, user, save_id)
    return events_service.news_list(
        db,
        save,
        limit=limit,
        cursor=cursor,
        major=major,
        code=code,
        industry=industry,
        watchlisted=watchlisted,
        lang=user.lang,
    )


@router.get("/events", response_model=EventPageOut)
def list_events(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    major: bool | None = None,
    code: CodeQuery = None,
    industry: IndustryQuery = None,
    phase: Literal["expected", "active", "settled"] | None = None,
) -> dict:
    """事件列表，按首见时间倒序。"""
    save = open_save(db, user, save_id)
    return events_service.events_list(
        db,
        save,
        limit=limit,
        cursor=cursor,
        major=major,
        code=code,
        industry=industry,
        phase=phase,
        lang=user.lang,
    )


@router.get("/events/{event_id}", response_model=EventDetailOut)
def get_event(save_id: uuid.UUID, event_id: str, user: CurrentUser, db: DbSession) -> dict:
    """事件详情：已发布快讯（时间升序）与已到达的传导节点（hop 0 为源节点，最先到达）。"""
    save = open_save(db, user, save_id)
    return events_service.event_detail(db, save, event_id, user.lang)
