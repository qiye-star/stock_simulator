"""下单限额的纯函数判定（04 §5.5）。参数由服务层查好（LimitState）后传入；违反即抛 DomainError。

不在本模块的规则（需要数据库或墙钟）：
- 频率 RATE_LIMIT_TRADES / 60 s（读 prediction_trades.created_at，服务层计数）；
- 账号年龄（读 03 的 CHALLENGE_MIN_ACCOUNT_AGE_HOURS，服务层判定）；
- 超前锁定 PM_LOCKED_AHEAD、市场状态 PM_NOT_OPEN、滑点 PM_SLIPPAGE_EXCEEDED（服务层）。
"""

from __future__ import annotations

from typing import Final

from ..errors import VALIDATION_ERROR, DomainError
from .constants import (
    CHALLENGE_BUY_CAP_POINTS,
    MARKET_NET_COST_CAP_MIN,
    MAX_SHARES_PER_TRADE,
)
from .types import LimitState, Side

PM_POSITION_LIMIT: Final = "PM_POSITION_LIMIT"
PM_DAILY_LIMIT: Final = "PM_DAILY_LIMIT"
PM_INSUFFICIENT_SHARES: Final = "PM_INSUFFICIENT_SHARES"
PM_TRADE_TOO_SMALL: Final = "PM_TRADE_TOO_SMALL"


def market_cap_points(subsidy_points: int) -> int:
    """单市场净投入上限：max(200, S // 4)。"""
    if subsidy_points < 0:
        raise ValueError("subsidy_points must be non-negative")
    return max(MARKET_NET_COST_CAP_MIN, subsidy_points // 4)


def check_trade(*, side: Side, shares: int, amount_points: int, state: LimitState) -> None:
    """检查一笔成交是否越限；越限抛 DomainError，通过返回 None。

    amount_points：买入为花费，卖出为回款（均为 lmsr 取整后的整数）。
    顺序：份额范围 → 卖出（持仓、回款为 0）→ 买入（单市场净投入、单场挑战买入额度）。
    卖出不受任何投入上限约束。
    """
    if side not in ("buy", "sell"):
        raise DomainError(VALIDATION_ERROR, {"field": "side", "reason": "invalid"})
    if not isinstance(shares, int) or not 1 <= shares <= MAX_SHARES_PER_TRADE:
        raise DomainError(VALIDATION_ERROR, {"field": "shares", "reason": "range"})
    if side == "sell":
        if shares > state.held_shares:
            raise DomainError(
                PM_INSUFFICIENT_SHARES, {"held": state.held_shares, "requested": shares}
            )
        if amount_points <= 0:
            raise DomainError(PM_TRADE_TOO_SMALL, {})
        return
    cap = market_cap_points(state.subsidy_points)
    if state.market_net_cost_points + amount_points > cap:
        raise DomainError(
            PM_POSITION_LIMIT,
            {"limit_points": cap, "used_points": state.market_net_cost_points},
        )
    if state.challenge_buy_points + amount_points > CHALLENGE_BUY_CAP_POINTS:
        raise DomainError(
            PM_DAILY_LIMIT,
            {"limit_points": CHALLENGE_BUY_CAP_POINTS, "used_points": state.challenge_buy_points},
        )
