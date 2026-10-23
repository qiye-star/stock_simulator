"""下单：市价/限价、T+1、涨跌停与资金校验、交易单位、休市、幂等键、成交流水分页、成就落库。"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.models import Save, Trade
from stocksim.services.market import advance_ticks

SAVES = "/api/v1/saves"
CODE = "600036"


def _setup(client: TestClient, app: FastAPI, *, minute: int = 600, **save_fields) -> str:
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret1"})
    # 关闭挂钟补推：行情只随测试显式推进，价格可预测
    assert client.patch("/api/v1/me", json={"refresh_rate_ms": 60_000}).status_code == 200
    resp = client.post(SAVES, json=save_fields)
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    _set_save(app, sid, clock_minute=minute)
    return sid


def _set_save(app: FastAPI, sid: str, **values) -> None:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        for key, value in values.items():
            setattr(save, key, value)
        db.commit()


def _advance_trading_day(app: FastAPI, sid: str) -> None:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        advance_ticks(db, save, 20)  # 20 个交易 tick = 一个交易日


def _price(client: TestClient, sid: str, code: str = CODE) -> dict:
    return client.get(f"{SAVES}/{sid}/market/{code}").json()


def _order(client: TestClient, sid: str, **body) -> object:
    payload = {"code": CODE, "side": "buy", "quantity": 100, **body}
    return client.post(f"{SAVES}/{sid}/orders", json=payload)


def test_market_buy_fills_at_quoted_price(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    price = _price(registered_client, sid)["price_cents"]
    resp = _order(registered_client, sid, quantity=100)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    trade = body["trade"]
    assert (
        trade["side"] == "buy" and trade["source"] == "manual" and trade["price_type"] == "market"
    )
    assert trade["price_cents"] == price and trade["quantity"] == 100
    assert trade["seq"] == 1 and trade["trading_day"] == 0 and trade["clock_minute"] == 600
    assert (
        trade["cash_delta_cents"] < 0
        and body["cash_cents"] == 100_000_000 + trade["cash_delta_cents"]
    )
    assert isinstance(body["unlocked_achievement_ids"], list) and body["replayed"] is False


def test_t1_blocks_same_day_sell(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    assert _order(registered_client, sid, quantity=100).status_code == 201
    resp = _order(registered_client, sid, side="sell", quantity=100)
    assert resp.status_code == 422
    assert resp.json()["code"] == "TRADE_T1_SELL_BLOCKED"
    assert resp.json()["params"] == {"bought": 100, "available": 0}


def test_next_day_sell_allowed_then_same_day_rebuy_blocked(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    assert _order(registered_client, sid, quantity=100).status_code == 201
    _advance_trading_day(app, sid)
    assert registered_client.get(f"{SAVES}/{sid}").json()["trading_day"] == 1

    sold = _order(registered_client, sid, side="sell", quantity=100)
    assert sold.status_code == 201, sold.text
    assert sold.json()["trade"]["side"] == "sell"  # 盈亏公式见 test_portfolio

    rebuy = _order(registered_client, sid, quantity=100)
    assert rebuy.status_code == 422
    assert rebuy.json()["code"] == "TRADE_T1_BUY_BLOCKED"


def test_limit_order_not_crossed_is_rejected(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    price = _price(registered_client, sid)["price_cents"]
    resp = _order(registered_client, sid, price_type="limit", limit_price_cents=price - 1)
    assert resp.status_code == 422
    assert resp.json()["code"] == "ORDER_LIMIT_NOT_REACHED"


def test_limit_order_crossed_fills_at_market_price(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    quote = _price(registered_client, sid)
    # 买入限价高于市价：按市价成交
    resp = _order(
        registered_client, sid, price_type="limit", limit_price_cents=quote["price_cents"] + 0
    )
    assert resp.status_code == 201, resp.text
    trade = resp.json()["trade"]
    assert trade["price_type"] == "limit" and trade["limit_price_cents"] == quote["price_cents"]
    assert trade["price_cents"] == quote["price_cents"]


def test_limit_price_outside_limit_band_is_rejected(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    quote = _price(registered_client, sid)
    resp = _order(
        registered_client, sid, price_type="limit", limit_price_cents=quote["limit_up_cents"] + 1
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "TRADE_PRICE_OUT_OF_LIMIT"


def test_insufficient_funds_and_invalid_quantity(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app, trade_unit=100)
    broke = _order(registered_client, sid, quantity=100_000_000)
    assert broke.status_code == 422 and broke.json()["code"] == "TRADE_INSUFFICIENT_FUNDS"

    odd = _order(registered_client, sid, quantity=50)
    assert odd.status_code == 422 and odd.json()["code"] == "TRADE_INVALID_QUANTITY"

    zero = _order(registered_client, sid, quantity=0)
    assert zero.status_code == 422 and zero.json()["code"] == "TRADE_INVALID_QUANTITY"


def test_market_closed_rejects_orders(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app, minute=12 * 60)  # 午休
    resp = _order(registered_client, sid, quantity=100)
    assert resp.status_code == 409 and resp.json()["code"] == "MARKET_CLOSED"


def test_unknown_stock_order_is_not_found(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    resp = _order(registered_client, sid, code="999998")
    assert resp.status_code == 404 and resp.json()["code"] == "STOCK_NOT_FOUND"


def test_idempotency_key_replays_same_trade(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    headers = {"Idempotency-Key": "order-abc-1"}
    first = registered_client.post(
        f"{SAVES}/{sid}/orders",
        json={"code": CODE, "side": "buy", "quantity": 100},
        headers=headers,
    )
    second = registered_client.post(
        f"{SAVES}/{sid}/orders",
        json={"code": CODE, "side": "buy", "quantity": 100},
        headers=headers,
    )
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["trade"]["id"] == first.json()["trade"]["id"]
    trades = registered_client.get(f"{SAVES}/{sid}/trades").json()["items"]
    assert len(trades) == 1


def test_trades_are_paginated_newest_first(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    for _ in range(51):
        assert _order(registered_client, sid, quantity=1).status_code == 201

    first = registered_client.get(f"{SAVES}/{sid}/trades").json()
    assert len(first["items"]) == 50 and first["next_cursor"] is not None
    seqs = [t["seq"] for t in first["items"]]
    assert seqs == sorted(seqs, reverse=True)

    second = registered_client.get(
        f"{SAVES}/{sid}/trades", params={"cursor": first["next_cursor"]}
    ).json()
    assert [t["seq"] for t in second["items"]] == [1]
    assert second["next_cursor"] is None
    assert (
        registered_client.get(f"{SAVES}/{sid}/trades", params={"cursor": "abc"}).status_code == 422
    )


def test_first_trade_unlocks_achievements_and_persists_them(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    resp = _order(registered_client, sid, quantity=100)
    assert resp.status_code == 201
    unlocked = resp.json()["unlocked_achievement_ids"]
    catalog_ids = {a["id"] for a in registered_client.get("/api/v1/achievements/catalog").json()}
    assert set(unlocked) <= catalog_ids
    stored = registered_client.get(f"{SAVES}/{sid}/achievements").json()
    assert {a["achievement_id"] for a in stored} == set(unlocked)
    # 再次交易不会重复解锁
    again = _order(registered_client, sid, quantity=100).json()["unlocked_achievement_ids"]
    assert not set(again) & set(unlocked)


def test_order_snapshots_are_stored_on_trade(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    quote = _price(registered_client, sid)
    trade = _order(registered_client, sid, quantity=100).json()["trade"]
    assert trade["prev_close_cents"] == quote["prev_close_cents"]
    assert trade["name"] == quote["name"]
    with app.state.session_factory() as db:
        row = db.get(Trade, uuid.UUID(trade["id"]))
        assert row is not None and row.fund_before_cents == 100_000_000


def test_export_includes_trades_with_serializable_fields(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    assert _order(registered_client, sid, quantity=100).status_code == 201
    resp = registered_client.get(f"{SAVES}/{sid}/export")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["trades"]) == 1 and body["trades"][0]["code"] == CODE
    assert body["holdings"][0]["quantity"] == 100
    assert body["trades"][0]["created_at"]
