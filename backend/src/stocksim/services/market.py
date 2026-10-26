"""行情推进与时钟：把 wall-clock 时间换算为游戏 tick，并持久化行情。

状态持久化（market_states.payload）：
  {code: [price, prev_close, open, high, low, daily_vol, prev_daily_vol, avg_vol, cb_cooldown],
   "_meta": {"trading_tick": int, "as_of": "YYYY-MM-DD"}}
- `_meta` 为保留键（股票代码都是 6 位数字）。as_of 即交易日 0 的日期。
- 日 K：收盘（交易日切换）时把已结束的一根追加到 candles；当日 K 由状态实时派生，不落库。
- 历史 K 线只保留 candles 表；推进时仅在批次跨交易日时才读取前 4 日的成交量（滚动均量）。

并发：每次推进都修改 saves 行（tick / last_tick_at），由 saves.version 乐观锁保护；
冲突（StaleDataError）时回滚、刷新存档并重算。

跨交易日的并发补推还会撞上 candles / equity_snapshots 的唯一约束：另一事务已提交同一交易日的
收盘数据，本事务的写入就抛 IntegrityError（SQLite 立即抛；PostgreSQL 在对方提交后抛）。
这与 StaleDataError 同属“他人已推进”，由 `_retrying` 一并处理：回滚、重读最新存档后重算，
此时 last_tick_at 已被推进，通常无事可做（n=0）而正常返回。写入本身不做 insert-or-ignore：
忽略冲突会让本事务带着过期的行情 payload 继续提交，必须整体回滚重算才正确，且避免方言分支。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.config import get_settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.clock import (
    CLOCK_RULES_V1,
    CLOCK_RULES_V2,
    DEFAULT_CLOCK_SPEED,
    MINUTES_PER_DAY,
    SPEED_MS_PER_MINUTE,
    V2_CLOSE_MINUTE,
    V2_LUNCH_MINUTE,
    TimeBase,
    advance_minute,
    is_order_time,
    is_trading_time,
    ms_until_minute_v2,
    next_event_of,
    next_step_v2,
    phase_of,
    plan_catchup_v2,
    session_label,
    session_label_v2,
    skip_target_minutes,
    skip_target_v2,
    skip_ticks,
    timebase,
    v2_expected_offset,
)
from stocksim.domain.market_engine import advance, find_stock, init_market, order_book
from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.domain.rules import LIMIT_PCT_BP, limit_down_cents, limit_up_cents
from stocksim.models import Candle, MarketState, Save, User, WatchlistItem
from stocksim.models.save import CHALLENGE_MODES, SAVE_MODE_CHALLENGE_MARKET, SAVE_MODE_REPLAY
from stocksim.services import event_hooks
from stocksim.services.equity import (
    holding_quantities,
    record_close_snapshot,
    record_entries_close,
)
from stocksim.services.stocks import get_stock_info, industry_ranges, stock_pool

logger = logging.getLogger(__name__)
META_KEY = "_meta"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_ATTEMPTS = 3
ROLLING_WINDOW = 4  # 滚动均量需要的前 4 个交易日（连同当日共 5 根，见 domain._rollover）
OPENING_HISTORY = 59  # 开局写入 candles 的已结束历史日数（domain 生成 60 根，最后一根为当日）

# ---------- 编解码 ----------


def encode_payload(
    state: Mapping[str, Any], as_of: date, clock_rules: int = CLOCK_RULES_V1
) -> dict[str, Any]:
    """v1 的 _meta 保持 {trading_tick, as_of}；v2 额外写入 rules=2（自描述，decode 时校验）。"""
    breaker = state["breaker"]
    meta: dict[str, Any] = {
        "trading_tick": int(state["trading_tick"]),
        "as_of": as_of.isoformat(),
    }
    if clock_rules == CLOCK_RULES_V2:
        meta["rules"] = CLOCK_RULES_V2
    payload: dict[str, Any] = {META_KEY: meta}
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
    payload: Mapping[str, Any],
    prior: Mapping[str, list[dict[str, Any]]] | None,
    clock_rules: int = CLOCK_RULES_V1,
) -> dict[str, Any]:
    """payload -> domain 行情状态。history 仅含当日（及可选的前序窗口），足以驱动 advance。

    payload 的规则版本必须与存档一致（数据损坏时抛 RuntimeError）。
    """
    meta = payload[META_KEY]
    stored_rules = int(meta.get("rules", CLOCK_RULES_V1))
    if stored_rules != clock_rules:
        raise RuntimeError(f"market payload rules={stored_rules} != save clock_rules={clock_rules}")
    as_of = date.fromisoformat(meta["as_of"])
    trading_tick = int(meta["trading_tick"])
    day = timebase(clock_rules).day_of(trading_tick)
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
    row = db.get(MarketState, market_key(save))
    if row is None:  # 不应发生：创建存档时一并写入
        raise RuntimeError(f"market_states missing for save {save.id}")
    return row


def load_market(db: Session, save: Save) -> tuple[dict[str, Any], date]:
    """读取当前行情状态（不推进）。返回 (state, as_of)。复盘存档由关卡包给出（05 §5.3）。"""
    if save.mode == SAVE_MODE_REPLAY:
        return _replay_service().load_state(db, save)
    row = _market_row(db, save)
    as_of, _ = _meta(row.payload)
    return decode_state(row.payload, None, save.clock_rules), as_of


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


def _batch_rolls(minute: int, trading_tick: int, n: int, tb: TimeBase) -> bool:
    """模拟 n 个分钟，判断其中是否会发生交易日切换（决定是否需要读取滚动窗口）。"""
    m, t = minute, trading_tick
    for _ in range(n):
        m = advance_minute(m)
        if is_trading_time(m):
            t += 1
            if tb.rolls_at(t):
                return True
    return False


def market_key(save: Save) -> uuid.UUID:
    """行情来源键（01 §1.7、03 §1.5）：读取 market_states / candles 时一律经它。
    普通存档与 master 恒为自身 id；挑战玩家存档返回 market_source_id（master 的 id）。"""
    return save.market_source_id or save.id


def reject_challenge(save: Save, feature: str) -> None:
    """挑战存档（玩家与 master）不支持的操作：CHALLENGE_UNSUPPORTED {feature}（03 §10.3）。"""
    if save.mode in CHALLENGE_MODES:
        raise AppError(ErrorCode.CHALLENGE_UNSUPPORTED, {"feature": feature})


def reject_replay(save: Save, feature: str) -> None:
    """复盘存档不支持的操作：REPLAY_UNSUPPORTED {feature}（05 §5.3）。"""
    if save.mode == SAVE_MODE_REPLAY:
        raise AppError(ErrorCode.REPLAY_UNSUPPORTED, {"feature": feature})


def _replay_service() -> Any:
    """延迟导入：services.replay 依赖本模块的部分函数，不能在模块顶层互相导入。"""
    from stocksim.services.replay import state as replay_state

    return replay_state


def current_trading_tick(db: Session, save: Save) -> int:
    """行情来源当前的交易 tick（_meta.trading_tick）。事件可见性以它为准。"""
    row = db.get(MarketState, market_key(save))
    if row is None:  # 不应发生：创建存档时一并写入
        raise RuntimeError(f"market_states missing for market {market_key(save)}")
    return _meta(row.payload)[1]


def _events_service() -> Any:
    """延迟导入：services.events 依赖本模块（market_key 等），不能在模块顶层互相导入。"""
    from stocksim.services import events as events_service

    return events_service


def _run_ticks(db: Session, save: Save, n: int) -> int:
    """推进 n 个游戏分钟并写回 market_states 与存档时钟字段（不提交）。返回实际推进的分钟数。

    每分钟 tick 计数 +1（RNG 维度）。非交易分钟只推进分钟与计数、不调用 advance：
    advance 对非交易分钟的结果就是原样副本，逐分钟调用与跳过的结果逐位相同（07 §5.3）。

    事件模式（save.events_enabled）：交易 tick 的漂移由 events.drift_for 提供；该 tick 有快讯发布时
    调用发布钩子，任一返回 True 则置 paused 并停止本批剩余 tick（01 §1.5）。
    关闭时完全不进入 events。
    """
    rules = save.clock_rules
    tb = timebase(rules)
    row = _market_row(db, save)
    as_of, trading_tick = _meta(row.payload)
    prior = None
    if _batch_rolls(save.clock_minute, trading_tick, n, tb):
        prior = _prior_windows(db, market_key(save), tb.day_of(trading_tick), as_of)
    state = decode_state(row.payload, prior, rules)
    seed = save.market_seed
    minute, tick = save.clock_minute, save.tick
    quantities: dict[str, int] | None = None
    events_on = bool(save.events_enabled)
    events_service = _events_service() if events_on else None
    done = 0
    for _ in range(n):
        minute = advance_minute(minute)
        tick += 1
        done += 1
        if not is_trading_time(minute):
            continue
        tt = int(state["trading_tick"]) + 1
        rolls = tb.rolls_at(tt)
        closing_day = state["trading_day"]
        drift = events_service.drift_for(save, tt) if events_on else None
        state = advance(state, seed, tick, minute, drift=drift, rules=rules)
        if rolls:
            _persist_closed_day(db, market_key(save), closing_day, state)
            if save.mode == SAVE_MODE_CHALLENGE_MARKET:
                # master 不写自身权益快照，改为写全部挑战玩家存档的收盘快照（03 §7.2）
                record_entries_close(db, save, closing_day, state, tick)
            else:
                # 收盘权益快照（资产曲线）；持仓在批次内不变，只在首次跨日时读取
                if quantities is None:
                    quantities = holding_quantities(db, save.id)
                record_close_snapshot(db, save, closing_day, state, quantities, tick)
        if events_on:
            events, news = events_service.news_for_tick(save, tt)
            if news and event_hooks.run_publish_hooks(
                db,
                event_hooks.PublishContext(
                    save=save,
                    trading_tick=tt,
                    tick=tick,
                    clock_minute=minute,
                    news=news,
                    events=events,
                ),
            ):
                save.paused = True
                break
    row.payload = encode_payload(state, as_of, rules)
    save.tick = tick
    save.clock_minute = minute
    save.trading_day = state["trading_day"]
    aligned = tb.offset_of(int(state["trading_tick"])) == v2_expected_offset(minute)
    if rules == CLOCK_RULES_V2 and not aligned:
        # 对齐不变量被破坏（多为直接改写了 clock_minute）：告警不抛错，分时退化为 exact=false
        logger.warning("v2 clock alignment broken: save=%s minute=%s", save.id, minute)
    return done


def _retrying[T](db: Session, save: Save, action: Callable[[], T]) -> T:
    """乐观锁冲突（StaleDataError）或并发写同一交易日收盘数据（IntegrityError）时，
    回滚、刷新存档后重试 action（action 必须从当前库状态重新计算）。"""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return action()
        except (StaleDataError, IntegrityError):
            db.rollback()
            db.refresh(save)
            if attempt == MAX_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def _to_ms(value: datetime) -> int:
    return (value - EPOCH) // timedelta(milliseconds=1)


def _from_ms(ms: int) -> datetime:
    return EPOCH + timedelta(milliseconds=ms)


def _iso(value: datetime | None) -> str | None:
    """UTC ISO 8601，毫秒精度，以 Z 结尾（前端倒计时与 server_time 校正用）。"""
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ClockCtx:
    """存档时钟的节奏参数：v1 按 refresh_rate_ms；v2 按用户节奏档与停留时长（Settings）。"""

    rules: int
    ms_per_minute: int
    lunch_dwell_ms: int
    close_dwell_ms: int


def clock_ctx(db: Session, save: Save) -> ClockCtx:
    user = db.get(User, save.user_id)
    settings = get_settings()
    if save.clock_rules == CLOCK_RULES_V2:
        speed = user.clock_speed if user is not None else DEFAULT_CLOCK_SPEED
        ms = SPEED_MS_PER_MINUTE[speed]
    else:
        ms = user.refresh_rate_ms if user is not None else 3000
    return ClockCtx(
        rules=save.clock_rules,
        ms_per_minute=ms,
        lunch_dwell_ms=settings.CLOCK_LUNCH_DWELL_MS,
        close_dwell_ms=settings.CLOCK_CLOSE_DWELL_MS,
    )


def _advance_v2_to_now(db: Session, save: Save, now: datetime) -> int:
    """v2 自动快进：按锚点 + 停留时长的纯函数计划推进（07 §5.2–5.3）。"""
    ctx = clock_ctx(db, save)
    plan = plan_catchup_v2(
        save.clock_minute,
        _to_ms(save.last_tick_at),
        _to_ms(now),
        ms_per_minute=ctx.ms_per_minute,
        lunch_dwell_ms=ctx.lunch_dwell_ms,
        close_dwell_ms=ctx.close_dwell_ms,
        max_trading_ticks=get_settings().TICK_CATCHUP_MAX,
    )
    if plan.minutes == 0:
        return 0
    done = _run_ticks(db, save, plan.minutes)
    # 完整执行时锚点按计划前进（停留窗口内的锚点即其到期时刻）；被截停时丢弃剩余墙钟时间
    save.last_tick_at = _from_ms(plan.anchor_ms) if done == plan.minutes else now
    db.commit()
    return done


def _advance_to_now_once(db: Session, save: Save) -> int:
    if save.mode == SAVE_MODE_REPLAY:
        return 0  # 复盘回合制：只在 advance 接口推进，不走墙钟（05 §5.3，先于 clock_rules 分支）
    if save.mode in CHALLENGE_MODES:
        # 挑战存档不走墙钟补推与 v2 调度：由公共时间线决定（03 §7.3）。先于 paused 判断分发
        from stocksim.services.challenges import sync as challenge_sync
        from stocksim.services.challenges import timeutil as challenge_timeutil

        return challenge_sync.sync_entry_save(db, save, challenge_timeutil.now())
    now = utcnow()
    if save.paused:
        return 0
    if save.last_tick_at is None:
        save.last_tick_at = now
        db.commit()
        return 0
    if save.clock_rules == CLOCK_RULES_V2:
        return _advance_v2_to_now(db, save, now)
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
    done = _run_ticks(db, save, n)
    # 被发布钩子截停：存档已暂停，剩余墙钟时间直接丢弃（暂停期间不快进）
    save.last_tick_at = new_last if done == n else now
    db.commit()
    return done


def advance_to_now(db: Session, save: Save) -> int:
    """按 wall-clock 补推 tick（每 refresh_rate_ms 一 tick，上限 TICK_CATCHUP_MAX，暂停不推进）。

    返回本次推进的 tick 数。所有存档级读写接口在访问数据前必须先调用。
    """
    try:
        return _retrying(db, save, lambda: _advance_to_now_once(db, save))
    except (StaleDataError, IntegrityError):
        # 另一个请求已推进（并写入了同一交易日的收盘数据），本次无需再推；_retrying 已回滚并刷新存档
        return 0


def _advance_ticks_once(db: Session, save: Save, n: int) -> int:
    if n <= 0:
        return 0
    done = _run_ticks(db, save, n)
    save.last_tick_at = utcnow()
    db.commit()
    return done


def advance_ticks(db: Session, save: Save, n: int) -> int:
    """立即推进 n 个 tick（跳过时间、调试时间等）。不考虑暂停；调用方应先 advance_to_now。

    同时把 last_tick_at 置为当前时刻，避免之后的 wall-clock 补推叠加。返回推进的 tick 数。
    挑战存档（玩家与 master）拒绝：时间只能由公共时间线推进（03 §5 #4）；复盘存档拒绝。
    """
    reject_challenge(save, "clock")
    reject_replay(save, "clock")
    return _retrying(db, save, lambda: _advance_ticks_once(db, save, n))


# ---------- 视图 ----------


def watch_codes(db: Session, save_id: uuid.UUID) -> set[str]:
    return set(db.scalars(select(WatchlistItem.stock_code).where(WatchlistItem.save_id == save_id)))


def _quote(stock: Mapping[str, Any], breaker_active: bool, watched: bool) -> dict[str, Any]:
    price = int(stock["price"])
    prev = int(stock["prev_close"])
    pct = int(stock.get("limit_pct_bp", LIMIT_PCT_BP))  # 复盘按板块涨跌幅；普通存档恒为 10%
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
        "limit_up_cents": limit_up_cents(prev, pct),
        "limit_down_cents": limit_down_cents(prev, pct),
        "circuit_breaker_active": breaker_active,
        "watchlisted": watched,
    }


def clock_view(
    db: Session, save: Save, *, skipped_ticks: int = 0, now: datetime | None = None
) -> dict[str, Any]:
    """存档时钟的对外视图（REST ClockOut 与 WS tick.clock 共用，07 §1.2–1.3）。

    next_event.at / next_tick_at / fast_forward_at 按调度表推演（v2）或按刷新间隔（v1）计算；
    暂停时 at 与 next_tick_at 为 null。now 仅用于 server_time（可注入以便测试）。
    """
    if save.mode == SAVE_MODE_REPLAY:
        return _replay_clock_view(save, skipped_ticks=skipped_ticks, now=now or utcnow())
    challenge = save.mode in CHALLENGE_MODES
    if now is None:
        if challenge:  # 挑战时钟与公共时间线同源（03 §3.2）
            from stocksim.services.challenges import timeutil as challenge_timeutil

            now = challenge_timeutil.now()
        else:
            now = utcnow()
    rules = save.clock_rules
    m = save.clock_minute
    ctx = clock_ctx(db, save)
    kind, target = next_event_of(m, rules)
    at: datetime | None = None
    next_tick_at: datetime | None = None
    fast_forward_at: datetime | None = None
    anchor = save.last_tick_at
    if challenge:
        # 挑战存档不走 v2 墙钟调度：下面的覆盖字段整体由公共时间线给出（03 §3.2）
        pass
    elif anchor is not None and not save.paused:
        a_ms = _to_ms(anchor)
        if rules == CLOCK_RULES_V1:
            delta = (target - m) % MINUTES_PER_DAY
            at = _from_ms(a_ms + delta * ctx.ms_per_minute)
            next_tick_at = _from_ms(a_ms + ctx.ms_per_minute)
        else:
            kw = {
                "ms_per_minute": ctx.ms_per_minute,
                "lunch_dwell_ms": ctx.lunch_dwell_ms,
                "close_dwell_ms": ctx.close_dwell_ms,
            }
            at_ms = ms_until_minute_v2(m, a_ms, target, **kw)
            at = _from_ms(at_ms) if at_ms is not None else None
            step = next_step_v2(m, a_ms, **kw)
            if step.kind == "tick":
                next_tick_at = _from_ms(step.due_ms)
            if m in (V2_LUNCH_MINUTE, V2_CLOSE_MINUTE):
                fast_forward_at = _from_ms(step.due_ms)
    if challenge:
        from stocksim.services.challenges import views as challenge_views

        over = challenge_views.clock_overrides(db, save, now)
        at = over["next_event_at"]
        next_tick_at = over["next_tick_at"]
        fast_forward_at = over["fast_forward_at"]
        ms_per_minute = over["ms_per_minute"]
    else:
        ms_per_minute = ctx.ms_per_minute
    return {
        "paused": save.paused,
        "tick": save.tick,
        "trading_day": save.trading_day,
        "clock_minute": m,
        "session": session_label_v2(m) if rules == CLOCK_RULES_V2 else session_label(m),
        "skipped_ticks": skipped_ticks,
        "clock_rules": "v2" if rules == CLOCK_RULES_V2 else "v1",
        "phase": phase_of(m, rules),
        "trading": is_order_time(m, rules),
        "next_event": {"kind": kind, "minute": target, "at": _iso(at)},
        "ms_per_minute": ms_per_minute,
        "next_tick_at": _iso(next_tick_at),
        "fast_forward_at": _iso(fast_forward_at),
        "server_time": _iso(now),
    }


def _replay_clock_view(save: Save, *, skipped_ticks: int, now: datetime) -> dict[str, Any]:
    """复盘存档的 ClockOut（05 §5.3）：paused 恒为 true，时间类字段为 null，阶段按 v1 推出。"""
    m = save.clock_minute
    kind, target = next_event_of(m, CLOCK_RULES_V1)
    return {
        "paused": True,
        "tick": save.tick,
        "trading_day": save.trading_day,
        "clock_minute": m,
        "session": session_label(m),
        "skipped_ticks": skipped_ticks,
        "clock_rules": "v1",
        "phase": phase_of(m, CLOCK_RULES_V1),
        "trading": is_order_time(m, CLOCK_RULES_V1),
        "next_event": {"kind": kind, "minute": target, "at": None},
        "ms_per_minute": None,
        "next_tick_at": None,
        "fast_forward_at": None,
        "server_time": _iso(now),
    }


def trade_guard(
    state: Mapping[str, Any], code: str, side: str
) -> tuple[ErrorCode, dict[str, Any]] | None:
    """下单前的守卫（05 §5.4 第 5 点）：复盘的已结算、停牌、封板。普通存档恒为 None。

    非交易阶段不在这里拦截，交给撮合返回 MARKET_CLOSED。
    """
    meta = state.get("_replay")
    if meta is None:
        return None
    if meta["settled"]:
        return ErrorCode.REPLAY_SESSION_SETTLED, {"save_id": meta["save_id"]}
    if meta["phase"] not in ("open", "close"):
        return None
    stock = find_stock(state, code)
    if stock is None:
        return None
    flags = stock["replay_flags"]
    if flags["suspended"]:
        return ErrorCode.REPLAY_STOCK_SUSPENDED, {"code": code}
    if side == "buy" and flags["locked_up"]:
        return ErrorCode.REPLAY_LIMIT_LOCKED, {"code": code, "side": "buy"}
    if side == "sell" and flags["locked_down"]:
        return ErrorCode.REPLAY_LIMIT_LOCKED, {"code": code, "side": "sell"}
    return None


# 列表排序键：取值函数（对 domain 行情状态里的个股 dict）
_SORT_VALUES: dict[str, Callable[[Mapping[str, Any]], int]] = {
    "code": lambda s: int(s["code"]),  # 股票代码均为 6 位数字
    "price": lambda s: int(s["price"]),
    "volume": lambda s: int(s["daily_volume"]),
    "change": lambda s: _change_bp(s),
}
DEFAULT_ORDER = {"code": "asc", "price": "desc", "volume": "desc", "change": "desc"}


def _change_bp(stock: Mapping[str, Any]) -> int:
    prev = int(stock["prev_close"])
    if prev <= 0:
        return 0
    return round_half_up_div((int(stock["price"]) - prev) * BP_DENOMINATOR, prev)


def _sort_key(sort: str, order: str, stock: Mapping[str, Any]) -> tuple[int, str]:
    """排序键：主键按 order 升/降，并列恒按代码升序，保证全序（游标可定位）。"""
    value = _SORT_VALUES[sort](stock)
    return (value if order == "asc" else -value, str(stock["code"]))


def _encode_cursor(sort: str, order: str, stock: Mapping[str, Any]) -> str:
    raw = json.dumps([sort, order, _SORT_VALUES[sort](stock), stock["code"]], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, sort: str, order: str) -> tuple[int, str]:
    """返回游标的排序键；格式非法或与当前 sort/order 不一致 → VALIDATION_ERROR(field=cursor)。"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        c_sort, c_order, value, code = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if (
            c_sort != sort
            or c_order != order
            or isinstance(value, bool)
            or not isinstance(value, int)
            or not isinstance(code, str)
        ):
            raise ValueError
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc
    return (value if order == "asc" else -value, code)


def market_overview(
    db: Session,
    save: Save,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    watchlisted: bool | None = None,
) -> dict[str, Any]:
    """全市场快照。不带任何查询参数时返回全部股票（顺序为股票池顺序，向后兼容）。

    过滤：q 为代码/名称子串（不区分大小写），watchlisted 为 True/False 时按自选过滤。
    排序：显式给出 sort/order 时按 (主键, 代码) 全序；分页用键集游标（见 CONTRACT）。
    total 为过滤后的总数，next_cursor 为 None 表示已到末页。
    """
    state, _ = load_market(db, save)
    watched = watch_codes(db, save.id)
    stocks = state["stocks"]
    needle = (q or "").strip().casefold()
    if needle:
        stocks = [s for s in stocks if needle in s["code"] or needle in s["name"].casefold()]
    if watchlisted is not None:
        stocks = [s for s in stocks if (s["code"] in watched) == watchlisted]
    total = len(stocks)

    next_cursor: str | None = None
    if any(v is not None for v in (limit, cursor, sort, order)):
        sort = sort or "code"
        eff_order = order or DEFAULT_ORDER[sort]
        stocks = sorted(stocks, key=lambda s: _sort_key(sort, eff_order, s))
        if cursor is not None:
            after = _decode_cursor(cursor, sort, eff_order)
            stocks = [s for s in stocks if _sort_key(sort, eff_order, s) > after]
        if limit is not None and len(stocks) > limit:
            stocks = stocks[:limit]
            next_cursor = _encode_cursor(sort, eff_order, stocks[-1])
    return {
        **clock_view(db, save),
        "total": total,
        "next_cursor": next_cursor,
        "stocks": [_quote(s, s["code"] in state["breaker"], s["code"] in watched) for s in stocks],
    }


# ---------- 个股当日分时 ----------


def _day_ticks(save: Save, count: int) -> list[tuple[int, int]]:
    """从存档当前时钟倒推最近 count 个交易 tick 的 (global_tick, minute)，按时间升序。

    每个 tick 恰好前进 1 分钟；只有落在交易时段的分钟才是交易 tick（见 _run_ticks）。
    """
    out: list[tuple[int, int]] = []
    minute, tick = save.clock_minute, save.tick
    while len(out) < count and tick > 0:
        if is_trading_time(minute):
            out.append((tick, minute))
        minute = (minute - 1) % 1440
        tick -= 1
    out.reverse()
    return out


def intraday(db: Session, save: Save, code: str) -> dict[str, Any] | None:
    """个股当日分时：由确定性引擎从当日开盘价重放，无需额外存储。复盘存档见 replay.views。

    当日已处理的交易 tick 数 = trading_tick - N*day（第 1 日起首个 tick 即换日 tick，+1）。
    N 为 timebase(clock_rules).ticks_per_day（v1=20，v2=242）。
    重放用 domain.advance（单只股票状态，RNG 维度仍用其 stock_idx 与全局 tick），
    并校验终点价格/成交量与持久化状态一致；不一致（调试改过时钟等）时退化为仅含当前点。
    """
    if save.mode == SAVE_MODE_REPLAY:
        from stocksim.services.replay import views as replay_views

        return replay_views.intraday(db, save, code)
    row = _market_row(db, save)
    as_of, trading_tick = _meta(row.payload)
    info = get_stock_info(code)
    if info is None:
        return None
    tb = timebase(save.clock_rules)
    per_day = tb.ticks_per_day
    day = tb.day_of(trading_tick)
    events_service = _events_service() if save.events_enabled else None
    raw = [int(v) for v in row.payload[code]]
    price, prev_close, open_, _high, _low, daily, prev_daily, _avg, _cd = raw
    processed = trading_tick - per_day * day + (1 if day >= 1 else 0)
    ticks = _day_ticks(save, processed)

    points: list[dict[str, int]] = []
    ok = len(ticks) == processed
    if ok and ticks:
        stock = {
            "code": info.code,
            "name": info.name,
            "industry": info.industry,
            "profile": info.profile,
            "stock_idx": info.idx,
            "price": open_,
            "prev_close": open_,
            "open": open_,
            "high": open_,
            "low": open_,
            # 换日 tick 会把 daily_volume 滚入 prev_daily_volume；第 0 日则直接取持久化值
            "volume": prev_daily if day >= 1 else 0,
            "daily_volume": prev_daily if day >= 1 else 0,
            "prev_daily_volume": prev_daily,
            "avg_volume": 0,
            "history": [
                {
                    "date": "2000-01-01",
                    "open": open_,
                    "high": open_,
                    "low": open_,
                    "close": open_,
                    "volume": prev_daily,
                }
            ],
        }
        sim = {
            "trading_tick": per_day * day - (1 if day >= 1 else 0),
            "trading_day": day,
            "breaker": {},
            "stocks": [stock],
        }
        for tick, minute in ticks:
            # 事件开启时逐 tick 取同一份漂移（只取本股票的项，与 _run_ticks 完全一致）
            drift = None
            if events_service is not None:
                drift = events_service.drift_for(save, int(sim["trading_tick"]) + 1)
            sim = advance(
                sim, save.market_seed, tick, minute, drift=drift, rules=save.clock_rules
            )
            cur = sim["stocks"][0]
            points.append(
                {
                    "minute": minute,
                    "tick": tick,
                    "price_cents": int(cur["price"]),
                    "volume": int(cur["daily_volume"]),
                }
            )
        ok = points[-1]["price_cents"] == price and points[-1]["volume"] == daily
    if not ok:
        last = ticks[-1][0] if ticks else save.tick
        points = (
            [{"minute": save.clock_minute, "tick": last, "price_cents": price, "volume": daily}]
            if processed > 0
            else []
        )
    return {
        "code": code,
        "trading_day": day,
        "date": _day_iso(as_of, day),
        "clock_minute": save.clock_minute,
        "tick": save.tick,
        "prev_close_cents": prev_close,
        "open_cents": open_,
        "points": points,
        "exact": ok,
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
    if save.mode == SAVE_MODE_REPLAY:
        from stocksim.services.replay import views as replay_views

        return replay_views.stock_market(db, save, code)
    state, as_of = load_market(db, save)
    stock = find_stock(state, code)
    if stock is None:
        return None
    rows = db.scalars(
        select(Candle)
        .where(Candle.save_id == market_key(save), Candle.stock_code == code)
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
    reject_challenge(save, "clock")
    reject_replay(save, "clock")

    def act() -> dict[str, Any]:
        save.paused = True
        db.commit()
        return clock_view(db, save)

    return _retrying(db, save, act)


def resume_clock(db: Session, save: Save) -> dict[str, Any]:
    reject_challenge(save, "clock")
    reject_replay(save, "clock")

    def act() -> dict[str, Any]:
        save.paused = False
        save.last_tick_at = utcnow()  # 暂停期间不补推；v2 停留窗口也从此刻重新计时
        db.commit()
        return clock_view(db, save)

    return _retrying(db, save, act)


def skip_clock(db: Session, save: Save) -> dict[str, Any]:
    reject_challenge(save, "clock")
    reject_replay(save, "clock")
    if save.clock_rules == CLOCK_RULES_V2:
        # v2 每次至少推进 1 分钟，跳到下一个关键时点（停留点、开盘、收盘）
        n = skip_ticks(save.clock_minute, skip_target_v2(save.clock_minute))
        done = advance_ticks(db, save, n)
        return clock_view(db, save, skipped_ticks=done)
    target = skip_target_minutes(save.clock_minute)
    if target is None:
        return clock_view(db, save, skipped_ticks=0)
    n = skip_ticks(save.clock_minute, target)
    done = advance_ticks(db, save, n)
    return clock_view(db, save, skipped_ticks=done)


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
    db.add(
        MarketState(
            save_id=save.id,
            payload=encode_payload(state, as_of, save.clock_rules),
            updated_at=utcnow(),
        )
    )
    db.execute(Candle.__table__.insert(), rows)


__all__ = [
    "advance_ticks",
    "advance_to_now",
    "clock_view",
    "current_trading_tick",
    "decode_state",
    "encode_payload",
    "init_market_for_save",
    "intraday",
    "load_market",
    "market_key",
    "market_overview",
    "pause_clock",
    "reject_replay",
    "resume_clock",
    "skip_clock",
    "stock_market",
    "trade_guard",
    "watch_codes",
]
