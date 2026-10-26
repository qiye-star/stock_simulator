"""情报卡（02 §10.1）：边强度 L1/L2、传闻提示。关闭事件的存档 → 409 EVENTS_DISABLED。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.intel import EdgeRevealIn, IntelPurchaseOut, IntelStateOut, RumorHintIn
from stocksim.services import intel as intel_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/intel", tags=["intel"])


@router.get("", response_model=IntelStateOut)
def get_intel(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return intel_service.state(db, save)


@router.post("/edges", response_model=IntelPurchaseOut)
def buy_edge(save_id: uuid.UUID, body: EdgeRevealIn, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return intel_service.buy_edge_reveal(db, save, edge_id=body.edge_id, level=body.level)


@router.post("/rumor-hints", response_model=IntelPurchaseOut)
def buy_rumor_hint(save_id: uuid.UUID, body: RumorHintIn, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return intel_service.buy_rumor_hint(db, save, event_id=body.event_id)
