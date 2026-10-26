"""时钟 v2 行情（07 §9.2）：分时逐步精确重放、墙钟补推与逐分钟推进的结果逐位一致。"""

import uuid
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from stocksim.db.base import utcnow
from stocksim.models import Candle, MarketState, Save
from stocksim.services.market import advance_ticks, init_market_for_save

SAVES = "/api/v1/saves"
CODE = "600036"


def _create_v2(client: TestClient) -> str:
    resp = client.post(SAVES, json={"clock_rules": 2})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _skip(client: TestClient, sid: str) -> dict:
    return client.post(f"{SAVES}/{sid}/clock/skip").json()


def _intraday(client: TestClient, sid: str) -> dict:
    resp = client.get(f"{SAVES}/{sid}/market/{CODE}/intraday")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_intraday_is_exact_at_every_skip_across_lunch_close_and_rollover(
    registered_client: TestClient,
) -> None:
    client = registered_client
    sid = _create_v2(client)
    last_points = -1
    for expected_minute in (689, 690, 779, 780, 899, 900, 569, 570):
        skipped = _skip(client, sid)
        assert skipped["clock_minute"] == expected_minute
        data = _intraday(client, sid)
        assert data["exact"] is True, expected_minute
        points = data["points"]
        minutes = [p["minute"] for p in points]
        assert minutes == sorted(minutes) and len(set(minutes)) == len(minutes)
        volumes = [p["volume"] for p in points]
        assert volumes == sorted(volumes)  # v2 成交量为当日累计，单调不减
        if points:
            market = client.get(f"{SAVES}/{sid}/market/{CODE}").json()
            assert points[-1]["price_cents"] == market["price_cents"]
            assert points[-1]["volume"] == market["volume"]
        if expected_minute == 779:
            assert len(points) == last_points  # 午休快进无新点
        if expected_minute == 569:
            assert len(points) == last_points  # 收盘后到次日开盘前无新点
        last_points = len(points)
    # 次日开盘后的第一个点是换日 tick，分时重新累计
    day_one = _intraday(client, sid)
    assert day_one["trading_day"] == 1 and len(day_one["points"]) == 1


def _snapshot(app: FastAPI, sid: str) -> tuple:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        market = db.get(MarketState, uuid.UUID(sid))
        candles = db.execute(
            select(
                Candle.stock_code,
                Candle.trading_day,
                Candle.open_cents,
                Candle.high_cents,
                Candle.low_cents,
                Candle.close_cents,
                Candle.volume,
            )
            .where(Candle.save_id == uuid.UUID(sid))
            .order_by(Candle.stock_code, Candle.trading_day)
        ).all()
        return (
            save.tick,
            save.clock_minute,
            save.trading_day,
            dict(market.payload),
            [tuple(c) for c in candles],
        )


def test_wall_clock_catch_up_equals_minute_by_minute_advance(
    registered_client: TestClient, app: FastAPI
) -> None:
    """同一 seed 的两个 v2 存档：A 靠墙钟补推（跨午休、收盘停留与次日换日），B 逐分钟推进。"""
    client = registered_client
    client.patch("/api/v1/me", json={"clock_speed": "fast"})  # 2500 ms / 分钟
    sid_a = _create_v2(client)
    sid_b = _create_v2(client)
    with app.state.session_factory() as db:
        a = db.get(Save, uuid.UUID(sid_a))
        b = db.get(Save, uuid.UUID(sid_b))
        b.market_seed = a.market_seed
        as_of = db.get(MarketState, uuid.UUID(sid_a)).payload["_meta"]["as_of"]
        for model in (MarketState, Candle):
            for row in db.scalars(select(model).where(model.save_id == uuid.UUID(sid_b))).all():
                db.delete(row)
        db.flush()
        init_market_for_save(db, b, date.fromisoformat(as_of))
        db.commit()

    # A：回拨约 1 个交易日多一点（超过 242 个交易 tick，含午休与收盘停留）
    with app.state.session_factory() as db:
        a = db.get(Save, uuid.UUID(sid_a))
        a.last_tick_at = utcnow() - timedelta(milliseconds=2500 * 2000 + 30_000)
        db.commit()
    client.get(f"{SAVES}/{sid_a}/market?limit=1")  # 触发补推
    with app.state.session_factory() as db:
        a = db.get(Save, uuid.UUID(sid_a))
        target_minutes = a.tick
        a.last_tick_at = utcnow() + timedelta(days=1)  # B 不再有墙钟补推
        db.commit()
    assert target_minutes > 1440  # 跨过至少一个次日换日

    with app.state.session_factory() as db:
        for _ in range(target_minutes):
            b = db.get(Save, uuid.UUID(sid_b))
            advance_ticks(db, b, 1)

    with app.state.session_factory() as db:
        a = db.get(Save, uuid.UUID(sid_a))
        b = db.get(Save, uuid.UUID(sid_b))
        assert (a.tick, a.clock_minute) == (b.tick, b.clock_minute)
    snap_a = _snapshot(app, sid_a)
    snap_b = _snapshot(app, sid_b)
    assert snap_a[:3] == snap_b[:3]
    assert snap_a[3] == snap_b[3]  # payload 逐位相同
    assert snap_a[4] == snap_b[4]  # candles 逐行相同
