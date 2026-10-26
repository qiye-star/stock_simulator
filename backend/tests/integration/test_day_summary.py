"""收盘小结 GET /saves/{id}/day-summary（07 §1.4、§9.2）。

覆盖：当前日口径（成交与持仓）、涨跌家数、排序、过去日取自 candles 与快照、
v1 存档可用、他人存档 404。
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.models import Save

SAVES = "/api/v1/saves"
CODE = "600036"


def _summary(client: TestClient, sid: str, **params) -> dict:
    resp = client.get(f"{SAVES}/{sid}/day-summary", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_current_day_with_trade_and_holding(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = client.post(SAVES, json={"clock_rules": 2}).json()["id"]  # 9:30 开盘
    order = client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": 100}
    )
    assert order.status_code == 201, order.text

    body = _summary(client, sid)
    assert body["trading_day"] == 0 and body["status"] == "trading"
    assert body["trades"]["count"] == 1 and body["trades"]["buy_count"] == 1
    assert body["trades"]["sell_count"] == 0
    assert body["trades"]["buy_amount_cents"] > 0
    assert body["trades"]["fee_cents"] > 0
    assert [h["code"] for h in body["holdings"]] == [CODE]
    assert body["holdings"][0]["quantity"] == 100
    # 当日盈亏口径与 portfolio 一致：只含手续费，昨收与开盘相同
    portfolio = client.get(f"{SAVES}/{sid}/portfolio").json()
    assert body["day_pnl_cents"] == portfolio["day_pnl_cents"]
    assert body["equity_cents"] == portfolio["equity_cents"]
    assert body["prev_equity_cents"] == portfolio["prev_equity_cents"]
    assert body["next_open_at"] is None  # 交易中，不是“下一次开盘”


def test_market_counts_and_ordering(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = client.post(SAVES, json={"clock_rules": 2}).json()["id"]
    body = _summary(client, sid)
    market = body["market"]
    assert market["total"] == 385
    assert market["up"] + market["down"] + market["flat"] == market["total"]
    gains = [q["change_bp"] for q in body["top_gainers"]]
    losses = [q["change_bp"] for q in body["top_losers"]]
    assert len(gains) <= 5 and len(losses) <= 5
    assert gains == sorted(gains, reverse=True) and all(g > 0 for g in gains)
    assert losses == sorted(losses) and all(v < 0 for v in losses)


def test_past_day_uses_candles_and_snapshots(registered_client: TestClient, app: FastAPI) -> None:
    """跨过第 0 日收盘后，第 0 日小结来自 candles 与 equity_snapshots。"""
    client = registered_client
    sid = client.post(SAVES, json={"clock_rules": 2}).json()["id"]
    for _ in range(8):  # 一个完整交易日（含两段停留的快进）
        client.post(f"{SAVES}/{sid}/clock/skip")
    market = client.get(f"{SAVES}/{sid}/market?limit=1").json()
    assert market["trading_day"] == 1

    past = _summary(client, sid, trading_day=0)
    assert past["status"] == "closed" and past["holdings"] is None
    assert past["market"]["total"] == 385
    assert past["equity_cents"] == past["prev_equity_cents"] == 100_000_000
    assert past["cash_cents"] == 100_000_000 and past["market_value_cents"] == 0

    current = _summary(client, sid)
    assert current["trading_day"] == 1 and current["status"] == "trading"


def test_v1_save_has_summary_too(registered_client: TestClient, app: FastAPI) -> None:
    sid = registered_client.post(SAVES, json={}).json()["id"]
    body = _summary(registered_client, sid)
    assert body["clock_rules"] == "v1" and body["market"]["total"] == 385


def test_summary_is_per_user(registered_client: TestClient, app: FastAPI) -> None:
    """他人存档一律 404（与其它存档接口一致）。"""
    sid = registered_client.post(SAVES, json={}).json()["id"]
    with TestClient(app) as other:
        assert other.post(
            "/api/v1/auth/register", json={"username": "mallory", "password": "secret1"}
        ).status_code == 201
        resp = other.get(f"{SAVES}/{sid}/day-summary")
        assert resp.status_code == 404
        assert resp.json()["code"] == "SAVE_NOT_FOUND"
    with app.state.session_factory() as db:
        assert db.get(Save, uuid.UUID(sid)) is not None
