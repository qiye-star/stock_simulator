"""收盘小结：GET /saves/{id}/day-summary（07 §1.4）。数据口径见 services/day_summary.py。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.market import DaySummaryOut
from stocksim.services import day_summary as day_summary_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}", tags=["market"])


@router.get("/day-summary", response_model=DaySummaryOut)
def get_day_summary(
    save_id: uuid.UUID, user: CurrentUser, db: DbSession, trading_day: int | None = None
) -> dict:
    """trading_day 缺省为当前交易日；范围外 422 VALIDATION_ERROR {"field":"trading_day"}。"""
    save = open_save(db, user, save_id)
    return day_summary_service.day_summary(db, save, trading_day)
