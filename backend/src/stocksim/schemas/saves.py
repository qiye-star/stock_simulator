"""存档的请求/响应模型。金额为整数分；费率为字符串形式的 Decimal。"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer

MAX_INITIAL_FUND_CENTS = 10**13


class SaveCreateIn(BaseModel):
    name: str = Field(default="", max_length=20)
    initial_fund_cents: StrictInt = Field(default=100_000_000, ge=10_000, le=MAX_INITIAL_FUND_CENTS)
    buy_fee_rate: Decimal = Field(default=Decimal("0.0003"), ge=0, le=Decimal("0.1"))
    sell_fee_rate: Decimal = Field(default=Decimal("0.0013"), ge=0, le=Decimal("0.1"))
    t0_mode: bool = False
    trade_unit: Literal[1, 100] = 1


class SaveUpdateIn(BaseModel):
    name: str = Field(max_length=20)


class SaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    mode: str
    initial_fund_cents: int
    cash_cents: int
    buy_fee_rate: Decimal
    sell_fee_rate: Decimal
    t0_mode: bool
    trade_unit: int
    tick: int
    trading_day: int
    clock_minute: int
    paused: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("buy_fee_rate", "sell_fee_rate")
    def _rate_text(self, value: Decimal) -> str:
        return format(value.normalize(), "f")  # 0.000300 -> "0.0003"
