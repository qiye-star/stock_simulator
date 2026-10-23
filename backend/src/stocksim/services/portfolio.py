"""持仓与资产视图：按当前行情估值；可卖股数由当日成交推导（T+1）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.domain.rules import sellable_quantity
from stocksim.models import Save
from stocksim.services.market import load_market
from stocksim.services.stocks import get_stock_info
from stocksim.services.trading import load_holdings, today_trade_refs


def portfolio_view(db: Session, save: Save) -> dict[str, Any]:
    state, _ = load_market(db, save)
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    trading_day = int(state["trading_day"])
    refs = today_trade_refs(db, save, trading_day)
    holdings_out: list[dict[str, Any]] = []
    market_value_total = 0
    for code, held in sorted(load_holdings(db, save).items()):
        price = prices.get(code, 0)
        market_value = held.quantity * price
        cost = held.total_cost_cents
        pnl = market_value - cost
        info = get_stock_info(code)
        market_value_total += market_value
        holdings_out.append(
            {
                "code": code,
                "name": info.name if info else held.name,
                "quantity": held.quantity,
                "sellable_quantity": sellable_quantity(
                    held.quantity, refs, code, trading_day, save.t0_mode
                ),
                "avg_price_cents": held.avg_cost_cents,
                "total_cost_cents": cost,
                "market_price_cents": price,
                "market_value_cents": market_value,
                "pnl_cents": pnl,
                "pnl_bp": round_half_up_div(pnl * BP_DENOMINATOR, cost) if cost > 0 else 0,
            }
        )
    equity = save.cash_cents + market_value_total
    return {
        "tick": save.tick,
        "trading_day": trading_day,
        "cash_cents": save.cash_cents,
        "initial_fund_cents": save.initial_fund_cents,
        "market_value_cents": market_value_total,
        "equity_cents": equity,
        "net_pnl_cents": equity - save.initial_fund_cents,
        "holdings": holdings_out,
    }


__all__ = ["portfolio_view"]
