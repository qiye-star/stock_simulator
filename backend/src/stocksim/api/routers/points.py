"""积分账本与统计（02 §10.1）：余额（首次访问开户并发 welcome）、流水、预测统计、称号。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.db.base import utcnow
from stocksim.domain.predictions.constants import PREDICTION_DAILY_POINTS_CAP
from stocksim.models import Save
from stocksim.schemas.points import (
    LedgerPageOut,
    PointsOut,
    PredictionStatsOut,
    TitlePutIn,
    TitlesOut,
)
from stocksim.services import points as points_service
from stocksim.services import predictions as pred_service
from stocksim.services import titles as titles_service
from stocksim.services.saves import open_save
from stocksim.services.tx import run_in_transaction

router = APIRouter(prefix="/points", tags=["points"])


def _points_out(db: Session, user_id: uuid.UUID) -> dict:
    acct = points_service.open_account(db, user_id)
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used = points_service.sum_since(db, user_id=user_id, reasons=["prediction"], since=today)
    return {
        "balance": acct.balance,
        "lifetime_earned": acct.lifetime_earned,
        "lifetime_spent": acct.lifetime_spent,
        "equipped_title": acct.equipped_title,
        "today_prediction_points": used,
        "daily_cap": PREDICTION_DAILY_POINTS_CAP,
    }


@router.get("", response_model=PointsOut)
def get_points(user: CurrentUser, db: DbSession) -> dict:
    out: dict = {}

    def work() -> None:
        out.update(_points_out(db, user.id))

    run_in_transaction(db, work)
    return out


@router.get("/ledger", response_model=LedgerPageOut)
def get_ledger(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    reason: Annotated[list[str] | None, Query(max_length=24)] = None,
) -> dict:
    rows, next_cursor = points_service.ledger_page(
        db, user_id=user.id, cursor=cursor, limit=limit, reasons=reason
    )
    items = [
        {
            "seq": e.seq,
            "delta": e.delta,
            "balance_after": e.balance_after,
            "reason": e.reason,
            "ref": e.ref,
            "save_id": e.save_id,
            "meta": e.meta,
            "created_at": e.created_at,
        }
        for e in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/stats", response_model=PredictionStatsOut)
def get_stats(
    user: CurrentUser,
    db: DbSession,
    save_id: uuid.UUID | None = None,
) -> dict:
    if save_id is not None:
        save = open_save(db, user, save_id)
        pred_service.settle_due(db, save)
    else:
        for save in db.scalars(
            select(Save).where(Save.user_id == user.id, Save.events_enabled.is_(True))
        ):
            pred_service.settle_due(db, save)
    return pred_service.stats(db, user_id=user.id, save_id=save_id, lang=user.lang)


@router.get("/titles", response_model=TitlesOut)
def get_titles(user: CurrentUser, db: DbSession) -> dict:
    return titles_service.list_titles(db, user.id)


@router.put("/title", response_model=PointsOut)
def put_title(body: TitlePutIn, user: CurrentUser, db: DbSession) -> dict:
    out: dict = {}

    def work() -> None:
        titles_service.equip(db, user.id, body.title_id)
        out.update(_points_out(db, user.id))

    run_in_transaction(db, work)
    return out
