"""复盘存档的行情视图（05 §5.3）：个股详情（日 K + 报价）与当日分时。

K 线只含回看期与已过的游戏日；当日按阶段给出部分 bar（pre_open 不含当日，open 为开盘点，
close/post_close 为完整当日）。报价与持仓共用 services.market 的 `_quote`，保证与普通存档形状一致。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stocksim.domain.replay import display_bar, phase_tick, visible_quote
from stocksim.models import Save
from stocksim.services.market import _quote, watch_codes
from stocksim.services.replay.state import (
    Ctx,
    build_state,
    date_iso,
    display_bar_row,
    find_stock,
    load_ctx,
    scale_of,
)


def visible_close_day(ctx: Ctx) -> int:
    """最后一个已收盘的游戏日（盘前与开盘时为前一日）。"""
    return ctx.day if ctx.phase in ("close", "post_close") else ctx.day - 1


def _candle(ctx: Ctx, day: int, o: int, h: int, low: int, c: int, v: int) -> dict[str, Any]:
    return {
        "trading_day": day,
        "date": date_iso(ctx, day),
        "open_cents": o,
        "high_cents": h,
        "low_cents": low,
        "close_cents": c,
        "volume": v,
    }


def candles_of(ctx: Ctx, stock_key: str, masked: bool) -> list[dict[str, Any]]:
    stock = ctx.pack.stock(stock_key)
    scale = scale_of(stock, masked)
    out: list[dict[str, Any]] = []
    for d in range(-ctx.lookback, ctx.day):  # 已完成的游戏日与回看期
        bar, prev = display_bar_row(ctx, stock, d)
        b = display_bar(bar, prev, scale)
        out.append(_candle(ctx, d, b.open, b.high, b.low, b.close, b.volume))
    if ctx.phase != "pre_open":  # 当日：open 阶段只有开盘点，close/post_close 为完整 bar
        bar, prev = display_bar_row(ctx, stock, ctx.day)
        q = visible_quote(bar, prev, scale, ctx.phase)
        out.append(_candle(ctx, ctx.day, q.open, q.high, q.low, q.price, q.volume))
    return out


def stock_market(db: Session, save: Save, code: str) -> dict[str, Any] | None:
    ctx = load_ctx(db, save)
    hit = find_stock(ctx, code)
    if hit is None:
        return None
    _, stock, visible_code, _ = hit
    state = build_state(ctx, int(save.tick))
    row = next(s for s in state["stocks"] if s["code"] == visible_code)
    watched = visible_code in watch_codes(db, save.id)
    return {
        **_quote(row, False, watched),
        "suspended": bool(row["replay_flags"]["suspended"]),
        "candles": candles_of(ctx, stock.key, ctx.masked),
        "order_book": {"bids": [], "asks": []},
    }


def intraday(db: Session, save: Save, code: str) -> dict[str, Any] | None:
    """阶段决定分时点：open 有开盘点，close 之后再加收盘点（exact=True）。"""
    ctx = load_ctx(db, save)
    hit = find_stock(ctx, code)
    if hit is None:
        return None
    _, stock, visible_code, _ = hit
    bar, prev = display_bar_row(ctx, stock, ctx.day)
    scale = scale_of(stock, ctx.masked)
    open_q = visible_quote(bar, prev, scale, "open")
    close_q = visible_quote(bar, prev, scale, "close")
    points: list[dict[str, int]] = []
    if ctx.phase in ("open", "close", "post_close"):
        points.append(
            {
                "minute": 570,
                "tick": phase_tick(ctx.day, "open"),
                "price_cents": open_q.price,
                "volume": 0,
            }
        )
    if ctx.phase in ("close", "post_close"):
        points.append(
            {
                "minute": 900,
                "tick": phase_tick(ctx.day, "close"),
                "price_cents": close_q.price,
                "volume": close_q.volume,
            }
        )
    return {
        "code": visible_code,
        "trading_day": ctx.day,
        "date": date_iso(ctx, ctx.day),
        "clock_minute": int(save.clock_minute),
        "tick": int(save.tick),
        "prev_close_cents": open_q.prev_close,
        "open_cents": open_q.price,
        "points": points,
        "exact": True,
    }


def benchmark(ctx: Ctx) -> dict[str, Any]:
    """基准指数：回看期起至最后已收盘日（点位取 closes_adj，只到当前可见）。"""
    bench = ctx.pack.benchmark
    last = visible_close_day(ctx)
    points = [
        {
            "trading_day": d,
            "date": date_iso(ctx, d),
            "close": bench.closes_adj[ctx.index(d)],
        }
        for d in range(-ctx.lookback, last + 1)
    ]
    return {"name": bench.name if not ctx.masked else "基准指数", "points": points}


def benchmark_close(ctx: Ctx, day: int) -> int:
    return ctx.pack.benchmark.closes_adj[ctx.index(day)]


__all__ = [
    "benchmark",
    "benchmark_close",
    "candles_of",
    "intraday",
    "stock_market",
    "visible_close_day",
]
