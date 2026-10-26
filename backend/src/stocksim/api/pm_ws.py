"""预测市场全服推送（04 §8）。

进程内 PmHub 每 PM_POLL_MS 轮询数据库差量并扇出；PM_SWEEP_MS 执行 sweeper。

- 全服共享，与存档刷新率无关。推送内容只含公开数据（价格、份额、状态），不含任何人的持仓。
- 多实例：状态全在数据库，每个实例的 Hub 各自轮询；sweeper 的幂等由生命周期服务保证（04 §5.3）。
- 服务端消息：pm_tick（已订阅市场的 seq 或状态变化）、pm_list（已关注挑战的市场集合或状态变化，
  rev 递增）、pm_resolved（结算或作废）、subscribed / unsubscribed / pong / error。
- 客户端消息：watch{challenge_id}、subscribe{market_id}（每连接最多 20 个）、
  unsubscribe{market_id}、ping。
- 鉴权与存档 WS 一致：未登录先 accept 再发 error AUTH_REQUIRED，以 4401 关闭。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from stocksim.core.config import Settings
from stocksim.core.errors import ErrorCode
from stocksim.models import Challenge, PredictionMarket, User
from stocksim.services import pm_lifecycle
from stocksim.services.auth import resolve_session
from stocksim.services.challenges import timeutil

logger = logging.getLogger(__name__)

CLOSE_AUTH_REQUIRED = 4401
MAX_SUBSCRIPTIONS = 20
TERMINAL = ("resolved", "voided")


@dataclass(eq=False)
class PmConn:
    """一个 WS 连接的订阅状态与出站队列（由连接的写循环统一发送）。"""

    user_id: uuid.UUID
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    challenges: set[uuid.UUID] = field(default_factory=set)
    markets: set[uuid.UUID] = field(default_factory=set)


class PmHub:
    """每个进程一个。poll_once / sweep_once 可被直接调用（测试与 debug 用）。"""

    def __init__(self, session_factory: sessionmaker[Session], *, poll_ms: int, sweep_ms: int):
        self._sf = session_factory
        self._poll_s = poll_ms / 1000
        self._sweep_s = sweep_ms / 1000
        self._conns: set[PmConn] = set()
        self._snap: dict[uuid.UUID, tuple[str, int]] = {}
        self._rev: dict[uuid.UUID, int] = {}
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._poll_loop()), loop.create_task(self._sweep_loop())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []

    def connect(self, user_id: uuid.UUID) -> PmConn:
        conn = PmConn(user_id=user_id)
        self._conns.add(conn)
        return conn

    def disconnect(self, conn: PmConn) -> None:
        self._conns.discard(conn)

    def watched_challenges(self) -> set[uuid.UUID]:
        out: set[uuid.UUID] = set()
        for conn in self._conns:
            out |= conn.challenges
        return out

    def watched_markets(self) -> set[uuid.UUID]:
        out: set[uuid.UUID] = set()
        for conn in self._conns:
            out |= conn.markets
        return out

    # ------------------------------------------------------------ 轮询与扇出

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_s)
            try:
                await self.poll_once()
            except Exception:  # 单轮失败只记日志，下一轮重试
                logger.exception("pm hub poll failed")

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_s)
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("pm sweeper failed")

    async def sweep_once(self) -> int:
        return await run_in_threadpool(pm_lifecycle.sync_due, self._sf, timeutil.now())

    async def poll_once(self) -> int:
        """读取被关注挑战的市场快照，与上一轮做差并扇出。返回变化的市场数。"""
        challenges = self.watched_challenges()
        if not challenges:
            return 0
        rows, ptts = await run_in_threadpool(self._load, challenges)
        return self._fanout(rows, ptts)

    def _load(
        self, challenge_ids: set[uuid.UUID]
    ) -> tuple[dict[uuid.UUID, dict[str, Any]], dict[uuid.UUID, int]]:
        now = timeutil.now()
        rows: dict[uuid.UUID, dict[str, Any]] = {}
        ptts: dict[uuid.UUID, int] = {}
        with self._sf() as db:
            for cid in challenge_ids:
                row = db.get(Challenge, cid)
                if row is None or row.status == "void":
                    continue
                info = pm_lifecycle.info_for(db, row)
                ptts[cid] = pm_lifecycle.public_tt(info, row, now)
            stmt = select(
                PredictionMarket.id,
                PredictionMarket.challenge_id,
                PredictionMarket.status,
                PredictionMarket.trade_seq,
                PredictionMarket.prices_ppm,
                PredictionMarket.volume_shares,
                PredictionMarket.winning_outcome,
            ).where(
                PredictionMarket.challenge_id.in_(list(challenge_ids)),
                PredictionMarket.status != "scheduled",
            )
            for mid, cid, status, seq, prices, volume, winning in db.execute(stmt).all():
                rows[mid] = {
                    "challenge_id": cid,
                    "status": status,
                    "trade_seq": seq,
                    "prices_ppm": list(prices or []),
                    "volume_shares": volume,
                    "winning_outcome": winning,
                }
        return rows, ptts

    def _fanout(self, rows: dict[uuid.UUID, dict[str, Any]], ptts: dict[uuid.UUID, int]) -> int:
        list_changed: set[uuid.UUID] = set()
        tick_changed: dict[uuid.UUID, dict[str, Any]] = {}
        resolved: dict[uuid.UUID, dict[str, Any]] = {}
        for mid, row in rows.items():
            key = (row["status"], row["trade_seq"])
            prev = self._snap.get(mid)
            if prev == key:
                continue
            self._snap[mid] = key
            cid = row["challenge_id"]
            if prev is None or prev[0] != row["status"]:
                list_changed.add(cid)
            tick_changed[mid] = row
            if row["status"] in TERMINAL and (prev is None or prev[0] not in TERMINAL):
                resolved[mid] = row
        for cid in list_changed:
            self._rev[cid] = self._rev.get(cid, 0) + 1
        for conn in list(self._conns):
            for cid in list_changed & conn.challenges:
                conn.queue.put_nowait(
                    {"t": "pm_list", "challenge_id": str(cid), "rev": self._rev[cid]}
                )
            for mid, row in resolved.items():
                if row["challenge_id"] in conn.challenges:
                    conn.queue.put_nowait(
                        {
                            "t": "pm_resolved",
                            "id": str(mid),
                            "status": row["status"],
                            "winning_outcome": row["winning_outcome"],
                        }
                    )
            for mid in conn.markets & tick_changed.keys():
                row = tick_changed[mid]
                conn.queue.put_nowait(
                    {
                        "t": "pm_tick",
                        "id": str(mid),
                        "seq": row["trade_seq"],
                        "status": row["status"],
                        "prices_ppm": row["prices_ppm"],
                        "volume_shares": row["volume_shares"],
                        "public_tt": ptts.get(row["challenge_id"]),
                    }
                )
        return len(tick_changed)

    # ------------------------------------------------------------ 客户端消息


def _market_exists(session_factory: sessionmaker[Session], market_id: uuid.UUID) -> bool:
    with session_factory() as db:
        return (
            db.scalar(
                select(PredictionMarket.id).where(
                    PredictionMarket.id == market_id, PredictionMarket.status != "scheduled"
                )
            )
            is not None
        )


def _auth(
    session_factory: sessionmaker[Session], settings: Settings, token: str | None
) -> User | None:
    with session_factory() as db:
        return resolve_session(db, settings, token)


async def _read_client(
    websocket: WebSocket, conn: PmConn, hub: PmHub, session_factory, settings
) -> None:
    """读循环：解析客户端消息，订阅变化直接作用于连接；回复经出站队列发送。"""
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if not isinstance(data, dict):
                conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
                continue
            await _handle(conn, hub, session_factory, data)
    except WebSocketDisconnect:
        pass
    finally:
        conn.queue.put_nowait({"t": "_close"})


async def _handle(conn: PmConn, hub: PmHub, session_factory, data: dict[str, Any]) -> None:
    kind = data.get("t")
    if kind == "ping":
        conn.queue.put_nowait({"t": "pong"})
        return
    if kind == "watch":
        cid = _uuid(data.get("challenge_id"))
        if cid is None:
            conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
            return
        conn.challenges.add(cid)
        return
    if kind in ("subscribe", "unsubscribe"):
        mid = _uuid(data.get("market_id"))
        if mid is None:
            conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
            return
        if kind == "unsubscribe":
            conn.markets.discard(mid)
            conn.queue.put_nowait({"t": "unsubscribed", "market_id": str(mid)})
            return
        if mid not in conn.markets and len(conn.markets) >= MAX_SUBSCRIPTIONS:
            conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
            return
        exists = await run_in_threadpool(_market_exists, session_factory, mid)
        if not exists:
            conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})
            return
        conn.markets.add(mid)
        conn.queue.put_nowait({"t": "subscribed", "market_id": str(mid)})
        return
    conn.queue.put_nowait({"t": "error", "code": ErrorCode.VALIDATION_ERROR.value})


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def stream_prediction_markets(
    websocket: WebSocket,
    hub: PmHub,
    session_factory: sessionmaker[Session],
    settings: Settings,
    token: str | None,
) -> None:
    """连接主循环。调用方已 accept。"""
    user = await run_in_threadpool(_auth, session_factory, settings, token)
    if user is None:
        await websocket.send_json({"t": "error", "code": ErrorCode.AUTH_REQUIRED.value})
        await websocket.close(code=CLOSE_AUTH_REQUIRED)
        return
    conn = hub.connect(user.id)
    reader = asyncio.create_task(_read_client(websocket, conn, hub, session_factory, settings))
    try:
        while True:
            msg = await conn.queue.get()
            if msg.get("t") == "_close":
                break
            await websocket.send_json(msg)
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reader
        hub.disconnect(conn)
