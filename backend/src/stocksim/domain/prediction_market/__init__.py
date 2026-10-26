"""预测市场纯函数包（04 §4–§5）：LMSR 定价取整、合约生成与结算判定、下单限额。零 I/O。

契约见 docs/10.26-plan/04-预测市场.md；数值全部为整数（积分、份额、ppm、tick）。
"""

from .constants import (
    CHALLENGE_BUY_CAP_POINTS,
    MAX_MARKETS_PER_CHALLENGE,
    MAX_SHARES_PER_TRADE,
    POINTS_PER_SHARE,
    PRICE_PPM_TOTAL,
    SHARE_PAYOUT_POINTS,
    SUBSIDY_TIERS,
)
from .contracts import (
    ContractContext,
    bucket_prior,
    contracts_for_challenge,
    contracts_for_event,
    resolve_bucket,
    resolve_rumor,
)
from .limits import check_trade, market_cap_points
from .lmsr import (
    LMSR_CTX,
    b_for_subsidy,
    buy_cost,
    cost_points,
    max_loss_points,
    max_shares_for_budget,
    prices_ppm,
    quote,
    sell_proceeds,
    subsidy_for,
)
from .types import ContractSpec, LimitState, Quote

__all__ = [
    "CHALLENGE_BUY_CAP_POINTS",
    "LMSR_CTX",
    "MAX_MARKETS_PER_CHALLENGE",
    "MAX_SHARES_PER_TRADE",
    "POINTS_PER_SHARE",
    "PRICE_PPM_TOTAL",
    "SHARE_PAYOUT_POINTS",
    "SUBSIDY_TIERS",
    "ContractContext",
    "ContractSpec",
    "LimitState",
    "Quote",
    "b_for_subsidy",
    "bucket_prior",
    "buy_cost",
    "check_trade",
    "contracts_for_challenge",
    "contracts_for_event",
    "cost_points",
    "market_cap_points",
    "max_loss_points",
    "max_shares_for_budget",
    "prices_ppm",
    "quote",
    "resolve_bucket",
    "resolve_rumor",
    "sell_proceeds",
    "subsidy_for",
]
