"""游戏时钟：暂停、继续、跳过（跳到下一个关键时点）。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.market import ClockOut
from stocksim.services import market as market_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/clock", tags=["clock"])


@router.post("/pause", response_model=ClockOut)
def pause(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return market_service.pause_clock(db, save)


@router.post("/resume", response_model=ClockOut)
def resume(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return market_service.resume_clock(db, save)


@router.post("/skip", response_model=ClockOut)
def skip(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return market_service.skip_clock(db, save)
