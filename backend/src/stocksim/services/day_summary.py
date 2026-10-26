"""收盘小结（07 §1.4）：某交易日的涨跌家数、成交汇总、涨跌幅前五与持仓（仅当前日）。

- 当前交易日：行情取自内存状态（price/prev_close），资金取自 portfolio_view（与当日盈亏口径一致）。
- 过去的交易日：行情取自 candles（第 d 日与第 d−1 日收盘价），权益取自 equity_snapshots；
  缺快照的字段为 null（不伪造）。第 0 日的“前一日权益”取初始资金。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import CLOCK_RULES_V2, phase_of
from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.domain.rules import limit_down_cents, limit_up_cents
from stocksim.models import Candle, EquitySnapshot, Save, Trade
from stocksim.services.market import clock_view, load_market, market_key, reject_replay
from stocksim.services.portfolio import portfolio_view
from stocksim.services.stocks import get_stock_info

DAY_SUMMARY_WINDOW = 30  # 可查询的历史交易日数（含当前日之前的 30 日）
TOP_N = 5


def _change_bp(prev: int, close: int) -> int:
    return round_half_up_div((close - prev) * BP_DENOMINATOR, prev) if prev > 0 else 0


def _limit(close: int, prev: int) -> str | None:
    if prev <= 0:
        return None
    if close == limit_up_cents(prev):
        return "up"
    if close == limit_down_cents(prev):
        return "down"
    return None


def _trade_summary(rows: list[Trade]) -> dict[str, int]:
    buys = [t for t in rows if t.side == "buy"]
    sells = [t for t in rows if t.side == "sell"]
    return {
        "count": len(rows),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_amount_cents": sum(int(t.gross_cents) for t in buys),
        "sell_amount_cents": sum(int(t.gross_cents) for t in sells),
        "fee_cents": sum(int(t.fee_cents) for t in rows),
        "realized_pnl_cents": sum(int(t.realized_pnl_cents) for t in rows),
    }


def _market_summary(quotes: list[dict[str, Any]]) -> dict[str, int]:
    total = len(quotes)
    return {
        "total": total,
        "up": sum(1 for q in quotes if q["change_bp"] > 0),
        "down": sum(1 for q in quotes if q["change_bp"] < 0),
        "flat": sum(1 for q in quotes if q["change_bp"] == 0),
        "limit_up": sum(1 for q in quotes if q["limit"] == "up"),
        "limit_down": sum(1 for q in quotes if q["limit"] == "down"),
        "avg_change_bp": round_half_up_div(sum(q["change_bp"] for q in quotes), total)
        if total
        else 0,
    }


def _ranked(quotes: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    up = [q for q in quotes if q["change_bp"] > 0]
    down = [q for q in quotes if q["change_bp"] < 0]
    gainers = sorted(up, key=lambda q: (-q["change_bp"], q["code"]))
    losers = sorted(down, key=lambda q: (q["change_bp"], q["code"]))
    keep = ("code", "name", "close_cents", "change_bp", "limit")
    return (
        [{k: q[k] for k in keep} for q in gainers[:TOP_N]],
        [{k: q[k] for k in keep} for q in losers[:TOP_N]],
    )


def _current_day(db: Session, save: Save, state: Mapping[str, Any]) -> dict[str, Any]:
    pf = portfolio_view(db, save)
    quotes: list[dict[str, Any]] = []
    prices: dict[str, dict[str, Any]] = {}
    for s in state["stocks"]:
        price, prev = int(s["price"]), int(s["prev_close"])
        info = get_stock_info(s["code"])
        q = {
            "code": s["code"],
            "name": info.name if info else s["name"],
            "close_cents": price,
            "change_bp": _change_bp(prev, price),
            "limit": _limit(price, prev),
        }
        quotes.append(q)
        prices[s["code"]] = q
    gainers, losers = _ranked(quotes)
    holdings = [
        {
            "code": h["code"],
            "name": h["name"],
            "quantity": h["quantity"],
            "close_cents": h["market_price_cents"],
            "change_bp": prices[h["code"]]["change_bp"] if h["code"] in prices else 0,
            "market_value_cents": h["market_value_cents"],
        }
        for h in pf["holdings"]
    ]
    return {
        "equity_cents": pf["equity_cents"],
        "prev_equity_cents": pf["prev_equity_cents"],
        "day_pnl_cents": pf["day_pnl_cents"],
        "day_pnl_bp": pf["day_pnl_bp"],
        "cash_cents": pf["cash_cents"],
        "market_value_cents": pf["market_value_cents"],
        "market": _market_summary(quotes),
        "top_gainers": gainers,
        "top_losers": losers,
        "holdings": holdings,
    }


def _past_day(db: Session, save: Save, as_of, day: int) -> dict[str, Any]:
    rows = db.execute(
        select(Candle.stock_code, Candle.trading_day, Candle.close_cents).where(
            Candle.save_id == market_key(save), Candle.trading_day.in_((day - 1, day))
        )
    ).all()
    close_by_day: dict[int, dict[str, int]] = {day - 1: {}, day: {}}
    for code, td, close in rows:
        close_by_day[int(td)][code] = int(close)

    quotes: list[dict[str, Any]] = []
    for code, close in close_by_day[day].items():
        prev = close_by_day[day - 1].get(code)
        if prev is None:
            continue
        info = get_stock_info(code)
        quotes.append(
            {
                "code": code,
                "name": info.name if info else code,
                "close_cents": close,
                "change_bp": _change_bp(prev, close),
                "limit": _limit(close, prev),
            }
        )
    quotes.sort(key=lambda q: q["code"])
    gainers, losers = _ranked(quotes)

    snaps = {
        int(e.trading_day): e
        for e in db.scalars(
            select(EquitySnapshot).where(
                EquitySnapshot.save_id == save.id,
                EquitySnapshot.trading_day.in_((day - 1, day)),
            )
        )
    }
    today = snaps.get(day)
    if day == 0:
        prev_equity: int | None = int(save.initial_fund_cents)
    else:
        prev_snap = snaps.get(day - 1)
        prev_equity = int(prev_snap.equity_cents) if prev_snap is not None else None
    equity = int(today.equity_cents) if today is not None else None
    day_pnl = equity - prev_equity if equity is not None and prev_equity is not None else None
    day_pnl_bp = None
    if day_pnl is not None and prev_equity is not None:
        day_pnl_bp = (
            round_half_up_div(day_pnl * BP_DENOMINATOR, prev_equity) if prev_equity > 0 else 0
        )
    return {
        "equity_cents": equity,
        "prev_equity_cents": prev_equity,
        "day_pnl_cents": day_pnl,
        "day_pnl_bp": day_pnl_bp,
        "cash_cents": int(today.cash_cents) if today is not None else None,
        "market_value_cents": int(today.market_value_cents) if today is not None else None,
        "market": _market_summary(quotes),
        "top_gainers": gainers,
        "top_losers": losers,
        "holdings": None,
    }


def day_summary(db: Session, save: Save, trading_day: int | None = None) -> dict[str, Any]:
    """收盘小结。trading_day 缺省为当前交易日；允许 [max(0, 当前日−30), 当前日]，否则 422。
    复盘存档不支持（没有 candles，收盘信息由揭示页提供，05 §5.3）。"""
    reject_replay(save, "day_summary")
    state, as_of = load_market(db, save)
    current = int(state["trading_day"])
    day = current if trading_day is None else int(trading_day)
    if day > current or day < max(0, current - DAY_SUMMARY_WINDOW):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "trading_day"})

    is_current = day == current
    closed = (not is_current) or phase_of(save.clock_minute, save.clock_rules) == "closed"
    body = (
        _current_day(db, save, state) if is_current else _past_day(db, save, as_of, day)
    )

    trade_rows = list(
        db.scalars(select(Trade).where(Trade.save_id == save.id, Trade.trading_day == day))
    )
    next_open_at = None
    if is_current and save.clock_rules == CLOCK_RULES_V2 and not save.paused and closed:
        event = clock_view(db, save)["next_event"]
        if event["kind"] == "open":
            next_open_at = event["at"]

    return {
        "trading_day": day,
        "date": (as_of + timedelta(days=day)).isoformat(),
        "clock_rules": "v2" if save.clock_rules == CLOCK_RULES_V2 else "v1",
        "status": "closed" if closed else "trading",
        **body,
        "trades": _trade_summary(trade_rows),
        "next_open_at": next_open_at,
    }


__all__ = ["DAY_SUMMARY_WINDOW", "day_summary"]
