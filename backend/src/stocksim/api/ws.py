"""行情 WebSocket 的推送循环：/api/v1/ws/saves/{id}（路由见 api/routers/ws.py）。

每个连接按用户的 refresh_rate_ms 周期执行一次 `tick_once`（线程池 + 每次新建 Session）：
1. market.advance_to_now 推进行情；2. auto_trade.run_auto_trade 评估自动交易；
3. 与上一轮快照做差，产生 tick / trade / achievement / auto_event 消息。

服务端消息：{"t":"tick",...} {"t":"trade",...} {"t":"achievement","ids"} {"t":"auto_event",...}
          {"t":"subscribed"|"unsubscribed","code"} {"t":"pong"} {"t":"error","code"}
客户端消息：{"t":"subscribe","code":"600519"} {"t":"unsubscribe","code"} {"t":"ping"}
关闭码：4401 未登录，4404 存档不存在或不属于当前用户。
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket, WebSocketDisconnect

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import is_trading_time
from stocksim.domain.money import round_half_up_div
from stocksim.models import AutoTradeEvent, MarketState, Save, SaveAchievement, Trade, User
from stocksim.services import auto_trade as auto_service
from stocksim.services import market as market_service
from stocksim.services.auth import resolve_session
from stocksim.services.saves import load_owned_save

CLOSE_AUTH_REQUIRED = 4401
CLOSE_NOT_FOUND = 4404
MIN_REFRESH_MS = 200
MAX_REFRESH_MS = 60_000
MAX_SUBSCRIPTIONS = 20
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


def snapshot(db: Session, save: Save) -> StreamState:
    """连接建立时的基线：已有的成就/成交/自动事件不再推送。"""
    return StreamState(
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
        refresh = min(max(user.refresh_rate_ms, MIN_REFRESH_MS), MAX_REFRESH_MS)
        return None, refresh, snapshot(db, save)


def _quote_messages(
    db: Session, save: Save, state: StreamState, advanced: int
) -> list[dict[str, Any]]:
    market = db.get(MarketState, save.id)
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
    return [
        {
            "t": "tick",
            "tick": save.tick,
            "advanced": advanced,
            "clock": {
                "minute": save.clock_minute,
                "trading_day": save.trading_day,
                "paused": save.paused,
                "trading": is_trading_time(save.clock_minute),
            },
            "full": not state.sent_full,
            "q": rows,
        }
    ]


def tick_once(
    session_factory: sessionmaker[Session], save_id: uuid.UUID, state: StreamState
) -> list[dict[str, Any]]:
    """同步执行一轮推进与评估，返回需要发送的消息。存档消失时返回 SAVE_NOT_FOUND 错误消息。"""
    with session_factory() as db:
        save = db.get(Save, save_id)
        if save is None:
            return [{"t": "error", "code": ErrorCode.SAVE_NOT_FOUND.value}]
        advanced = market_service.advance_to_now(db, save)
        db.refresh(save)
        auto_trades = auto_service.run_auto_trade(db, save)

        # 每个刷新周期都发一帧 tick（即使本轮未推进），q 只含相对上一帧变化的股票；首帧全量
        messages: list[dict[str, Any]] = _quote_messages(db, save, state, advanced)
        state.sent_full = True

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
        return messages


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
    error, refresh_ms, state = await run_in_threadpool(
        authorize, session_factory, settings, token, save_id
    )
    if error is not None or state is None:
        code = error or ErrorCode.SAVE_NOT_FOUND.value
        await websocket.send_json({"t": "error", "code": code})
        close_code = (
            CLOSE_AUTH_REQUIRED if code == ErrorCode.AUTH_REQUIRED.value else CLOSE_NOT_FOUND
        )
        await websocket.close(code=close_code)
        return

    interval = refresh_ms / 1000
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
                messages = await run_in_threadpool(tick_once, session_factory, save_id, state)
            except AppError as exc:
                messages = [{"t": "error", "code": exc.code.value}]
            except Exception:  # 单轮失败不断开连接，记录后继续下一轮
                logger.exception("ws tick failed for save %s", save_id)
                messages = [{"t": "error", "code": "INTERNAL_ERROR"}]
            for out in messages:
                await websocket.send_json(out)
            if any(m.get("code") == ErrorCode.SAVE_NOT_FOUND.value for m in messages):
                await websocket.close(code=CLOSE_NOT_FOUND)
                return
            next_at = loop.time() + interval
    finally:
        reader.cancel()
