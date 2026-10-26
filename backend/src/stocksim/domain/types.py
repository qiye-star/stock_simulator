"""领域数据类型（不可变为主）。金额全部为 int 分。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, TypedDict

from .money import round_half_up_div
from .rules import LIMIT_PCT_BP

Side = Literal["buy", "sell"]
PriceType = Literal["market", "limit"]


class TradeRecord(TypedDict):
    """一笔成交的持久化形态（services 落库 trades 表；domain 只读取）。

    trade-time 快照字段（prev_close_cents / fund_before_cents）保证成就等统计
    不随之后的行情或资金变化而改变。
    """

    code: str
    name: str
    industry: str
    side: str  # "buy" | "sell"
    price_type: str  # "market" | "limit"
    quantity: int
    price_cents: int  # 成交价（限价单为市价成交价，见 matching.py）
    amount_cents: int  # 成交金额 = 价 * 量
    fee_cents: int
    cash_cents: int  # 现金变动：买 = -(金额+手续费)；卖 = 金额-手续费
    pnl_cents: int  # 仅卖出有值，买入为 0
    trading_day: int
    minute_of_day: int
    prev_close_cents: int
    fund_before_cents: int
    source: str  # "manual" | "auto"


@dataclass(frozen=True)
class Holding:
    code: str
    name: str
    quantity: int
    total_cost_cents: int  # 含买入手续费的累计成本

    @property
    def avg_cost_cents(self) -> int:
        if self.quantity <= 0:
            return 0
        return round_half_up_div(self.total_cost_cents, self.quantity)


@dataclass(frozen=True)
class Account:
    fund_cents: int
    holdings: Mapping[str, Holding] = field(default_factory=dict)


@dataclass(frozen=True)
class Quote:
    """单只股票在某一时刻的行情快照（由 market_engine 状态派生）。"""

    code: str
    name: str
    industry: str
    price_cents: int
    prev_close_cents: int
    circuit_breaker_active: bool = False
    limit_pct_bp: int = LIMIT_PCT_BP  # 涨跌幅（基点）：主板 1000、创业板 2000（复盘按板块）


@dataclass(frozen=True)
class TradeSettings:
    buy_fee_rate: Decimal = Decimal("0.0003")
    sell_fee_rate: Decimal = Decimal("0.0013")
    trade_unit: int = 1  # 1 或 100
    t0_mode: bool = False
    clock_rules: int = 1  # 撮合窗口按规则版本判断（v1 = is_trading_time，v2 = 半开区间）


@dataclass(frozen=True)
class OrderRequest:
    code: str
    side: Side
    quantity: int
    price_type: PriceType = "market"
    limit_price_cents: int | None = None
    confirm_deviation: bool = False


@dataclass(frozen=True)
class OrderResult:
    trade: TradeRecord
    account: Account  # 成交后的新账户（不修改入参）
    fill_price_cents: int
    amount_cents: int
    fee_cents: int
    pnl_cents: int
