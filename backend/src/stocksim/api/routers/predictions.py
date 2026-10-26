"""预测卡（02 §10.1）：列表、详情、作答、不答、模式设置。存档未开事件 → 409 EVENTS_DISABLED。

每个读接口先 open_save（推进到当前时刻），再 settle_due（过期与结算到期的题）。
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.predictions import (
    PredictionAnswerIn,
    PredictionAnswerOut,
    PredictionCardOut,
    PredictionCardPageOut,
    PredictionSettingsIn,
    PredictionSettingsOut,
    PredictionSkipIn,
)
from stocksim.services import predictions as pred_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/predictions", tags=["predictions"])

StatusQuery = Literal["open", "answered", "settled", "expired", "void", "all"]


@router.get("", response_model=PredictionCardPageOut)
def list_predictions(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    status: Annotated[StatusQuery, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    save = open_save(db, user, save_id)
    pred_service.settle_due(db, save)
    rows, next_cursor = pred_service.list_cards(db, save, status=status, limit=limit, cursor=cursor)
    items = [pred_service.card_out(db, save, c, user.lang) for c in rows]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/settings", response_model=PredictionSettingsOut)
def get_settings(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    pred_service.require_enabled(save)
    return pred_service.get_settings_out(db, save)


@router.put("/settings", response_model=PredictionSettingsOut)
def put_settings(
    save_id: uuid.UUID, body: PredictionSettingsIn, user: CurrentUser, db: DbSession
) -> dict:
    save = open_save(db, user, save_id)
    pred_service.require_enabled(save)
    return pred_service.set_settings(db, save, body.mode)


@router.get("/{card_id}", response_model=PredictionCardOut)
def get_prediction(
    save_id: uuid.UUID, card_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> dict:
    save = open_save(db, user, save_id)
    pred_service.require_enabled(save)
    pred_service.settle_due(db, save)
    card = pred_service.get_card(db, save, card_id)
    return pred_service.card_out(db, save, card, user.lang)


@router.post("/{card_id}/answer", response_model=PredictionAnswerOut)
def answer_prediction(
    save_id: uuid.UUID,
    card_id: uuid.UUID,
    body: PredictionAnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    save = open_save(db, user, save_id)
    answers = {qid: value for qid, value in body.answers.model_dump().items() if value is not None}
    return pred_service.answer_card(db, save, card_id, answers, resume=body.resume, lang=user.lang)


@router.post("/{card_id}/skip", response_model=PredictionAnswerOut)
def skip_prediction(
    save_id: uuid.UUID,
    card_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    body: PredictionSkipIn | None = None,
) -> dict:
    save = open_save(db, user, save_id)
    resume = body.resume if body is not None else True
    return pred_service.skip_card(db, save, card_id, resume=resume, lang=user.lang)
