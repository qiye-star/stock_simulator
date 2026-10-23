"""成就：目录（全局）与存档已解锁列表。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.achievements import AchievementDefOut, SaveAchievementOut
from stocksim.services import achievements as achievements_service
from stocksim.services.saves import open_save

router = APIRouter(tags=["achievements"])


@router.get("/achievements/catalog", response_model=list[AchievementDefOut])
def get_catalog(user: CurrentUser) -> list[dict]:
    return achievements_service.catalog()


@router.get("/saves/{save_id}/achievements", response_model=list[SaveAchievementOut])
def list_save_achievements(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list:
    save = open_save(db, user, save_id)
    return achievements_service.unlocked_rows(db, save)
