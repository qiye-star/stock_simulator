"""持仓：估值、资产汇总、T+1 可卖股数、卖出实现盈亏。"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.models import Save
from stocksim.services.market import advance_ticks

SAVES = "/api/v1/saves"
CODE = "600036"
INITIAL = 100_000_000


def _setup(client: TestClient, app: FastAPI) -> str:
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret1"})
    assert client.patch("/api/v1/me", json={"refresh_rate_ms": 60_000}).status_code == 200
    sid = client.post(SAVES, json={}).json()["id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = 600
        db.commit()
    return sid


def _fee(amount: int, rate: str) -> int:
    return int((Decimal(amount) * Decimal(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _buy(client: TestClient, sid: str, qty: int = 100) -> dict:
    resp = client.post(f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": qty})
    assert resp.status_code == 201, resp.text
    return resp.json()["trade"]


def test_portfolio_values_holdings_and_cash(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    trade = _buy(registered_client, sid)
    gross = trade["price_cents"] * 100
    fee = _fee(gross, "0.0003")
    assert trade["gross_cents"] == gross and trade["fee_cents"] == fee

    body = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    assert body["cash_cents"] == INITIAL - gross - fee
    assert body["initial_fund_cents"] == INITIAL
    assert len(body["holdings"]) == 1
    holding = body["holdings"][0]
    assert holding["code"] == CODE and holding["quantity"] == 100
    assert holding["sellable_quantity"] == 0  # T+1：当日买入不可卖
    assert holding["total_cost_cents"] == gross + fee
    assert holding["market_value_cents"] == 100 * trade["price_cents"]
    assert body["equity_cents"] == body["cash_cents"] + body["market_value_cents"]
    assert body["net_pnl_cents"] == body["equity_cents"] - INITIAL


def test_sellable_quantity_unlocks_next_trading_day(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    _buy(registered_client, sid)
    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(sid)), 20)
    holding = registered_client.get(f"{SAVES}/{sid}/portfolio").json()["holdings"][0]
    assert holding["sellable_quantity"] == 100


def test_sell_realizes_pnl_against_average_cost(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    buy = _buy(registered_client, sid)
    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(sid)), 20)

    sell = registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "sell", "quantity": 100}
    ).json()["trade"]
    total_cost = buy["gross_cents"] + buy["fee_cents"]
    avg = int((Decimal(total_cost) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    sell_gross = sell["price_cents"] * 100
    sell_fee = _fee(sell_gross, "0.0013")
    expected_pnl = (sell["price_cents"] - avg) * 100 - sell_fee
    assert sell["realized_pnl_cents"] == expected_pnl
    assert sell["cash_delta_cents"] == sell_gross - sell_fee

    body = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    assert body["holdings"] == []  # 清仓后持仓移除
    assert body["cash_cents"] == INITIAL - total_cost + sell["cash_delta_cents"]


def test_portfolio_is_scoped_to_owner(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    registered_client.post("/api/v1/auth/logout")
    registered_client.post("/api/v1/auth/register", json={"username": "bob", "password": "secret1"})
    assert registered_client.get(f"{SAVES}/{sid}/portfolio").status_code == 404
