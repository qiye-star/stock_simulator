"""并发请求跨交易日补推：不得 500，收盘数据（K线/权益快照）每交易日恰好一行，结果与串行一致。

回归背景：新存档静置一段时间后，待补推的 tick 跨过交易日；多个请求同时 advance_to_now，
后提交者写同一交易日的 candles / equity_snapshots 撞唯一约束抛 IntegrityError，
旧的 `_retrying` 只接 StaleDataError，于是 500。
"""

import threading
import uuid
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.db.base import utcnow
from stocksim.models import Candle, EquitySnapshot, MarketState, Save
from stocksim.services.market import advance_to_now

SAVES = "/api/v1/saves"
RATE_MS = 60_000
PENDING_TICKS = 100  # 从 600 分钟起推 100 个 tick，跨过多个交易日（每日 20 个交易 tick）
READ_PATHS = [
    "portfolio",
    "trades",
    "auto-trade/configs",
    "auto-trade/status",
    "market?limit=500&watchlisted=true",
    "equity-curve?range=all",
    "auto-trade/events?limit=20",
    "market",
]


def _stale_save(client: TestClient, app: FastAPI, seed: int = 12345) -> str:
    """新建存档并回拨 last_tick_at，使其有 PENDING_TICKS 个 tick 待补推（0.5 个周期余量防抖）。"""
    client.patch("/api/v1/me", json={"refresh_rate_ms": RATE_MS})
    sid = client.post(SAVES, json={}).json()["id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = 600
        save.market_seed = seed
        save.last_tick_at = utcnow() - timedelta(milliseconds=int((PENDING_TICKS + 0.5) * RATE_MS))
        db.commit()
    return sid


def _clone_save(app: FastAPI, sid: str) -> str:
    """复制存档的行情初始状态（payload/种子/时钟/历史 K 线）作为串行基准。"""
    with app.state.session_factory() as db:
        src = db.get(Save, uuid.UUID(sid))
        new_id = uuid.uuid4()
        db.add(
            Save(
                id=new_id,
                **{
                    c.name: getattr(src, c.name)
                    for c in Save.__table__.columns
                    if c.name not in ("id", "version")
                },
            )
        )
        db.flush()
        db.add(
            MarketState(
                save_id=new_id, payload=db.get(MarketState, src.id).payload, updated_at=utcnow()
            )
        )
        for c in db.scalars(select(Candle).where(Candle.save_id == src.id)):
            db.add(
                Candle(
                    save_id=new_id,
                    stock_code=c.stock_code,
                    trading_day=c.trading_day,
                    open_cents=c.open_cents,
                    high_cents=c.high_cents,
                    low_cents=c.low_cents,
                    close_cents=c.close_cents,
                    volume=c.volume,
                )
            )
        db.commit()
        return str(new_id)


def _final_state(app: FastAPI, sid: str) -> dict[str, Any]:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        uid = uuid.UUID(sid)
        candles = db.execute(
            select(Candle.stock_code, Candle.trading_day, Candle.close_cents, Candle.volume)
            .where(Candle.save_id == uid)
            .order_by(Candle.stock_code, Candle.trading_day)
        ).all()
        dup_candles = db.execute(
            select(Candle.stock_code, Candle.trading_day)
            .where(Candle.save_id == uid)
            .group_by(Candle.stock_code, Candle.trading_day)
            .having(func.count() > 1)
        ).all()
        snaps = db.execute(
            select(
                EquitySnapshot.trading_day,
                EquitySnapshot.equity_cents,
                EquitySnapshot.cash_cents,
                EquitySnapshot.tick,
            )
            .where(EquitySnapshot.save_id == uid)
            .order_by(EquitySnapshot.trading_day)
        ).all()
        return {
            "tick": save.tick,
            "clock_minute": save.clock_minute,
            "trading_day": save.trading_day,
            "payload": db.get(MarketState, uid).payload,
            "candles": [tuple(r) for r in candles],
            "dup_candles": dup_candles,
            "snaps": [tuple(r) for r in snaps],
        }


def _assert_equivalent(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual["dup_candles"] == []
    assert actual["trading_day"] >= 3  # 确认确实跨了多个交易日
    days = [d for d, *_ in actual["snaps"]]
    assert days == list(range(actual["trading_day"]))  # 每个已收盘交易日恰好一行快照
    for key in ("tick", "clock_minute", "trading_day", "payload", "candles", "snaps"):
        assert actual[key] == expected[key], key


def _serial_expected(app: FastAPI, sid: str) -> dict[str, Any]:
    twin = _clone_save(app, sid)
    with app.state.session_factory() as db:
        assert advance_to_now(db, db.get(Save, uuid.UUID(twin))) == PENDING_TICKS
    return _final_state(app, twin)


def _hammer(client: TestClient, sid: str) -> dict[str, int]:
    """同一时刻并发请求所有读接口（Barrier 对齐起跑），返回 {路径: 状态码}。"""
    barrier = threading.Barrier(len(READ_PATHS))
    results: dict[str, int] = {}

    def hit(path: str) -> None:
        barrier.wait()
        results[path] = client.get(f"{SAVES}/{sid}/{path}").status_code

    threads = [threading.Thread(target=hit, args=(p,)) for p in READ_PATHS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_requests_across_trading_days(
    registered_client: TestClient, app: FastAPI
) -> None:
    for round_ in range(3):  # 多轮提高撞车概率；任何一轮出现 500 即失败
        sid = _stale_save(registered_client, app, seed=1000 + round_)
        expected = _serial_expected(app, sid)

        results = _hammer(registered_client, sid)

        assert results == dict.fromkeys(READ_PATHS, 200), results
        _assert_equivalent(_final_state(app, sid), expected)


def test_stale_session_hits_unique_conflict_and_recovers(
    registered_client: TestClient, app: FastAPI
) -> None:
    """确定性复现：会话 B 持有过期的存档与行情，会话 A 先补推并提交，B 再补推必撞唯一约束。"""
    sid = _stale_save(registered_client, app)
    expected = _serial_expected(app, sid)
    uid = uuid.UUID(sid)

    with app.state.session_factory() as db_a, app.state.session_factory() as db_b:
        save_b = db_b.get(Save, uid)
        db_b.get(MarketState, uid)  # B 缓存了旧行情 payload
        assert advance_to_now(db_a, db_a.get(Save, uid)) == PENDING_TICKS
        # 修复前此处抛 IntegrityError（candles 唯一约束）；修复后回滚重读，发现无事可做
        assert advance_to_now(db_b, save_b) == 0

    _assert_equivalent(_final_state(app, sid), expected)
