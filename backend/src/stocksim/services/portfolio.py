"""持仓与资产视图：按当前行情估值；可卖股数由当日成交推导（T+1）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.domain.rules import sellable_quantity
from stocksim.models import Save, Trade
from stocksim.services.equity import equity_curve
from stocksim.services.market import load_market
from stocksim.services.stocks import get_stock_info
from stocksim.services.trading import load_holdings, today_trade_refs


def _prev_close_equity(
    db: Session, save: Save, state: dict[str, Any], quantities: dict[str, int]
) -> int:
    """昨日收盘权益：把当日成交倒推回去，现金与持仓按昨收（prev_close）估值。

    cash_start = 现金 - 当日成交现金变动之和；qty_start = 现持仓 - 当日买卖净股数。
    不依赖快照表，导入存档/调试改动后也自洽；调试加资金（set_cash）会被计入当日盈亏。
    """
    trading_day = int(state["trading_day"])
    prev_close = {s["code"]: int(s["prev_close"]) for s in state["stocks"]}
    cash_start = save.cash_cents
    qty_start = dict(quantities)
    rows = db.execute(
        select(Trade.stock_code, Trade.side, Trade.quantity, Trade.cash_delta_cents).where(
            Trade.save_id == save.id, Trade.trading_day == trading_day
        )
    ).all()
    for code, side, qty, cash_delta in rows:
        cash_start -= cash_delta
        qty_start[code] = qty_start.get(code, 0) - (qty if side == "buy" else -qty)
    return cash_start + sum(q * prev_close.get(c, 0) for c, q in qty_start.items())


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
    prev_equity = _prev_close_equity(
        db, save, state, {h["code"]: h["quantity"] for h in holdings_out}
    )
    day_pnl = equity - prev_equity
    return {
        "tick": save.tick,
        "trading_day": trading_day,
        "cash_cents": save.cash_cents,
        "initial_fund_cents": save.initial_fund_cents,
        "market_value_cents": market_value_total,
        "equity_cents": equity,
        "net_pnl_cents": equity - save.initial_fund_cents,
        "holdings": holdings_out,
        "prev_equity_cents": prev_equity,
        "day_pnl_cents": day_pnl,
        "day_pnl_bp": round_half_up_div(day_pnl * BP_DENOMINATOR, prev_equity)
        if prev_equity > 0
        else 0,
    }


def equity_curve_view(db: Session, save: Save, range_: str) -> dict[str, Any]:
    """资产曲线：初始点 + 各已收盘交易日快照 + 当前交易日实时点。"""
    pf = portfolio_view(db, save)
    live = (pf["equity_cents"], pf["cash_cents"], pf["market_value_cents"])
    items = equity_curve(db, save, live, pf["trading_day"], range_)
    return {"range": range_, "items": items}


__all__ = ["equity_curve_view", "portfolio_view"]
