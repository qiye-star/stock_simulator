"""下单与成交流水：POST /saves/{id}/orders（可选 Idempotency-Key）、GET trades（游标分页）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.orders import OrderIn, OrderOut, TradeOut, TradePageOut
from stocksim.services import trading as trading_service
from stocksim.services.saves import open_save

router = APIRouter(tags=["orders"])


@router.post(
    "/saves/{save_id}/orders", status_code=status.HTTP_201_CREATED, response_model=OrderOut
)
def place_order(
    save_id: uuid.UUID,
    body: OrderIn,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=64)] = None,
) -> OrderOut:
    save = open_save(db, user, save_id)
    placed = trading_service.place_order_detailed(
        db,
        save,
        user.id,
        code=body.code,
        side=body.side,
        quantity=body.quantity,
        price_type=body.price_type,
        limit_price_cents=body.limit_price_cents,
        confirm_deviation=body.confirm_deviation,
        idempotency_key=idempotency_key or None,
    )
    if placed.replayed:
        response.status_code = status.HTTP_200_OK
    return OrderOut(
        trade=TradeOut.model_validate(trading_service.trade_to_dict(placed.trade)),
        unlocked_achievement_ids=list(placed.unlocked_achievement_ids),
        cash_cents=placed.cash_cents,
        replayed=placed.replayed,
    )


@router.get("/saves/{save_id}/trades", response_model=TradePageOut)
def list_trades(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    cursor: str | None = None,
) -> TradePageOut:
    save = open_save(db, user, save_id)
    rows, next_cursor = trading_service.list_trades(db, save, cursor)
    return TradePageOut(
        items=[TradeOut.model_validate(trading_service.trade_to_dict(t)) for t in rows],
        next_cursor=next_cursor,
    )
