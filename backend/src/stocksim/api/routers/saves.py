"""存档：列表、创建、详情、改名、删除、导出。"""

import uuid

from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.saves import SaveCreateIn, SaveOut, SaveUpdateIn
from stocksim.services import saves as saves_service

router = APIRouter(prefix="/saves", tags=["saves"])


@router.get("", response_model=list[SaveOut])
def list_saves(user: CurrentUser, db: DbSession) -> list:
    return saves_service.list_saves(db, user)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SaveOut)
def create_save(body: SaveCreateIn, user: CurrentUser, db: DbSession) -> object:
    return saves_service.create_save(
        db,
        user,
        name=body.name,
        initial_fund_cents=body.initial_fund_cents,
        buy_fee_rate=body.buy_fee_rate,
        sell_fee_rate=body.sell_fee_rate,
        t0_mode=body.t0_mode,
        trade_unit=body.trade_unit,
        clock_rules=body.clock_rules,
        events_enabled=body.events_enabled,
    )


@router.get("/{save_id}", response_model=SaveOut)
def get_save(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> object:
    return saves_service.open_save(db, user, save_id)


@router.patch("/{save_id}", response_model=SaveOut)
def update_save(save_id: uuid.UUID, body: SaveUpdateIn, user: CurrentUser, db: DbSession) -> object:
    save = saves_service.load_owned_save(db, user, save_id)
    return saves_service.update_save_name(db, save, body.name)


@router.delete("/{save_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_save(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    save = saves_service.load_owned_save(db, user, save_id)
    saves_service.delete_save(db, save)


@router.get("/{save_id}/export")
def export_save(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JSONResponse:
    save = saves_service.open_save(db, user, save_id)
    payload = saves_service.export_save(db, save)
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": f'attachment; filename="stocksim-save-{save.id}.json"'},
    )
