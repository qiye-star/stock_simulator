"""产业链结构（01 §1.6）。静态结构，关闭事件模式的存档同样返回；强度/滞后只对已揭示的边给出。
复盘存档返回 409 REPLAY_UNSUPPORTED {feature:"supply_chain"}（决策 16，防止龙头真实代码泄露匿名）。
"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.events import SupplyChainOut
from stocksim.services import events as events_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}", tags=["supply_chain"])


@router.get("/supply-chain", response_model=SupplyChainOut)
def get_supply_chain(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return events_service.supply_chain(db, save)
