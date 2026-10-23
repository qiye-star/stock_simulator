"""自选股：PUT/DELETE /saves/{id}/watchlist/{code}（幂等）。"""

import uuid

from fastapi import APIRouter, status

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.services import saves as saves_service

router = APIRouter(prefix="/saves/{save_id}/watchlist", tags=["watchlist"])


@router.put("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def add_item(save_id: uuid.UUID, code: str, user: CurrentUser, db: DbSession) -> None:
    save = saves_service.open_save(db, user, save_id)
    saves_service.add_watchlist(db, save, code)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(save_id: uuid.UUID, code: str, user: CurrentUser, db: DbSession) -> None:
    save = saves_service.open_save(db, user, save_id)
    saves_service.remove_watchlist(db, save, code)
