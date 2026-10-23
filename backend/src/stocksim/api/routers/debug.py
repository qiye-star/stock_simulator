"""调试接口：POST /saves/{id}/debug/{fund|time|achievements|reset-market|clear}。

仅当 settings.ENABLE_DEBUG_API=true 时可用，否则一律 403 DEBUG_DISABLED（先于鉴权判断）。
"""

import uuid

from fastapi import APIRouter, Depends

from stocksim.api.deps import CurrentUser, DbSession, SettingsDep
from stocksim.core.errors import AppError, ErrorCode
from stocksim.models import Save
from stocksim.schemas.debug import DebugAchievementsIn, DebugFundIn, DebugResultOut, DebugTimeIn
from stocksim.services import debug as debug_service
from stocksim.services.saves import open_save


def _require_debug_enabled(settings: SettingsDep) -> None:
    if not settings.ENABLE_DEBUG_API:
        raise AppError(ErrorCode.DEBUG_DISABLED)


router = APIRouter(
    prefix="/saves/{save_id}/debug",
    tags=["debug"],
    dependencies=[Depends(_require_debug_enabled)],
)


def _result(action: str, save: Save, changed: int) -> DebugResultOut:
    return DebugResultOut(
        action=action,
        cash_cents=save.cash_cents,
        clock_minute=save.clock_minute,
        trading_day=save.trading_day,
        changed=changed,
    )


@router.post("/fund", response_model=DebugResultOut)
def set_fund(
    save_id: uuid.UUID, body: DebugFundIn, user: CurrentUser, db: DbSession
) -> DebugResultOut:
    save = open_save(db, user, save_id)
    return _result("fund", save, debug_service.set_cash(db, save, body.cash_cents))


@router.post("/time", response_model=DebugResultOut)
def set_time(
    save_id: uuid.UUID, body: DebugTimeIn, user: CurrentUser, db: DbSession
) -> DebugResultOut:
    save = open_save(db, user, save_id)
    return _result("time", save, debug_service.set_clock(db, save, body.minute_of_day))


@router.post("/achievements", response_model=DebugResultOut)
def achievements(
    save_id: uuid.UUID, body: DebugAchievementsIn, user: CurrentUser, db: DbSession
) -> DebugResultOut:
    save = open_save(db, user, save_id)
    changed = debug_service.achievements(db, save, body.action, body.ids)
    return _result("achievements", save, changed)


@router.post("/reset-market", response_model=DebugResultOut)
def reset_market(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DebugResultOut:
    save = open_save(db, user, save_id)
    return _result("reset-market", save, debug_service.reset_market(db, save))


@router.post("/clear", response_model=DebugResultOut)
def clear(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DebugResultOut:
    save = open_save(db, user, save_id)
    return _result("clear", save, debug_service.clear_game(db, save))
