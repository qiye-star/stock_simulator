"""行情：全市场快照、单股详情（日 K/五档/涨跌停）、时间补推、暂停、跨日 K 线、自选标记。"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.models import Save
from stocksim.services.market import advance_ticks

SAVES = "/api/v1/saves"
REFRESH_SLOW = 60_000  # 测试中关闭挂钟补推，行情只随显式操作变化


def _save(client: TestClient, app: FastAPI, *, minute: int = 600) -> str:
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret1"})
    assert client.patch("/api/v1/me", json={"refresh_rate_ms": REFRESH_SLOW}).status_code == 200
    resp = client.post(SAVES, json={})
    assert resp.status_code == 201
    sid = resp.json()["id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = minute
        db.commit()
    return sid


def test_market_overview_has_every_stock_within_limits(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _save(registered_client, app)
    resp = registered_client.get(f"{SAVES}/{sid}/market")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trading_day"] == 0 and body["paused"] is False and body["session"] == "trading"
    assert len(body["stocks"]) == 385
    for quote in body["stocks"]:
        assert quote["limit_down_cents"] <= quote["price_cents"] <= quote["limit_up_cents"]
        assert quote["watchlisted"] is False
        assert quote["prev_close_cents"] > 0


def test_stock_detail_has_candles_and_order_book(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _save(registered_client, app)
    resp = registered_client.get(f"{SAVES}/{sid}/market/600036")
    assert resp.status_code == 200
    body = resp.json()
    candles = body["candles"]
    assert len(candles) == 60  # 59 根历史 + 当日
    assert candles[-1]["trading_day"] == 0
    assert candles[-1]["close_cents"] == body["price_cents"]
    assert candles == sorted(candles, key=lambda c: c["trading_day"])

    book = body["order_book"]
    price = body["price_cents"]
    assert len(book["bids"]) == 5 and len(book["asks"]) == 5
    bid_prices = [lvl["price_cents"] for lvl in book["bids"]]
    ask_prices = [lvl["price_cents"] for lvl in book["asks"]]
    assert bid_prices == sorted(bid_prices, reverse=True) and all(p < price for p in bid_prices)
    assert ask_prices == sorted(ask_prices) and all(p > price for p in ask_prices)
    assert all(lvl["volume"] >= 100 for lvl in book["bids"] + book["asks"])


def test_unknown_stock_is_not_found(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    resp = registered_client.get(f"{SAVES}/{sid}/market/999998")
    assert resp.status_code == 404
    assert resp.json() == {"code": "STOCK_NOT_FOUND", "params": {"code": "999998"}}


def test_wall_clock_catches_up_ticks(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    assert registered_client.patch("/api/v1/me", json={"refresh_rate_ms": 1000}).status_code == 200
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        before = save.tick
        save.last_tick_at = datetime.now(UTC) - timedelta(seconds=10, milliseconds=500)
        db.commit()
    after = registered_client.get(f"{SAVES}/{sid}").json()["tick"]
    assert 10 <= after - before <= 11  # 10.5 秒 / 1000ms，一次读取即补推
    # 紧接着再读不会重复补推
    assert registered_client.get(f"{SAVES}/{sid}").json()["tick"] == after


def test_paused_clock_does_not_advance(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    registered_client.post(f"{SAVES}/{sid}/clock/pause")
    assert registered_client.patch("/api/v1/me", json={"refresh_rate_ms": 1000}).status_code == 200
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.last_tick_at = datetime.now(UTC) - timedelta(seconds=30)
        db.commit()
    before = registered_client.get(f"{SAVES}/{sid}").json()["tick"]
    assert registered_client.get(f"{SAVES}/{sid}").json()["tick"] == before


def test_day_rollover_appends_closed_candle(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app, minute=600)
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        advance_ticks(db, save, 25)  # 20 个交易 tick 即翻到交易日 1
    detail = registered_client.get(f"{SAVES}/{sid}/market/600036").json()
    assert registered_client.get(f"{SAVES}/{sid}").json()["trading_day"] == 1
    assert detail["candles"][-1]["trading_day"] == 1
    closed = [c for c in detail["candles"] if c["trading_day"] == 0]
    assert len(closed) == 1
    assert closed[0]["high_cents"] >= closed[0]["low_cents"]
    assert len(detail["candles"]) == 61  # 59 历史 + 收盘的第 0 日 + 当日


def test_watchlist_add_remove_and_market_flag(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    assert (
        registered_client.put(f"{SAVES}/{sid}/watchlist/999998").json()["code"] == "STOCK_NOT_FOUND"
    )

    assert registered_client.put(f"{SAVES}/{sid}/watchlist/600036").status_code == 204
    assert registered_client.put(f"{SAVES}/{sid}/watchlist/600036").status_code == 204  # 幂等
    market = registered_client.get(f"{SAVES}/{sid}/market").json()["stocks"]
    flags = {q["code"]: q["watchlisted"] for q in market}
    assert flags["600036"] is True and sum(flags.values()) == 1

    assert registered_client.delete(f"{SAVES}/{sid}/watchlist/600036").status_code == 204
    market = registered_client.get(f"{SAVES}/{sid}/market").json()["stocks"]
    assert not any(q["watchlisted"] for q in market)
