"""交易规则（纯函数）：涨跌停、熔断、T+1、数量校验。

legacy 对应：LimitManager（game.js 4-104）、executeTrade/validateTradeParameters（3245-3400）。
所有价格为 int 分；涨跌幅用基点 bp（1 bp = 0.01%）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .errors import TRADE_INVALID_QUANTITY, VALIDATION_ERROR, DomainError
from .money import BP_DENOMINATOR, round_half_up_div

LIMIT_PCT_BP = 1000  # 涨跌停 ±10%（LimitManager 6-7）
CIRCUIT_BREAKER_BP = 500  # 单 tick 波动 ≥5% 触发熔断（P2-1 修复后的阈值）
CIRCUIT_BREAKER_COOLDOWN_TICKS = 3  # 熔断冷却（LimitManager 9）
MAX_PRICE_DEVIATION_BP = 2000  # 委托价偏离市价 >20% 硬阻断（game.js 3380）
WARN_PRICE_DEVIATION_BP = 1000  # 偏离 >10% 需确认（game.js 3383）
MAX_QUANTITY = 1_000_000_000  # legacy 3 行：quantity ≤ 1e9
MAX_PRICE_CENTS = 1_000_000_000  # legacy price ≤ 1e7 元
VALID_TRADE_UNITS = (1, 100)


def limit_up_cents(prev_close_cents: int) -> int:
    """涨停价（分），四舍五入到分。"""
    return round_half_up_div(prev_close_cents * (BP_DENOMINATOR + LIMIT_PCT_BP), BP_DENOMINATOR)


def limit_down_cents(prev_close_cents: int) -> int:
    """跌停价（分），四舍五入到分。"""
    return round_half_up_div(prev_close_cents * (BP_DENOMINATOR - LIMIT_PCT_BP), BP_DENOMINATOR)


def is_within_limits(price_cents: int, prev_close_cents: int) -> bool:
    return limit_down_cents(prev_close_cents) <= price_cents <= limit_up_cents(prev_close_cents)


def clamp_to_limits(price_cents: int, prev_close_cents: int) -> int:
    return min(
        max(price_cents, limit_down_cents(prev_close_cents)), limit_up_cents(prev_close_cents)
    )


def is_limit_up(price_cents: int, prev_close_cents: int) -> bool:
    return price_cents == limit_up_cents(prev_close_cents)


def is_limit_down(price_cents: int, prev_close_cents: int) -> bool:
    return price_cents == limit_down_cents(prev_close_cents)


def breaker_move_exceeded(new_price_cents: int, prev_price_cents: int) -> bool:
    """单 tick 波动是否达到熔断阈值（|new-prev| / prev ≥ 5%）。"""
    if prev_price_cents <= 0:
        return False
    return (
        abs(new_price_cents - prev_price_cents) * BP_DENOMINATOR
        >= prev_price_cents * CIRCUIT_BREAKER_BP
    )


def tick_circuit_breakers(cooldowns: Mapping[str, int], triggered: Iterable[str]) -> dict[str, int]:
    """推进一个 tick 的熔断状态（legacy 先 trigger 再 updateCooldown）。

    返回 {code: 剩余冷却 tick}，仅包含 >0 的项。
    """
    state = dict(cooldowns)
    for code in triggered:
        state[code] = CIRCUIT_BREAKER_COOLDOWN_TICKS
    result: dict[str, int] = {}
    for code, remaining in state.items():
        if remaining - 1 > 0:
            result[code] = remaining - 1
    return result


def circuit_breaker_active(cooldowns: Mapping[str, int], code: str) -> bool:
    return cooldowns.get(code, 0) > 0


def validate_trade_unit(trade_unit: int) -> None:
    if trade_unit not in VALID_TRADE_UNITS:
        raise DomainError(
            VALIDATION_ERROR, {"field": "trade_unit", "allowed": list(VALID_TRADE_UNITS)}
        )


def validate_quantity(quantity: int, trade_unit: int) -> None:
    """数量须为正整数、不超过上限、且为交易单位整数倍。"""
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise DomainError(TRADE_INVALID_QUANTITY, {"quantity": quantity})
    if quantity <= 0 or quantity > MAX_QUANTITY or quantity % trade_unit != 0:
        raise DomainError(TRADE_INVALID_QUANTITY, {"quantity": quantity, "unit": trade_unit})


def bought_quantity(trades: Sequence[Mapping[str, object]], code: str, trading_day: int) -> int:
    """当日（trading_day）该股票的累计买入股数，由成交记录推导。"""
    return sum(
        int(t["quantity"])  # type: ignore[call-overload]
        for t in trades
        if t["code"] == code and t["side"] == "buy" and t["trading_day"] == trading_day
    )


def sold_quantity(trades: Sequence[Mapping[str, object]], code: str, trading_day: int) -> int:
    return sum(
        int(t["quantity"])  # type: ignore[call-overload]
        for t in trades
        if t["code"] == code and t["side"] == "sell" and t["trading_day"] == trading_day
    )


def sellable_quantity(
    held_quantity: int,
    trades: Sequence[Mapping[str, object]],
    code: str,
    trading_day: int,
    t0_mode: bool,
) -> int:
    """当前可卖股数。T+0 模式下等于持仓；否则扣除当日买入（T+1）。"""
    if t0_mode:
        return held_quantity
    return max(0, held_quantity - bought_quantity(trades, code, trading_day))


def t1_buy_blocked(
    trades: Sequence[Mapping[str, object]], code: str, trading_day: int, t0_mode: bool
) -> bool:
    """legacy 规则：T+1 模式下当日已卖出的股票禁止再买入（game.js 3357-3363）。"""
    return not t0_mode and sold_quantity(trades, code, trading_day) > 0
