"""自动交易的请求/响应模型。金额为整数分（`_cents`），百分比为 float（如 2.5 表示 2.5%）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CODE = r"^\d{6}$"
_MAX_QTY = 1_000_000_000
_MAX_CENTS = 1_000_000_000_000  # 1e10 元


class AutoConfigIn(BaseModel):
    """创建/整体替换一条条件单（PUT 为全量替换）。

    规则（服务层再次校验）：
    - price/profit 条件需要 condition_operator 与 condition_value_cents；
    - percentage 条件需要 condition_operator 与 condition_percent；
    - time 条件不需要 operator 与阈值；
    - profit 条件仅适用于卖出；
    - price_type=limit 时需要 limit_price_cents。
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=_CODE)
    direction: Literal["buy", "sell"]
    condition_type: Literal["price", "percentage", "profit", "time"]
    condition_operator: Literal["above", "below", "equal"] | None = None
    condition_value_cents: int | None = Field(default=None, ge=0, le=_MAX_CENTS)
    condition_percent: float | None = Field(default=None, ge=0, le=1000)
    quantity: int = Field(gt=0, le=_MAX_QTY)
    price_type: Literal["market", "limit"] = "market"
    limit_price_cents: int | None = Field(default=None, gt=0, le=_MAX_CENTS)
    stop_loss_percent: float | None = Field(default=None, ge=0, le=100)
    take_profit_percent: float | None = Field(default=None, ge=0, le=1000)
    max_trades: int = Field(default=0, ge=0, le=100_000)
    max_amount_cents: int | None = Field(default=None, ge=0, le=_MAX_CENTS)
    enabled: bool = True

    @model_validator(mode="after")
    def _shape(self) -> "AutoConfigIn":
        if self.price_type == "limit" and self.limit_price_cents is None:
            raise ValueError("limit_price_cents required for limit orders")
        if self.price_type == "market" and self.limit_price_cents is not None:
            raise ValueError("limit_price_cents only allowed for limit orders")
        return self


class AutoConfigOut(BaseModel):
    id: str
    code: str
    name: str
    direction: str
    condition_type: str
    condition_operator: str | None
    condition_value_cents: int | None
    condition_percent: float | None
    quantity: int
    price_type: str
    limit_price_cents: int | None
    stop_loss_percent: float | None
    take_profit_percent: float | None
    max_trades: int
    max_amount_cents: int | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AutoConfigList(BaseModel):
    items: list[AutoConfigOut]


class AutoStatusOut(BaseModel):
    enabled: bool
    paused: bool
    max_total_trades: int
    total_trades: int
    success_trades: int
    failed_trades: int
    total_pnl_cents: int


class AutoEventOut(BaseModel):
    id: str
    config_id: str | None
    stock_code: str
    direction: str
    condition_type: str
    success: bool
    reason_code: str | None
    amount_cents: int
    pnl_cents: int
    pnl_percent: float | None
    buy_price_cents: int | None
    sell_price_cents: int | None
    tick: int
    trading_day: int
    created_at: datetime


class AutoEventPage(BaseModel):
    items: list[AutoEventOut]
    next_cursor: str | None
