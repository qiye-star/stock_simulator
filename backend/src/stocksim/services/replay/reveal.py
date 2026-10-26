"""揭示页（05 §1.6、§5.8）：结算后可见。真名、真日期、完整 K 线、事件影响、题目对错与资产曲线。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.money import round_half_up_div
from stocksim.domain.replay import return_bp
from stocksim.models import Trade, User
from stocksim.services import equity as equity_service
from stocksim.services.replay import predictions, sessions
from stocksim.services.replay.feed import ordered_events, to_feed_item
from stocksim.services.replay.state import Ctx, load_ctx, stock_view


def _real_candles(ctx: Ctx, stock_key: str) -> list[dict[str, Any]]:
    stock = ctx.pack.stock(stock_key)
    bars = ctx.pack.bars[stock.key]
    out: list[dict[str, Any]] = []
    for d in range(-ctx.lookback, ctx.pack.play_days + ctx.pack.reveal_days):
        idx = ctx.index(d)
        o, h, lo, c, vol, _lim, _flags = bars[idx]
        out.append(
            {
                "trading_day": d,
                "date": ctx.pack.calendar[idx],
                "open_cents": o,
                "high_cents": h,
                "low_cents": lo,
                "close_cents": c,
                "volume": vol,
            }
        )
    return out


def reveal(db: Session, user: User, save_id: uuid.UUID) -> dict[str, Any]:
    save = sessions.load_session_save(db, user, save_id)
    ctx = load_ctx(db, save)
    if not ctx.settled:
        raise AppError(ErrorCode.REPLAY_REVEAL_LOCKED, {"save_id": str(save.id)})
    session = ctx.session
    pack = ctx.pack
    answers = predictions.answers_by_question(db, save.id)

    stocks = []
    for stock in pack.stocks:
        visible_code, _ = stock_view(stock, ctx.masked)
        stocks.append(
            {
                "code": visible_code,
                "real_code": stock.real_code,
                "real_name": stock.real_name,
                "industry": stock.industry,
                "candles": _real_candles(ctx, stock.key),
                "play_range": [0, pack.play_days - 1],
            }
        )

    benchmark_points = [
        {
            "trading_day": d,
            "date": pack.calendar[ctx.index(d)],
            "close": pack.benchmark.closes_adj[ctx.index(d)],
        }
        for d in range(-ctx.lookback, pack.play_days + pack.reveal_days)
    ]

    events = []
    for ev in ordered_events(pack):
        item = to_feed_item(ev, ctx, reveal=True)
        item["impact"] = ev.impact.model_dump() if ev.impact is not None else None
        item["sentiment"] = ev.sentiment
        events.append(item)

    questions = [
        predictions.question_out(ctx, q, answers.get(q.id), reveal=True) for q in pack.questions
    ]

    final = int(session.final_equity_cents or 0)
    cash = int(save.cash_cents)
    live = (final, cash, final - cash)
    equity_points = equity_service.equity_curve(db, save, live, int(save.trading_day), "all")

    trades_count = db.scalar(
        select(func.count()).select_from(Trade).where(Trade.save_id == save.id)
    )
    last_day = pack.play_days - 1
    all_returns = [
        return_bp(
            pack.bars[s.key][ctx.index(-1)][3],
            pack.bars[s.key][ctx.index(last_day)][3],
        )
        for s in pack.stocks
    ]
    hold_all = round_half_up_div(sum(all_returns), len(all_returns)) if all_returns else 0

    return {
        "session": sessions.session_view(db, save),
        "commentary": pack.commentary,
        "stocks": stocks,
        "benchmark": {"name": pack.benchmark.name, "points": benchmark_points},
        "events": events,
        "questions": questions,
        "equity": equity_points,
        "trades_count": int(trades_count or 0),
        "hold_all_return_bp": hold_all,
        "benchmark_return_bp": session.benchmark_return_bp,
    }


__all__ = ["reveal"]
