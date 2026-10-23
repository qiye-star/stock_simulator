"""持仓与资产的响应模型。"""

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
