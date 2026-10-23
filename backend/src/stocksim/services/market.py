"""行情推进与时钟：把 wall-clock 时间换算为游戏 tick，并持久化行情。

状态持久化（market_states.payload）：
  {code: [price, prev_close, open, high, low, daily_vol, prev_daily_vol, avg_vol, cb_cooldown],
   "_meta": {"trading_tick": int, "as_of": "YYYY-MM-DD"}}
- `_meta` 为保留键（股票代码都是 6 位数字）。as_of 即交易日 0 的日期。
- 日 K：收盘（交易日切换）时把已结束的一根追加到 candles；当日 K 由状态实时派生，不落库。
- 历史 K 线只保留 candles 表；推进时仅在批次跨交易日时才读取前 4 日的成交量（滚动均量）。

并发：每次推进都修改 saves 行（tick / last_tick_at），由 saves.version 乐观锁保护；
冲突（StaleDataError）时回滚、刷新存档并重算。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.config import get_settings
from stocksim.db.base import utcnow
from stocksim.domain.clock import (
    TICKS_PER_TRADING_DAY,
    advance_minute,
    is_trading_time,
    session_label,
    skip_target_minutes,
    skip_ticks,
)
from stocksim.domain.market_engine import advance, find_stock, init_market, order_book
from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.domain.rules import limit_down_cents, limit_up_cents
from stocksim.models import Candle, MarketState, Save, User, WatchlistItem
from stocksim.services.stocks import industry_ranges, stock_pool

META_KEY = "_meta"
MAX_ATTEMPTS = 3
ROLLING_WINDOW = 4  # 滚动均量需要的前 4 个交易日（连同当日共 5 根，见 domain._rollover）
OPENING_HISTORY = 59  # 开局写入 candles 的已结束历史日数（domain 生成 60 根，最后一根为当日）

# ---------- 编解码 ----------


def encode_payload(state: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    breaker = state["breaker"]
    payload: dict[str, Any] = {
        META_KEY: {"trading_tick": int(state["trading_tick"]), "as_of": as_of.isoformat()}
    }
    for stock in state["stocks"]:
        code = stock["code"]
        payload[code] = [
            int(stock["price"]),
            int(stock["prev_close"]),
            int(stock["open"]),
            int(stock["high"]),
            int(stock["low"]),
            int(stock["daily_volume"]),
            int(stock["prev_daily_volume"]),
            int(stock["avg_volume"]),
            int(breaker.get(code, 0)),
        ]
    return payload


def _day_iso(as_of: date, trading_day: int) -> str:
    return (as_of + timedelta(days=trading_day)).isoformat()


def decode_state(
    payload: Mapping[str, Any], prior: Mapping[str, list[dict[str, Any]]] | None
) -> dict[str, Any]:
    """payload -> domain 行情状态。history 仅含当日（及可选的前序窗口），足以驱动 advance。"""
    meta = payload[META_KEY]
    as_of = date.fromisoformat(meta["as_of"])
    trading_tick = int(meta["trading_tick"])
    day = trading_tick // TICKS_PER_TRADING_DAY
    breaker: dict[str, int] = {}
    stocks: list[dict[str, Any]] = []
    for info in stock_pool():
        price, prev_close, open_, high, low, daily, prev_daily, avg, cooldown = (
            int(v) for v in payload[info.code]
        )
        if cooldown > 0:
            breaker[info.code] = cooldown
        current = {
            "date": _day_iso(as_of, day),
            "open": open_,
            "high": high,
            "low": low,
            "close": price,
            "volume": daily,
        }
        stocks.append(
            {
                "code": info.code,
                "name": info.name,
                "industry": info.industry,
                "profile": info.profile,
                "stock_idx": info.idx,
                "price": price,
                "prev_close": prev_close,
                "open": open_,
                "high": high,
                "low": low,
                "volume": daily,
                "daily_volume": daily,
                "prev_daily_volume": prev_daily,
                "avg_volume": avg,
                "history": [*((prior or {}).get(info.code, [])), current],
            }
        )
    return {"trading_tick": trading_tick, "trading_day": day, "breaker": breaker, "stocks": stocks}


def _meta(payload: Mapping[str, Any]) -> tuple[date, int]:
    meta = payload[META_KEY]
    return date.fromisoformat(meta["as_of"]), int(meta["trading_tick"])


# ---------- 数据库读写 ----------


def _market_row(db: Session, save: Save) -> MarketState:
    row = db.get(MarketState, save.id)
    if row is None:  # 不应发生：创建存档时一并写入
        raise RuntimeError(f"market_states missing for save {save.id}")
    return row


def load_market(db: Session, save: Save) -> tuple[dict[str, Any], date]:
    """读取当前行情状态（不推进）。返回 (state, as_of)。"""
    row = _market_row(db, save)
    as_of, _ = _meta(row.payload)
    return decode_state(row.payload, None), as_of


def _prior_windows(
    db: Session, save_id: uuid.UUID, day: int, as_of: date
) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute(
        select(
            Candle.stock_code,
            Candle.trading_day,
            Candle.open_cents,
            Candle.high_cents,
            Candle.low_cents,
            Candle.close_cents,
            Candle.volume,
        )
        .where(
            Candle.save_id == save_id,
            Candle.trading_day >= day - ROLLING_WINDOW,
            Candle.trading_day < day,
        )
        .order_by(Candle.stock_code, Candle.trading_day)
    ).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for code, td, o, h, low, c, v in rows:
        out.setdefault(code, []).append(
            {"date": _day_iso(as_of, td), "open": o, "high": h, "low": low, "close": c, "volume": v}
        )
    return out


def _persist_closed_day(
    db: Session, save_id: uuid.UUID, closing_day: int, state: Mapping[str, Any]
) -> None:
    rows = []
    for stock in state["stocks"]:
        closed = stock["history"][-2]  # advance 在滚动时追加新一日，倒数第二根即已收盘的一日
        rows.append(
            {
                "id": uuid.uuid4(),
                "save_id": save_id,
                "stock_code": stock["code"],
                "trading_day": closing_day,
                "open_cents": closed["open"],
                "high_cents": closed["high"],
                "low_cents": closed["low"],
                "close_cents": closed["close"],
                "volume": closed["volume"],
            }
        )
    if rows:
        db.execute(Candle.__table__.insert(), rows)


def _batch_rolls(minute: int, trading_tick: int, n: int) -> bool:
    """模拟 n 个 tick，判断其中是否会发生交易日切换（决定是否需要读取滚动窗口）。"""
    m, t = minute, trading_tick
    for _ in range(n):
        m = advance_minute(m)
        if is_trading_time(m):
            t += 1
            if t % TICKS_PER_TRADING_DAY == 0:
                return True
    return False


def _run_ticks(db: Session, save: Save, n: int) -> None:
    """推进 n 个 tick 并写回 market_states 与存档时钟字段（不提交）。"""
    row = _market_row(db, save)
    as_of, trading_tick = _meta(row.payload)
    prior = None
    if _batch_rolls(save.clock_minute, trading_tick, n):
        prior = _prior_windows(db, save.id, trading_tick // TICKS_PER_TRADING_DAY, as_of)
    state = decode_state(row.payload, prior)
    seed = save.market_seed
    minute, tick = save.clock_minute, save.tick
    for _ in range(n):
        minute = advance_minute(minute)
        tick += 1
        rolls = is_trading_time(minute) and (state["trading_tick"] + 1) % TICKS_PER_TRADING_DAY == 0
        closing_day = state["trading_day"]
        state = advance(state, seed, tick, minute)
        if rolls:
            _persist_closed_day(db, save.id, closing_day, state)
    row.payload = encode_payload(state, as_of)
    save.tick = tick
    save.clock_minute = minute
    save.trading_day = state["trading_day"]


def _retrying[T](db: Session, save: Save, action: Callable[[], T]) -> T:
    """乐观锁冲突时回滚、刷新存档后重试 action（action 必须从当前库状态重新计算）。"""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return action()
        except StaleDataError:
            db.rollback()
            db.refresh(save)
            if attempt == MAX_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def _advance_to_now_once(db: Session, save: Save) -> int:
    now = utcnow()
    if save.paused:
        return 0
    if save.last_tick_at is None:
        save.last_tick_at = now
        db.commit()
        return 0
    user = db.get(User, save.user_id)
    rate_ms = user.refresh_rate_ms if user is not None else 3000
    elapsed_ms = int((now - save.last_tick_at).total_seconds() * 1000)
    n = elapsed_ms // rate_ms
    if n <= 0:
        return 0
    cap = get_settings().TICK_CATCHUP_MAX
    if n > cap:
        n = cap
        new_last = now  # 超出补偿上限的时间直接丢弃，避免之后一次性补推
    else:
        new_last = save.last_tick_at + timedelta(milliseconds=n * rate_ms)
    _run_ticks(db, save, n)
    save.last_tick_at = new_last
    db.commit()
    return n


def advance_to_now(db: Session, save: Save) -> int:
    """按 wall-clock 补推 tick（每 refresh_rate_ms 一 tick，上限 TICK_CATCHUP_MAX，暂停不推进）。

    返回本次推进的 tick 数。所有存档级读写接口在访问数据前必须先调用。
    """
    try:
        return _retrying(db, save, lambda: _advance_to_now_once(db, save))
    except StaleDataError:
        return 0  # 另一个请求已推进到同一时刻附近，本次无需再推


def _advance_ticks_once(db: Session, save: Save, n: int) -> int:
    if n <= 0:
        return 0
    _run_ticks(db, save, n)
    save.last_tick_at = utcnow()
    db.commit()
    return n


def advance_ticks(db: Session, save: Save, n: int) -> int:
    """立即推进 n 个 tick（跳过时间、调试时间等）。不考虑暂停；调用方应先 advance_to_now。

    同时把 last_tick_at 置为当前时刻，避免之后的 wall-clock 补推叠加。返回推进的 tick 数。
    """
    return _retrying(db, save, lambda: _advance_ticks_once(db, save, n))


# ---------- 视图 ----------


def watch_codes(db: Session, save_id: uuid.UUID) -> set[str]:
    return set(db.scalars(select(WatchlistItem.stock_code).where(WatchlistItem.save_id == save_id)))


def _quote(stock: Mapping[str, Any], breaker_active: bool, watched: bool) -> dict[str, Any]:
    price = int(stock["price"])
    prev = int(stock["prev_close"])
    change_bp = round_half_up_div((price - prev) * BP_DENOMINATOR, prev) if prev > 0 else 0
    return {
        "code": stock["code"],
        "name": stock["name"],
        "industry": stock["industry"],
        "price_cents": price,
        "prev_close_cents": prev,
        "open_cents": int(stock["open"]),
        "high_cents": int(stock["high"]),
        "low_cents": int(stock["low"]),
        "volume": int(stock["daily_volume"]),
        "change_bp": change_bp,
        "limit_up_cents": limit_up_cents(prev),
        "limit_down_cents": limit_down_cents(prev),
        "circuit_breaker_active": breaker_active,
        "watchlisted": watched,
    }


def clock_view(save: Save, *, skipped_ticks: int = 0) -> dict[str, Any]:
    return {
        "paused": save.paused,
        "tick": save.tick,
        "trading_day": save.trading_day,
        "clock_minute": save.clock_minute,
        "session": session_label(save.clock_minute),
        "skipped_ticks": skipped_ticks,
    }


def market_overview(db: Session, save: Save) -> dict[str, Any]:
    state, _ = load_market(db, save)
    watched = watch_codes(db, save.id)
    return {
        **clock_view(save),
        "stocks": [
            _quote(s, s["code"] in state["breaker"], s["code"] in watched) for s in state["stocks"]
        ],
    }


def _candle_out(
    trading_day: int, as_of: date, o: int, h: int, low: int, c: int, v: int
) -> dict[str, Any]:
    return {
        "trading_day": trading_day,
        "date": _day_iso(as_of, trading_day),
        "open_cents": o,
        "high_cents": h,
        "low_cents": low,
        "close_cents": c,
        "volume": v,
    }


def stock_market(db: Session, save: Save, code: str) -> dict[str, Any] | None:
    state, as_of = load_market(db, save)
    stock = find_stock(state, code)
    if stock is None:
        return None
    rows = db.scalars(
        select(Candle)
        .where(Candle.save_id == save.id, Candle.stock_code == code)
        .order_by(Candle.trading_day.desc())
        .limit(OPENING_HISTORY + 1)
    ).all()
    candles = [
        _candle_out(
            c.trading_day, as_of, c.open_cents, c.high_cents, c.low_cents, c.close_cents, c.volume
        )
        for c in reversed(rows)
    ]
    candles.append(
        _candle_out(
            state["trading_day"],
            as_of,
            int(stock["open"]),
            int(stock["high"]),
            int(stock["low"]),
            int(stock["price"]),
            int(stock["daily_volume"]),
        )
    )
    book = order_book(int(stock["price"]), save.market_seed, save.tick, int(stock["stock_idx"]))
    watched = code in watch_codes(db, save.id)
    return {
        **_quote(stock, code in state["breaker"], watched),
        "candles": candles,
        "order_book": book,
    }


# ---------- 时钟操作 ----------


def pause_clock(db: Session, save: Save) -> dict[str, Any]:
    def act() -> dict[str, Any]:
        save.paused = True
        db.commit()
        return clock_view(save)

    return _retrying(db, save, act)


def resume_clock(db: Session, save: Save) -> dict[str, Any]:
    def act() -> dict[str, Any]:
        save.paused = False
        save.last_tick_at = utcnow()  # 暂停期间不补推
        db.commit()
        return clock_view(save)

    return _retrying(db, save, act)


def skip_clock(db: Session, save: Save) -> dict[str, Any]:
    target = skip_target_minutes(save.clock_minute)
    if target is None:
        return clock_view(save, skipped_ticks=0)
    n = skip_ticks(save.clock_minute, target)
    done = advance_ticks(db, save, n)
    return clock_view(save, skipped_ticks=done)


# ---------- 新存档的行情初始化 ----------


def init_market_for_save(db: Session, save: Save, as_of: date) -> None:
    """生成初始行情、写入 market_states 与历史日 K。调用方负责 flush 后的提交。"""
    stocks = [
        {"code": s.code, "name": s.name, "industry": s.industry, "profile": s.profile}
        for s in stock_pool()
    ]
    state = init_market(save.market_seed, stocks, as_of, industry_ranges())
    rows = []
    for stock in state["stocks"]:
        history = stock["history"]
        for i, candle in enumerate(history[:-1]):  # 最后一根为交易日 0 的当日 K
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "save_id": save.id,
                    "stock_code": stock["code"],
                    "trading_day": i - (len(history) - 1),
                    "open_cents": candle["open"],
                    "high_cents": candle["high"],
                    "low_cents": candle["low"],
                    "close_cents": candle["close"],
                    "volume": candle["volume"],
                }
            )
    db.add(MarketState(save_id=save.id, payload=encode_payload(state, as_of), updated_at=utcnow()))
    db.execute(Candle.__table__.insert(), rows)


__all__ = [
    "advance_ticks",
    "advance_to_now",
    "clock_view",
    "decode_state",
    "encode_payload",
    "init_market_for_save",
    "load_market",
    "market_overview",
    "pause_clock",
    "resume_clock",
    "skip_clock",
    "stock_market",
    "watch_codes",
]
