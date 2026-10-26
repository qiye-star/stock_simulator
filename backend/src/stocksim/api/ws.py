"""行情 WebSocket 的推送循环：/api/v1/ws/saves/{id}（路由见 api/routers/ws.py）。

每个连接按用户的 refresh_rate_ms 周期执行一次 `tick_once`（线程池 + 每次新建 Session）：
1. market.advance_to_now 推进行情；2. auto_trade.run_auto_trade 评估自动交易；
3. 与上一轮快照做差，产生 tick / trade / achievement / auto_event 消息。

服务端消息：{"t":"tick",...} {"t":"phase","from","to",...} {"t":"news",...}（仅事件存档，01 §8.2）
          {"t":"challenge","challenge_id","status","phase","round_index","next_change_at",
           "public_trading_tick","resolved_qids"}（挑战存档，03 §10.4：首帧及相位等变化时）
          {"t":"prediction","op","card_id","event_id","status","points","balance"}（预测卡）
          {"t":"title","ids"}（称号新解锁）
          {"t":"trade",...} {"t":"achievement","ids"} {"t":"auto_event",...}
          {"t":"subscribed"|"unsubscribed","code"} {"t":"pong"} {"t":"error","code"}
消息顺序：tick → phase → news → challenge → prediction → title → trade → achievement → auto_event。
推送节奏：v1 存档每 refresh_rate_ms 一轮；v2 存档醒在下一个到期点（下一分钟或停留结束），
暂停时每 2 秒一轮。挑战存档不走 v2 调度：快放段（burst/final）每 tick_ms（夹在 [200, 60000]）一轮，
其余（赛前、停顿、结束）每 CHALLENGE_HOLD_POLL_MS 一轮；每轮先经 market.advance_to_now 分发到
challenges.sync.sync_entry_save（推进 master 并镜像，master 不可经 WS 访问）。挑战 tick 帧的 clock
由 market.clock_view 按挑战规则覆盖（views.clock_overrides，03 §3.2）。
tick 帧的 clock 与 REST ClockOut 同源（services/market.clock_view），帧内的 clock_minute 叫 minute。
客户端消息：{"t":"subscribe","code":"600519"} {"t":"unsubscribe","code"} {"t":"ping"}
关闭码：4401 未登录，4404 存档不存在或不属于当前用户。
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket, WebSocketDisconnect

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.clock import V2_WS_PAUSED_POLL_MS, phase_of
from stocksim.domain.money import round_half_up_div
from stocksim.models import (
    AutoTradeEvent,
    MarketState,
    PredictionCard,
    Save,
    SaveAchievement,
    Trade,
    User,
    UserTitle,
)
from stocksim.models.save import CHALLENGE_MODES, SAVE_MODE_REPLAY
from stocksim.services import auto_trade as auto_service
from stocksim.services import events as events_service
from stocksim.services import market as market_service
from stocksim.services import points as points_service
from stocksim.services import predictions as pred_service
from stocksim.services.auth import resolve_session
from stocksim.services.challenges import registry as challenge_registry
from stocksim.services.challenges import timeutil as challenge_timeutil
from stocksim.services.challenges import views as challenge_views
from stocksim.services.challenges.sync import RUNNING_PHASES as CHALLENGE_RUNNING_PHASES
from stocksim.services.saves import load_owned_save

CLOSE_AUTH_REQUIRED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_REPLAY_UNSUPPORTED = 4409  # 复盘存档不建实时连接（05 §5.3）
MIN_REFRESH_MS = 200
MAX_REFRESH_MS = 60_000
MAX_SUBSCRIPTIONS = 20
WS_NEWS_PER_FRAME = events_service.WS_NEWS_PER_FRAME  # 每帧 news 最多条数，超出置 truncated
_CODE_RE = re.compile(r"^\d{6}$")
_TICK = object()  # 内部哨兵：到达推送时刻
logger = logging.getLogger(__name__)


@dataclass
class StreamState:
    """连接级快照：用于计算相对上一轮的增量。"""

    sent_full: bool = False
    quotes: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    subscribed: set[str] = field(default_factory=set)
    achievements: set[str] = field(default_factory=set)
    trade_seq: int = 0
    auto_events: int = 0
    refresh_ms: int = 3000  # v1 推送间隔（用户 refresh_rate_ms，夹在 [MIN, MAX] 内）
    phase: str | None = None  # 上一帧的时段相位（变化时发送 phase 消息）
    events_enabled: bool = False  # 事件存档才推送 news
    news_tt: int = 0  # 已推送到的交易 tick（(news_tt, 当前] 内发布的快讯随本轮推送）
    lang: str = "zh-CN"  # 快讯标题语言（users.lang）
    pred: dict[str, str] = field(default_factory=dict)  # 未终结预测卡 {card_id: status}
    titles: set[str] = field(default_factory=set)  # 已推送过的称号（连接时已解锁的不再推）
    is_challenge: bool = False  # 挑战存档（玩家）：不推 news/prediction/title，推 challenge
    challenge_key: tuple[Any, ...] | None = None  # 上一条 challenge 的判定键
    challenge_hold_ms: int = 5000  # 挑战赛前/停顿/结束的轮询间隔（CHALLENGE_HOLD_POLL_MS）


WS_CLOCK_EXTRA = (
    "clock_rules",
    "phase",
    "next_event",
    "ms_per_minute",
    "next_tick_at",
    "fast_forward_at",
    "server_time",
)


def snapshot(db: Session, save: Save) -> StreamState:
    """连接建立时的基线：已有的成就/成交/自动事件/称号不再推送；未终结的预测卡在首轮推 opened。

    挑战存档（03 §10.4）不走事件通道：events_enabled 视为 False，不推 news/prediction/title。
    """
    is_challenge = save.mode in CHALLENGE_MODES
    events = bool(save.events_enabled) and not is_challenge
    titles: set[str] = set()
    if events:
        titles = set(
            db.scalars(select(UserTitle.title_id).where(UserTitle.user_id == save.user_id))
        )
    return StreamState(
        is_challenge=is_challenge,
        events_enabled=events,
        news_tt=market_service.current_trading_tick(db, save),
        titles=titles,
        achievements=set(
            db.scalars(
                select(SaveAchievement.achievement_id).where(SaveAchievement.save_id == save.id)
            )
        ),
        trade_seq=db.scalar(
            select(func.coalesce(func.max(Trade.seq), 0)).where(Trade.save_id == save.id)
        )
        or 0,
        auto_events=_count_auto_events(db, save),
    )


def _count_auto_events(db: Session, save: Save) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(AutoTradeEvent)
            .where(AutoTradeEvent.save_id == save.id)
        )
        or 0
    )


def authorize(
    session_factory: sessionmaker[Session],
    settings: Settings,
    token: str | None,
    save_id: uuid.UUID,
) -> tuple[str | None, int, StreamState | None]:
    """返回 (错误码或 None, refresh_ms, 基线)。"""
    with session_factory() as db:
        user: User | None = resolve_session(db, settings, token)
        if user is None:
            return ErrorCode.AUTH_REQUIRED.value, 0, None
        try:
            save = load_owned_save(db, user, save_id)
        except AppError:
            return ErrorCode.SAVE_NOT_FOUND.value, 0, None
        if save.mode == SAVE_MODE_REPLAY:
            return ErrorCode.REPLAY_UNSUPPORTED.value, 0, None
        refresh = min(max(user.refresh_rate_ms, MIN_REFRESH_MS), MAX_REFRESH_MS)
        state = snapshot(db, save)
        state.refresh_ms = refresh
        state.lang = user.lang
        state.challenge_hold_ms = settings.CHALLENGE_HOLD_POLL_MS
        return None, refresh, state


def _quote_messages(
    db: Session, save: Save, state: StreamState, advanced: int, view: dict[str, Any]
) -> list[dict[str, Any]]:
    market = db.get(MarketState, market_service.market_key(save))
    payload = (market.payload if market else None) or {}
    rows: list[list[Any]] = []
    for code, raw in payload.items():
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        price, prev_close, volume = int(raw[0]), int(raw[1]), int(raw[5])
        change_bp = (
            round_half_up_div((price - prev_close) * 10_000, prev_close) if prev_close else 0
        )
        current = (price, change_bp, volume)
        forced = code in state.subscribed
        if not state.sent_full or forced or state.quotes.get(code) != current:
            state.quotes[code] = current
            rows.append([code, price, change_bp, volume])
    clock = {
        "minute": view["clock_minute"],
        "trading_day": view["trading_day"],
        "paused": view["paused"],
        "trading": view["trading"],
        **{key: view[key] for key in WS_CLOCK_EXTRA},
    }
    return [
        {
            "t": "tick",
            "tick": save.tick,
            "advanced": advanced,
            "clock": clock,
            "full": not state.sent_full,
            "q": rows,
        }
    ]


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def next_delay_ms(view: dict[str, Any], refresh_ms: int, now: datetime) -> int:
    """下一轮推送的延迟（07 §5.5）。v1 固定 refresh_ms；v2 醒在下一个到期点（+50 ms），
    夹在 [MIN_REFRESH_MS, ms_per_minute] 内。"""
    if view["clock_rules"] != "v2":
        return refresh_ms
    due = [_parse_utc(v) for v in (view["next_tick_at"], view["fast_forward_at"]) if v]
    if view["paused"] or not due:
        return V2_WS_PAUSED_POLL_MS
    delay = int((min(due) - now).total_seconds() * 1000) + 50
    return max(MIN_REFRESH_MS, min(delay, int(view["ms_per_minute"])))


def _news_messages(db: Session, save: Save, state: StreamState) -> list[dict[str, Any]]:
    """发布 tick 在 (news_tt, 当前] 内的快讯（升序）。超过上限只保留最新的，并置 truncated。"""
    if not state.events_enabled:
        return []
    cur = market_service.current_trading_tick(db, save)
    if cur <= state.news_tt:  # 调试改时间回退等：静默对齐基线
        state.news_tt = cur
        return []
    items = events_service.ws_news(db, save, state.news_tt, cur, state.lang)
    state.news_tt = cur
    if not items:
        return []
    truncated = len(items) > WS_NEWS_PER_FRAME
    if truncated:
        items = items[-WS_NEWS_PER_FRAME:]
    return [{"t": "news", "trading_tick": cur, "items": items, "truncated": truncated}]


_PRED_OPS = {
    "open": "opened",
    "answered": "answered",
    "expired": "expired",
    "settled": "settled",
    "void": "void",
}


def _prediction_messages(db: Session, save: Save, state: StreamState) -> list[dict[str, Any]]:
    """预测卡状态变化：与 state.pred 做差（未终结的卡与已知卡参与比较）。"""
    if not state.events_enabled:
        return []
    known = [uuid.UUID(k) for k in state.pred]
    rows = db.execute(
        select(
            PredictionCard.id,
            PredictionCard.event_id,
            PredictionCard.status,
            PredictionCard.points,
            PredictionCard.settled_at,
        )
        .where(
            PredictionCard.save_id == save.id,
            or_(
                (PredictionCard.status.in_(("open", "answered", "expired")))
                & (PredictionCard.settled_at.is_(None)),
                PredictionCard.id.in_(known) if known else False,
            ),
        )
        .order_by(PredictionCard.event_id)
    ).all()
    messages: list[dict[str, Any]] = []
    for cid, event_id, status, pts, settled_at in rows:
        key = str(cid)
        prev = state.pred.get(key)
        finished_expiry = status == "expired" and settled_at is not None
        if status in ("settled", "void") or finished_expiry:
            if prev is not None and prev != status:
                op = _PRED_OPS[status] if not finished_expiry else "settled"
                msg = {
                    "t": "prediction",
                    "op": op,
                    "card_id": key,
                    "event_id": event_id,
                    "status": status,
                    "points": pts if op == "settled" else None,
                    "balance": None,
                }
                if op == "settled":
                    msg["balance"] = points_service.balance(db, user_id=save.user_id)
                messages.append(msg)
            state.pred.pop(key, None)
            continue
        if prev != status:
            state.pred[key] = status
            messages.append(
                {
                    "t": "prediction",
                    "op": _PRED_OPS[status],
                    "card_id": key,
                    "event_id": event_id,
                    "status": status,
                    "points": None,
                    "balance": None,
                }
            )
    return messages


def _title_messages(db: Session, save: Save, state: StreamState) -> list[dict[str, Any]]:
    """用户级称号新解锁（连接后）。"""
    if not state.events_enabled:
        return []
    now = set(db.scalars(select(UserTitle.title_id).where(UserTitle.user_id == save.user_id)))
    fresh = sorted(now - state.titles)
    state.titles = now
    return [{"t": "title", "ids": fresh}] if fresh else []


def _iso_z(value: datetime | None) -> str | None:
    """UTC ISO 8601，毫秒精度，以 Z 结尾（与 REST 时间字段同口径）。"""
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _challenge_messages(
    db: Session, save: Save, state: StreamState, now: datetime
) -> tuple[list[dict[str, Any]], str, int]:
    """挑战存档（03 §10.4）：(challenge 消息, 挑战相位, 挑战 tick_ms)。

    只在 (status, phase, round_index, resolved_qids) 相对上一条发生变化时发送（首帧必发）。
    字段全部是公开形态：相位与回合号来自 views.phase_of，resolved_qids 为已判定题目数。
    """
    ch = challenge_registry.challenge_of_save(db, save)
    phase, round_index, next_at = challenge_views.phase_of(db, ch, now)
    resolved = sum(len(r.outcomes or {}) for r in challenge_registry.rounds_of(db, ch))
    key = (ch.status, phase, round_index, resolved)
    if key == state.challenge_key:
        return [], phase, ch.tick_ms
    state.challenge_key = key
    msg = {
        "t": "challenge",
        "challenge_id": str(ch.id),
        "status": ch.status,
        "phase": phase,
        "round_index": round_index,
        "next_change_at": _iso_z(next_at),
        "public_trading_tick": int(save.tick),
        "resolved_qids": resolved,
    }
    return [msg], phase, ch.tick_ms


def challenge_delay_ms(phase: str, tick_ms: int, hold_ms: int) -> int:
    """挑战存档的推送间隔（03 §10.4）：快放段（burst/final）为 tick_ms，其余为轮询间隔。

    不走 v2 调度（next_delay_ms）。夹在 [MIN_REFRESH_MS, MAX_REFRESH_MS] 内。
    """
    base = tick_ms if phase in CHALLENGE_RUNNING_PHASES else hold_ms
    return min(max(base, MIN_REFRESH_MS), MAX_REFRESH_MS)


def tick_once(
    session_factory: sessionmaker[Session], save_id: uuid.UUID, state: StreamState
) -> tuple[list[dict[str, Any]], int]:
    """同步执行一轮推进与评估，返回 (需要发送的消息, 下一轮延迟毫秒)。

    存档消失时返回 SAVE_NOT_FOUND 错误消息。消息顺序：tick → phase → trade → achievement →
    auto_event。
    """
    with session_factory() as db:
        save = db.get(Save, save_id)
        if save is None:
            return [{"t": "error", "code": ErrorCode.SAVE_NOT_FOUND.value}], state.refresh_ms
        advanced = market_service.advance_to_now(db, save)
        db.refresh(save)
        auto_trades = auto_service.run_auto_trade(db, save)
        if save.events_enabled and not state.is_challenge:
            pred_service.settle_due(db, save)  # 截止过期与到期结算（自己 commit，幂等）

        # 挑战存档：同一 now 贯穿 clock 视图与 challenge 消息（与 sync_entry_save 的时间源一致）
        cnow = challenge_timeutil.now() if state.is_challenge else None
        # 每个刷新周期都发一帧 tick（即使本轮未推进），q 只含相对上一帧变化的股票；首帧全量
        view = market_service.clock_view(db, save, now=cnow)
        messages: list[dict[str, Any]] = _quote_messages(db, save, state, advanced, view)
        state.sent_full = True

        # 时段相位变化：在 tick 之后发送一次（上一帧 → 当前）；首帧只记录不发送
        phase = phase_of(save.clock_minute, save.clock_rules)
        if state.phase is not None and phase != state.phase:
            messages.append(
                {
                    "t": "phase",
                    "from": state.phase,
                    "to": phase,
                    "trading_day": save.trading_day,
                    "clock_minute": save.clock_minute,
                }
            )
        state.phase = phase

        messages.extend(_news_messages(db, save, state))
        challenge_phase, challenge_tick_ms = "", 0
        if state.is_challenge and cnow is not None:
            ch_msgs, challenge_phase, challenge_tick_ms = _challenge_messages(db, save, state, cnow)
            messages.extend(ch_msgs)
        messages.extend(_prediction_messages(db, save, state))
        messages.extend(_title_messages(db, save, state))

        max_seq, new_trades = db.execute(
            select(func.coalesce(func.max(Trade.seq), 0), func.count()).where(
                Trade.save_id == save.id, Trade.seq > state.trade_seq
            )
        ).one()
        if new_trades:
            messages.append({"t": "trade", "seq": int(max_seq), "count": int(new_trades)})
            state.trade_seq = int(max_seq)

        ids = set(
            db.scalars(
                select(SaveAchievement.achievement_id).where(SaveAchievement.save_id == save.id)
            )
        )
        fresh = sorted(ids - state.achievements)
        if fresh:
            messages.append({"t": "achievement", "ids": fresh})
        state.achievements = ids

        count = _count_auto_events(db, save)
        if count > state.auto_events:
            messages.append(
                {"t": "auto_event", "count": count - state.auto_events, "trades": len(auto_trades)}
            )
        state.auto_events = count  # 清空事件（reset）时计数回落，静默更新基线
        if state.is_challenge:
            delay = challenge_delay_ms(challenge_phase, challenge_tick_ms, state.challenge_hold_ms)
        else:
            delay = next_delay_ms(view, state.refresh_ms, utcnow())
        return messages, delay


async def _read_client(websocket: WebSocket, inbox: asyncio.Queue[Any]) -> None:
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            inbox.put_nowait(data if isinstance(data, dict) else {"t": "_invalid"})
    except WebSocketDisconnect:
        pass
    finally:
        inbox.put_nowait(None)


async def _handle_client(websocket: WebSocket, state: StreamState, msg: dict[str, Any]) -> None:
    kind = msg.get("t")
    if kind == "ping":
        await websocket.send_json({"t": "pong"})
    elif kind in ("subscribe", "unsubscribe"):
        code = msg.get("code")
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
            await websocket.send_json({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
            return
        if kind == "subscribe":
            if len(state.subscribed) >= MAX_SUBSCRIPTIONS and code not in state.subscribed:
                await websocket.send_json({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
                return
            state.subscribed.add(code)
        else:
            state.subscribed.discard(code)
        await websocket.send_json(
            {"t": "subscribed" if kind == "subscribe" else "unsubscribed", "code": code}
        )
    else:
        await websocket.send_json({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})


async def stream_save(
    websocket: WebSocket,
    session_factory: sessionmaker[Session],
    settings: Settings,
    save_id: uuid.UUID,
    token: str | None,
) -> None:
    """连接主循环。调用方已 accept。"""
    error, _refresh_ms, state = await run_in_threadpool(
        authorize, session_factory, settings, token, save_id
    )
    if error is not None or state is None:
        code = error or ErrorCode.SAVE_NOT_FOUND.value
        await websocket.send_json({"t": "error", "code": code})
        close_code = {
            ErrorCode.AUTH_REQUIRED.value: CLOSE_AUTH_REQUIRED,
            ErrorCode.REPLAY_UNSUPPORTED.value: CLOSE_REPLAY_UNSUPPORTED,
        }.get(code, CLOSE_NOT_FOUND)
        await websocket.close(code=close_code)
        return

    inbox: asyncio.Queue[Any] = asyncio.Queue()
    reader = asyncio.create_task(_read_client(websocket, inbox))
    loop = asyncio.get_running_loop()
    next_at = loop.time()  # 立即推送第一帧（全量）
    try:
        while True:
            try:
                msg = await asyncio.wait_for(inbox.get(), timeout=max(0.0, next_at - loop.time()))
            except TimeoutError:
                msg = _TICK
            if msg is None:
                return  # 客户端已断开
            if msg is not _TICK:
                await _handle_client(websocket, state, msg)
                continue
            try:
                messages, delay_ms = await run_in_threadpool(
                    tick_once, session_factory, save_id, state
                )
            except AppError as exc:
                messages, delay_ms = [{"t": "error", "code": exc.code.value}], state.refresh_ms
            except Exception:  # 单轮失败不断开连接，记录后继续下一轮
                logger.exception("ws tick failed for save %s", save_id)
                messages = [{"t": "error", "code": "INTERNAL_ERROR"}]
                delay_ms = state.refresh_ms
            for out in messages:
                await websocket.send_json(out)
            if any(m.get("code") == ErrorCode.SAVE_NOT_FOUND.value for m in messages):
                await websocket.close(code=CLOSE_NOT_FOUND)
                return
            next_at = loop.time() + delay_ms / 1000
    finally:
        reader.cancel()
