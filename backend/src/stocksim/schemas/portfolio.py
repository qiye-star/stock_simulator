"""持仓与资产的响应模型。"""

from typing import Literal

from pydantic import BaseModel


class HoldingOut(BaseModel):
    code: str
    name: str
    quantity: int
    sellable_quantity: int
    avg_price_cents: int
    total_cost_cents: int
    market_price_cents: int
    market_value_cents: int
    pnl_cents: int
    pnl_bp: int


class PortfolioOut(BaseModel):
    tick: int
    trading_day: int
    cash_cents: int
    initial_fund_cents: int
    market_value_cents: int
    equity_cents: int
    net_pnl_cents: int
    holdings: list[HoldingOut]
    # 当日盈亏：当前权益 - 昨日收盘权益（见 services/portfolio.py）
    prev_equity_cents: int
    day_pnl_cents: int
    day_pnl_bp: int


class EquityPointOut(BaseModel):
    trading_day: int  # 初始点为 -1
    equity_cents: int
    cash_cents: int
    market_value_cents: int
    kind: Literal["initial", "close", "live"]


class EquityCurveOut(BaseModel):
    range: Literal["7d", "30d", "all"]
    items: list[EquityPointOut]
