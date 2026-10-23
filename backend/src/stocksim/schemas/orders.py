"""下单与成交流水的请求/响应模型。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class OrderIn(BaseModel):
    code: str = Field(min_length=1, max_length=6)
    side: Literal["buy", "sell"]
    quantity: StrictInt
    price_type: Literal["market", "limit"] = "market"
    limit_price_cents: StrictInt | None = None
    confirm_deviation: StrictBool = False


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    code: str
    name: str
    side: str
    source: str
    price_type: str
    limit_price_cents: int | None
    price_cents: int
    quantity: int
    gross_cents: int
    fee_cents: int
    cash_delta_cents: int
    realized_pnl_cents: int
    prev_close_cents: int
    tick: int
    trading_day: int
    clock_minute: int
    auto_config_id: uuid.UUID | None
    created_at: datetime


class OrderOut(BaseModel):
    trade: TradeOut
    unlocked_achievement_ids: list[str]
    cash_cents: int
    replayed: bool = False


class TradePageOut(BaseModel):
    items: list[TradeOut]
    next_cursor: str | None
