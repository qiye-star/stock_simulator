"""自动交易接口：条件单 CRUD、启停/暂停/恢复/重置、事件分页。业务逻辑见 services/auto_trade.py。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.models import AutoTradeConfig, AutoTradeEvent, User
from stocksim.schemas.auto_trade import (
    AutoConfigIn,
    AutoConfigList,
    AutoConfigOut,
    AutoEventOut,
    AutoEventPage,
    AutoStatusOut,
)
from stocksim.services import auto_trade as service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/auto-trade", tags=["auto-trade"])

LimitQuery = Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)]


def _pct(value: int | None) -> float | None:
    return None if value is None else value / 100


def _config_out(row: AutoTradeConfig, name: str) -> AutoConfigOut:
    return AutoConfigOut(
        id=str(row.id),
        code=row.stock_code,
        name=name,
        direction=row.direction,
        condition_type=row.condition_type,
        condition_operator=None if row.condition_type == "time" else row.condition_operator,
        condition_value_cents=row.condition_value_cents,
        condition_percent=_pct(row.condition_pct100),
        quantity=row.quantity,
        price_type=row.price_type,
        limit_price_cents=row.limit_price_cents,
        stop_loss_percent=_pct(row.stop_loss_pct100),
        take_profit_percent=_pct(row.take_profit_pct100),
        max_trades=row.max_trades,
        max_amount_cents=row.max_amount_cents,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_out(row: AutoTradeEvent) -> AutoEventOut:
    return AutoEventOut(
        id=str(row.id),
        config_id=str(row.config_id) if row.config_id else None,
        stock_code=row.stock_code,
        direction=row.direction,
        condition_type=row.condition_type,
        success=row.success,
        reason_code=None if row.success else (row.message or None),
        amount_cents=row.amount_cents,
        pnl_cents=row.pnl_cents,
        pnl_percent=None if row.pnl_pct100 is None else row.pnl_pct100 / 100,
        buy_price_cents=row.buy_price_cents,
        sell_price_cents=row.sell_price_cents,
        tick=row.tick,
        trading_day=row.trading_day,
        created_at=row.created_at,
    )


@router.get("/configs", response_model=AutoConfigList)
def list_configs(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoConfigList:
    save = open_save(db, user, save_id)
    return AutoConfigList(items=[_config_out(r, n) for r, n in service.list_configs(db, save)])


@router.post("/configs", status_code=status.HTTP_201_CREATED, response_model=AutoConfigOut)
def create_config(
    save_id: uuid.UUID, body: AutoConfigIn, user: CurrentUser, db: DbSession
) -> AutoConfigOut:
    save = open_save(db, user, save_id)
    row, name = service.create_config(db, save, body)
    return _config_out(row, name)


@router.put("/configs/{config_id}", response_model=AutoConfigOut)
def update_config(
    save_id: uuid.UUID,
    config_id: uuid.UUID,
    body: AutoConfigIn,
    user: CurrentUser,
    db: DbSession,
) -> AutoConfigOut:
    save = open_save(db, user, save_id)
    row, name = service.update_config(db, save, config_id, body)
    return _config_out(row, name)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    save_id: uuid.UUID, config_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    save = open_save(db, user, save_id)
    service.delete_config(db, save, config_id)


@router.get("/status", response_model=AutoStatusOut)
def get_status(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    save = open_save(db, user, save_id)
    return AutoStatusOut(**service.status(db, save))


@router.post("/start", response_model=AutoStatusOut)
def start(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    return _run_action(save_id, user, db, "start")


@router.post("/pause", response_model=AutoStatusOut)
def pause(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    return _run_action(save_id, user, db, "pause")


@router.post("/resume", response_model=AutoStatusOut)
def resume(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    return _run_action(save_id, user, db, "resume")


@router.post("/stop", response_model=AutoStatusOut)
def stop(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    return _run_action(save_id, user, db, "stop")


@router.post("/reset", response_model=AutoStatusOut)
def reset(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AutoStatusOut:
    return _run_action(save_id, user, db, "reset")


def _run_action(save_id: uuid.UUID, user: User, db: Session, action: str) -> AutoStatusOut:
    save = open_save(db, user, save_id)
    return AutoStatusOut(**service.run_action(db, save, action))


@router.get("/events", response_model=AutoEventPage)
def list_events(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    cursor: str | None = None,
    limit: LimitQuery = service.DEFAULT_PAGE_SIZE,
) -> AutoEventPage:
    save = open_save(db, user, save_id)
    rows, next_cursor = service.list_events(db, save, cursor, limit)
    return AutoEventPage(items=[_event_out(r) for r, _ in rows], next_cursor=next_cursor)
