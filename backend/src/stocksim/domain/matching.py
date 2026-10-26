"""撮合：单笔订单 -> 成交结果（纯函数，不修改入参）。

legacy 对应：executeTrade / validateTradeParameters / executeBuyTrade / executeSellTrade
（game.js 3245-3530）。与 legacy 的有意差异（见 CLAUDE.md “偏离 legacy”）：
- 限价单：买单限价 ≥ 市价、卖单限价 ≤ 市价时按**市价**成交，否则拒绝 ORDER_LIMIT_NOT_REACHED；
  限价必须在涨跌停区间内（买卖两侧都校验）。市价单直接按市价成交。
- 手续费先单独四舍五入到分。
- 买卖都经由本函数，自动交易复用同一逻辑。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .clock import is_order_time
from .errors import (
    MARKET_CLOSED,
    ORDER_LIMIT_NOT_REACHED,
    STOCK_NOT_FOUND,
    TRADE_CIRCUIT_BREAKER_ACTIVE,
    TRADE_INSUFFICIENT_FUNDS,
    TRADE_INSUFFICIENT_HOLDINGS,
    TRADE_PRICE_DEVIATION_CONFIRM,
    TRADE_PRICE_DEVIATION_EXCEEDED,
    TRADE_PRICE_OUT_OF_LIMIT,
    TRADE_T1_BUY_BLOCKED,
    TRADE_T1_SELL_BLOCKED,
    VALIDATION_ERROR,
    DomainError,
)
from .money import BP_DENOMINATOR, fee_cents
from .rules import (
    MAX_PRICE_CENTS,
    MAX_PRICE_DEVIATION_BP,
    WARN_PRICE_DEVIATION_BP,
    bought_quantity,
    limit_down_cents,
    limit_up_cents,
    t1_buy_blocked,
    validate_quantity,
)
from .types import Account, Holding, OrderRequest, OrderResult, Quote, TradeRecord, TradeSettings


def _check_limit_price(request: OrderRequest, quote: Quote) -> int:
    """校验限价单并返回成交价（市价）。失败抛 DomainError。"""
    limit = request.limit_price_cents
    if (
        limit is None
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or limit > MAX_PRICE_CENTS
    ):
        raise DomainError(VALIDATION_ERROR, {"field": "limit_price_cents"})
    market = quote.price_cents
    prev = quote.prev_close_cents
    up = limit_up_cents(prev, quote.limit_pct_bp)
    down = limit_down_cents(prev, quote.limit_pct_bp)
    if limit > up or limit < down:
        raise DomainError(
            TRADE_PRICE_OUT_OF_LIMIT,
            {"price_cents": limit, "limit_up_cents": up, "limit_down_cents": down},
        )
    crossed = limit >= market if request.side == "buy" else limit <= market
    if not crossed:
        raise DomainError(
            ORDER_LIMIT_NOT_REACHED, {"limit_price_cents": limit, "market_price_cents": market}
        )
    deviation = abs(limit - market) * BP_DENOMINATOR
    if deviation > MAX_PRICE_DEVIATION_BP * market:
        raise DomainError(
            TRADE_PRICE_DEVIATION_EXCEEDED,
            {"market_price_cents": market, "percent": MAX_PRICE_DEVIATION_BP // 100},
        )
    if deviation > WARN_PRICE_DEVIATION_BP * market and not request.confirm_deviation:
        raise DomainError(
            TRADE_PRICE_DEVIATION_CONFIRM,
            {"market_price_cents": market, "percent": WARN_PRICE_DEVIATION_BP // 100},
        )
    return market


def execute_order(
    request: OrderRequest,
    *,
    account: Account,
    quote: Quote,
    settings: TradeSettings,
    trades: Sequence[Mapping[str, Any]],
    trading_day: int,
    minute_of_day: int,
    source: str = "manual",
) -> OrderResult:
    """执行一笔订单。失败抛 DomainError(code, params)。

    trades: 该存档全部成交记录（用于 T+1 推导，只读）。
    trading_day: 当前交易日序号（= 行情 trading_day）。
    minute_of_day: 当前游戏分钟（用于交易时段判断与成交记录）。
    """
    if request.code != quote.code:
        raise DomainError(STOCK_NOT_FOUND, {"code": request.code})
    if request.side not in ("buy", "sell"):
        raise DomainError(VALIDATION_ERROR, {"field": "side"})
    if request.price_type not in ("market", "limit"):
        raise DomainError(VALIDATION_ERROR, {"field": "price_type"})
    validate_quantity(request.quantity, settings.trade_unit)
    if not is_order_time(minute_of_day, settings.clock_rules):
        raise DomainError(MARKET_CLOSED, {"minute_of_day": minute_of_day})
    if quote.circuit_breaker_active:
        raise DomainError(TRADE_CIRCUIT_BREAKER_ACTIVE, {"code": quote.code})

    if request.price_type == "limit":
        fill = _check_limit_price(request, quote)
    else:
        fill = quote.price_cents

    qty = request.quantity
    amount = fill * qty
    holding = account.holdings.get(quote.code)
    fund_before = account.fund_cents

    if request.side == "buy":
        rate = settings.buy_fee_rate
        fee = fee_cents(amount, rate)
        total = amount + fee
        if total > fund_before:
            raise DomainError(
                TRADE_INSUFFICIENT_FUNDS, {"required_cents": total, "available_cents": fund_before}
            )
        if t1_buy_blocked(trades, quote.code, trading_day, settings.t0_mode):
            raise DomainError(TRADE_T1_BUY_BLOCKED, {"code": quote.code})
        pnl = 0
        cash = -total
        prev_qty = holding.quantity if holding else 0
        prev_cost = holding.total_cost_cents if holding else 0
        new_qty = prev_qty + qty
        new_holding: Holding | None = Holding(
            code=quote.code,
            name=quote.name,
            quantity=new_qty,
            total_cost_cents=prev_cost + total,
        )
    else:
        held_qty = holding.quantity if holding else 0
        if held_qty < qty:
            raise DomainError(TRADE_INSUFFICIENT_HOLDINGS, {"held": held_qty, "requested": qty})
        if not settings.t0_mode:
            bought = bought_quantity(trades, quote.code, trading_day)
            available = max(0, held_qty - bought)
            if qty > available:
                raise DomainError(TRADE_T1_SELL_BLOCKED, {"bought": bought, "available": available})
        rate = settings.sell_fee_rate
        fee = fee_cents(amount, rate)
        cash = amount - fee
        avg = holding.avg_cost_cents if holding else 0
        pnl = (fill - avg) * qty - fee
        remaining = held_qty - qty
        if remaining > 0:
            new_holding = Holding(
                code=quote.code,
                name=holding.name if holding else quote.name,
                quantity=remaining,
                total_cost_cents=avg * remaining,
            )
        else:
            new_holding = None

    fund_after = fund_before + cash
    holdings = dict(account.holdings)
    if new_holding is None:
        holdings.pop(quote.code, None)
    else:
        holdings[quote.code] = new_holding

    trade: TradeRecord = {
        "code": quote.code,
        "name": quote.name,
        "industry": quote.industry,
        "side": request.side,
        "price_type": request.price_type,
        "quantity": qty,
        "price_cents": fill,
        "amount_cents": amount,
        "fee_cents": fee,
        "cash_cents": cash,
        "pnl_cents": pnl,
        "trading_day": trading_day,
        "minute_of_day": minute_of_day,
        "prev_close_cents": quote.prev_close_cents,
        "fund_before_cents": fund_before,
        "source": source,
    }
    return OrderResult(
        trade=trade,
        account=Account(fund_cents=fund_after, holdings=holdings),
        fill_price_cents=fill,
        amount_cents=amount,
        fee_cents=fee,
        pnl_cents=pnl,
    )


__all__ = ["execute_order"]
