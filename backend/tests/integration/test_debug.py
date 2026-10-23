"""调试接口：默认关闭返回 403 DEBUG_DISABLED；开启后各动作改写存档的预期字段。"""

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.domain.achievements.catalog import CATALOG
from stocksim.main import create_app
from stocksim.models import Holding, MarketState, Save, SaveAchievement, Trade
from stocksim.services.seed import seed_stock_table

PASSWORD = "secret1"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_EXPORT = (FIXTURES / "legacy_export.txt").read_text(encoding="ascii")


def _url(save_id: str, action: str) -> str:
    return f"/api/v1/saves/{save_id}/debug/{action}"


ACTIONS = ("fund", "time", "achievements", "reset-market", "clear")


@pytest.fixture
def disabled_client(registered_client: TestClient, app: FastAPI) -> TestClient:
    with app.state.session_factory() as db:
        seed_stock_table(db)
    return registered_client


@pytest.fixture
def debug_ctx(settings, migrated: str) -> tuple[TestClient, FastAPI, str]:
    app = create_app(settings.model_copy(update={"ENABLE_DEBUG_API": True}))
    with app.state.session_factory() as db:  # 通过 app 的 session 工厂播种股票表
        seed_stock_table(db)
    client = TestClient(app)
    client.__enter__()
    try:
        assert (
            client.post(
                "/api/v1/auth/register", json={"username": "alice", "password": PASSWORD}
            ).status_code
            == 201
        )
        resp = client.post("/api/v1/saves", json={"name": "d", "initial_fund_cents": 100_000_000})
        assert resp.status_code == 201, resp.text
        yield client, app, resp.json()["id"]
    finally:
        client.__exit__(None, None, None)


def test_debug_disabled_by_default(disabled_client: TestClient) -> None:
    save_id = disabled_client.post(
        "/api/v1/saves", json={"name": "d", "initial_fund_cents": 100_000_000}
    ).json()["id"]
    bodies = {
        "fund": {"cash_cents": 1},
        "time": {"minute_of_day": 600},
        "achievements": {"action": "clear_all"},
        "reset-market": None,
        "clear": None,
    }
    for action in ACTIONS:
        body = bodies[action]
        resp = (
            disabled_client.post(_url(save_id, action), json=body)
            if body
            else disabled_client.post(_url(save_id, action))
        )
        assert resp.status_code == 403, action
        assert resp.json() == {"code": "DEBUG_DISABLED", "params": {}}


def test_debug_requires_login_even_when_enabled(debug_ctx) -> None:
    _, app, save_id = debug_ctx
    anon = TestClient(app)
    resp = anon.post(_url(save_id, "clear"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


def test_fund_sets_cash(debug_ctx) -> None:
    client, _, save_id = debug_ctx
    resp = client.post(_url(save_id, "fund"), json={"cash_cents": 5_000_000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cash_cents"] == 5_000_000 and resp.json()["action"] == "fund"


def test_time_sets_clock_minute(debug_ctx) -> None:
    client, app, save_id = debug_ctx
    resp = client.post(_url(save_id, "time"), json={"minute_of_day": 840})
    assert resp.json()["clock_minute"] == 840
    with app.state.session_factory() as db:
        assert db.get(Save, uuid.UUID(save_id)).clock_minute == 840


def test_time_rejects_out_of_range(debug_ctx) -> None:
    client, _, save_id = debug_ctx
    resp = client.post(_url(save_id, "time"), json={"minute_of_day": 1440})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_achievements_unlock_lock_and_bulk(debug_ctx) -> None:
    client, app, save_id = debug_ctx
    url = _url(save_id, "achievements")
    assert (
        client.post(url, json={"action": "unlock", "ids": ["first_trade"]}).json()["changed"] == 1
    )
    assert (
        client.post(url, json={"action": "unlock", "ids": ["first_trade"]}).json()["changed"] == 0
    )
    bad = client.post(url, json={"action": "unlock", "ids": ["nope"]})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    assert client.post(url, json={"action": "lock", "ids": ["first_trade"]}).json()["changed"] == 1
    assert client.post(url, json={"action": "unlock_all"}).json()["changed"] == len(CATALOG)
    assert client.post(url, json={"action": "clear_all"}).json()["changed"] == len(CATALOG)
    with app.state.session_factory() as db:
        remaining = db.scalar(
            select(func.count())
            .select_from(SaveAchievement)
            .where(SaveAchievement.save_id == uuid.UUID(save_id))
        )
        assert remaining == 0


def test_clear_resets_cash_trades_and_holdings(debug_ctx) -> None:
    client, app, _ = debug_ctx
    # 导入一份旧存档（带成交与持仓），再清空
    imported = client.post("/api/v1/import/legacy", json={"content": SAMPLE_EXPORT})
    assert imported.status_code == 200, imported.text
    sid = uuid.UUID(imported.json()["imported"][0]["save_id"])
    resp = client.post(f"/api/v1/saves/{sid}/debug/clear")
    assert resp.status_code == 200, resp.text
    assert resp.json()["cash_cents"] == 100_000_000  # 回到初始资金
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Trade).where(Trade.save_id == sid)) == 0
        assert (
            db.scalar(select(func.count()).select_from(Holding).where(Holding.save_id == sid)) == 0
        )


def test_reset_market_regenerates_seed_and_payload(debug_ctx) -> None:
    client, app, save_id = debug_ctx
    sid = uuid.UUID(save_id)
    with app.state.session_factory() as db:
        before_seed = db.get(Save, sid).market_seed
        before_payload = dict(db.get(MarketState, sid).payload)
    resp = client.post(_url(save_id, "reset-market"))
    assert resp.status_code == 200, resp.text
    with app.state.session_factory() as db:
        assert db.get(Save, sid).market_seed != before_seed
        assert db.get(MarketState, sid).payload != before_payload


def test_other_user_cannot_use_debug(debug_ctx) -> None:
    _, app, save_id = debug_ctx
    bob = TestClient(app)
    assert (
        bob.post(
            "/api/v1/auth/register", json={"username": "bob", "password": PASSWORD}
        ).status_code
        == 201
    )
    resp = bob.post(_url(save_id, "fund"), json={"cash_cents": 1})
    assert resp.status_code == 404
    assert resp.json()["code"] == "SAVE_NOT_FOUND"
