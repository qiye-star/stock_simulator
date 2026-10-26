"""预测市场 REST 的请求与响应模型（04 §9.2）。字段名与服务层字典逐一对应；业务校验在 services/。

保密：响应不含 event_fingerprint、01 §1.8 的隐藏事件字段、scheduled 市场；
open 状态的传闻合约不含 close/resolve 时点。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["buy", "sell"]
MarketStatus = Literal["open", "closed", "resolved", "voided"]


class PmPublicClockOut(BaseModel):
    challenge_id: uuid.UUID
    public_trading_tick: int
    public_trading_day: int
    server_time: datetime


class PmQuestionOut(BaseModel):
    scope: Literal["industry", "stock", "market"] | None
    industry: str | None
    code: str | None
    stock_name: str | None
    from_day: int | None
    to_day: int | None
    edges_bp: list[int]


class PmEventRefOut(BaseModel):
    event_id: str
    kind: str
    scope: str | None
    major: bool
    sentiment: int | None
    title: str
    first_seen_trading_tick: int
    rumor_status: str | None


class PmOutcomeOut(BaseModel):
    idx: int
    key: str
    price_ppm: int


class PmMarketOut(BaseModel):
    id: uuid.UUID
    challenge_id: uuid.UUID
    event_id: str
    kind: Literal["bucket", "rumor"]
    status: MarketStatus
    question: PmQuestionOut
    event: PmEventRefOut
    outcomes: list[PmOutcomeOut]
    open_tt: int
    close_tt: int | None
    resolve_tt: int | None
    opens_at: datetime | None
    closes_at: datetime | None
    resolves_at: datetime | None
    trade_seq: int
    volume_shares: int
    traders: int
    liquidity_b_milli: int
    subsidy_points: int
    winning_outcome: int | None
    resolution_value_bp: int | None
    void_reason: str | None
    my_shares: list[int] | None


class PmMarketPageOut(BaseModel):
    items: list[PmMarketOut]
    next_cursor: str | None
    public: PmPublicClockOut


class PmPositionOutcomeOut(BaseModel):
    idx: int
    shares: int
    cost_points: int
    value_points: int


class PmMyPositionOut(BaseModel):
    outcomes: list[PmPositionOutcomeOut]
    bought_points: int
    sold_points: int
    net_cost_points: int
    value_points: int
    pnl_points: int


class PmLimitsOut(BaseModel):
    market_net_cost_cap_points: int
    market_net_cost_used_points: int
    challenge_buy_cap_points: int
    challenge_buy_used_points: int
    locked_ahead: bool
    eligible: bool


class PmMarketDetailOut(PmMarketOut):
    q_shares: list[int]
    window_change_bp: int | None
    my: PmMyPositionOut | None
    limits: PmLimitsOut
    balance_points: int


class PmQuoteOut(BaseModel):
    market_id: uuid.UUID
    side: Side
    outcome: int
    shares: int
    points: int
    avg_price_ppm: int
    price_before_ppm: int
    prices_after_ppm: list[int]
    trade_seq: int


class PmTradeIn(BaseModel):
    """下单请求体。买入二选一 shares / budget_points；卖出只能给 shares 与 min_proceeds_points。"""

    model_config = ConfigDict(extra="forbid")

    side: Side
    outcome: int = Field(ge=0, le=7)
    shares: int | None = Field(default=None, ge=1, le=200)
    budget_points: int | None = Field(default=None, ge=1)
    max_cost_points: int | None = Field(default=None, ge=0)
    min_proceeds_points: int | None = Field(default=None, ge=0)


class PmTradeOut(BaseModel):
    id: uuid.UUID
    market_id: uuid.UUID
    seq: int
    side: Side
    outcome: int
    shares: int
    points: int
    price_before_ppm: int
    prices_after_ppm: list[int]
    public_tt: int
    created_at: datetime


class PmTradeResultOut(BaseModel):
    trade: PmTradeOut
    market: PmMarketOut
    my: PmMyPositionOut | None
    balance_points: int
    replayed: bool


class PmHistoryPointOut(BaseModel):
    seq: int
    public_tt: int
    at: datetime
    prices_ppm: list[int]


class PmHistoryOut(BaseModel):
    market_id: uuid.UUID
    items: list[PmHistoryPointOut]


class PmTapeItemOut(BaseModel):
    """匿名成交带：不含 user。"""

    seq: int
    side: Side
    outcome: int
    shares: int
    points: int
    public_tt: int
    at: datetime


class PmTapePageOut(BaseModel):
    items: list[PmTapeItemOut]
    next_cursor: str | None


class PmPositionSummaryOut(BaseModel):
    market: PmMarketOut
    my: PmMyPositionOut | None


class PmPositionPageOut(BaseModel):
    items: list[PmPositionSummaryOut]
    next_cursor: str | None


class PmSettlementOut(BaseModel):
    market_id: uuid.UUID
    event_id: str
    kind: Literal["resolved", "voided"]
    question: PmQuestionOut
    market_kind: Literal["bucket", "rumor"]
    winning_outcome: int | None
    winning_shares: int
    payout_points: int
    net_cost_points: int
    pnl_points: int
    created_at: datetime


class PmSettlementPageOut(BaseModel):
    items: list[PmSettlementOut]
    next_cursor: str | None


class PmDebugVoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=32)


class PmDebugSyncOut(BaseModel):
    changed: int
