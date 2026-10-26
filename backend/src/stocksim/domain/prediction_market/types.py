"""预测市场的数据类型（04 §4.1）。全部不可变；金额为整数积分，价格为整数 ppm。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ContractKind = Literal["bucket", "rumor"]
Scope = Literal["industry", "stock", "market"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class ContractSpec:
    """一份合约的定义（04 §3.2）。文本只使用 01 §1.8 允许公开的字段，不含隐藏量。

    bucket：n_outcomes=5，edges_bp 为四个边界，from_day/to_day 为窗口（含端点）。
    rumor：n_outcomes=2，选项序 (deny, confirm)，edges_bp=()，from_day/to_day=None。
    open_tt / close_tt / resolve_tt 均为挑战公共时间线上的 trading tick
    （close 之后停止交易，resolve 之后结算）。
    """

    kind: ContractKind
    event_id: str
    scope: Scope | None
    industry: str | None
    code: str | None
    from_day: int | None
    to_day: int | None
    edges_bp: tuple[int, ...]
    n_outcomes: int
    prior_ppm: tuple[int, ...]
    open_tt: int
    close_tt: int
    resolve_tt: int
    close_public: bool


@dataclass(frozen=True)
class Quote:
    """一次报价（04 §4.1）。points 为买入花费或卖出回款（整数积分，已按 §4.3 取整）。"""

    side: Side
    outcome: int
    shares: int
    points: int
    avg_price_ppm: int
    price_before_ppm: int
    prices_after_ppm: tuple[int, ...]


@dataclass(frozen=True)
class LimitState:
    """限额检查所需的、由服务层查好的用户状态（04 §5.5）。

    subsidy_points：本市场开市时记录的补贴 S（决定单市场净投入上限）。
    market_net_cost_points：该用户在本市场 Σ买入花费 − Σ卖出回款（各选项合计，可为负）。
    challenge_buy_points：该用户在本场挑战内累计买入花费（只累计买入）。
    held_shares：该用户在本选项的当前持仓份额。
    """

    subsidy_points: int
    market_net_cost_points: int
    challenge_buy_points: int
    held_shares: int
