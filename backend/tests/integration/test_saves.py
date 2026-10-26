"""存档：创建/列表/详情/改名/删除/导出、归属隔离、时钟暂停与跳过、股票池种子、成就目录。"""

import uuid
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.models import Save, Stock
from stocksim.services.seed import seed_stock_table

PASSWORD = "secret1"
SAVES = "/api/v1/saves"


def _create(client: TestClient, **overrides) -> dict:
    body = {"name": "我的存档", **overrides}
    resp = client.post(SAVES, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_save(app: FastAPI, save_id: str, **values) -> None:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(save_id))
        assert save is not None
        for key, value in values.items():
            setattr(save, key, value)
        db.commit()


def test_create_save_initializes_market_and_fields(registered_client: TestClient) -> None:
    save = _create(registered_client, initial_fund_cents=50_000_000, t0_mode=False, trade_unit=100)
    assert save["name"] == "我的存档"
    assert save["initial_fund_cents"] == 50_000_000
    assert save["cash_cents"] == 50_000_000
    assert save["buy_fee_rate"] == "0.0003"
    assert save["sell_fee_rate"] == "0.0013"
    assert save["trade_unit"] == 100
    assert save["trading_day"] == 0 and save["tick"] == 0 and save["paused"] is False
    assert 570 <= save["clock_minute"] <= 690  # 开局在 9:30-11:30 之间

    detail = registered_client.get(f"{SAVES}/{save['id']}")
    assert detail.status_code == 200
    listed = registered_client.get(SAVES).json()
    assert [s["id"] for s in listed] == [save["id"]]


def test_create_save_validates_input(registered_client: TestClient) -> None:
    bad_unit = registered_client.post(SAVES, json={"trade_unit": 3})
    assert bad_unit.status_code == 422 and bad_unit.json()["code"] == "VALIDATION_ERROR"
    too_small = registered_client.post(SAVES, json={"initial_fund_cents": 10})
    assert too_small.status_code == 422 and too_small.json()["code"] == "VALIDATION_ERROR"


def test_save_endpoints_require_login(client: TestClient) -> None:
    resp = client.get(SAVES)
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


def test_save_limit_reached(registered_client: TestClient) -> None:
    for _ in range(10):
        _create(registered_client)
    resp = registered_client.post(SAVES, json={})
    assert resp.status_code == 409
    assert resp.json() == {"code": "SAVE_LIMIT_REACHED", "params": {"limit": 10}}


def test_other_users_saves_are_not_found(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"username": "alice", "password": PASSWORD})
    save = _create(client)
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/register", json={"username": "bob", "password": PASSWORD})

    sid = save["id"]
    not_found = {"code": "SAVE_NOT_FOUND", "params": {"save_id": sid}}
    for method, path in [
        ("get", f"{SAVES}/{sid}"),
        ("get", f"{SAVES}/{sid}/export"),
        ("get", f"{SAVES}/{sid}/market"),
        ("get", f"{SAVES}/{sid}/market/600036"),
        ("get", f"{SAVES}/{sid}/portfolio"),
        ("get", f"{SAVES}/{sid}/trades"),
        ("get", f"{SAVES}/{sid}/achievements"),
        ("post", f"{SAVES}/{sid}/clock/pause"),
        ("post", f"{SAVES}/{sid}/orders"),
        ("put", f"{SAVES}/{sid}/watchlist/600036"),
    ]:
        kwargs = (
            {"json": {"code": "600036", "side": "buy", "quantity": 100}}
            if path.endswith("orders")
            else {}
        )
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 404, (method, path, resp.text)
        assert resp.json() == not_found
    assert client.patch(f"{SAVES}/{sid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"{SAVES}/{sid}").status_code == 404
    assert client.get(SAVES).json() == []


def test_rename_and_delete_save(registered_client: TestClient) -> None:
    save = _create(registered_client)
    resp = registered_client.patch(f"{SAVES}/{save['id']}", json={"name": "新名字"})
    assert resp.status_code == 200 and resp.json()["name"] == "新名字"
    assert registered_client.delete(f"{SAVES}/{save['id']}").status_code == 204
    assert registered_client.get(f"{SAVES}/{save['id']}").status_code == 404


def test_export_contains_versioned_snapshot(registered_client: TestClient) -> None:
    save = _create(registered_client)
    resp = registered_client.get(f"{SAVES}/{save['id']}/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.json()
    assert body["format"] == "stocksim-save" and body["format_version"] == 2
    assert body["save"]["id"] == save["id"]
    assert body["save"]["market_seed"].isdigit()
    assert body["trades"] == [] and body["holdings"] == []


def test_stock_pool_is_seeded_idempotently(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Stock)) == 385
        assert seed_stock_table(db) == 0
        assert db.scalar(select(func.count()).select_from(Stock)) == 385


def test_stocks_endpoint_lists_pool(registered_client: TestClient) -> None:
    resp = registered_client.get("/api/v1/stocks")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 385
    assert len({item["code"] for item in items}) == 385
    assert {"code", "name", "industry"} <= set(items[0])


def test_achievement_catalog_endpoint(registered_client: TestClient) -> None:
    resp = registered_client.get("/api/v1/achievements/catalog")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert len(ids) == len(set(ids)) > 0
    assert all({"id", "level", "category", "hidden"} <= set(item) for item in resp.json())


def test_clock_pause_resume_and_skip(registered_client: TestClient, app: FastAPI) -> None:
    save = _create(registered_client)
    sid = save["id"]
    _set_save(app, sid, clock_minute=570)  # 9:30 开盘

    paused = registered_client.post(f"{SAVES}/{sid}/clock/pause")
    assert paused.status_code == 200 and paused.json()["paused"] is True
    resumed = registered_client.post(f"{SAVES}/{sid}/clock/resume")
    assert resumed.status_code == 200 and resumed.json()["paused"] is False

    before = registered_client.get(f"{SAVES}/{sid}").json()["tick"]
    skipped = registered_client.post(f"{SAVES}/{sid}/clock/skip").json()
    # 上午盘 9:30 -> 11:29，共 119 个分钟 tick
    assert skipped["skipped_ticks"] == 119
    assert skipped["clock_minute"] == 689
    assert skipped["tick"] == before + 119


def test_fee_rates_round_trip_as_decimal_strings(registered_client: TestClient) -> None:
    save = _create(registered_client, buy_fee_rate="0.00035", sell_fee_rate=0.001)
    assert Decimal(save["buy_fee_rate"]) == Decimal("0.00035")
    assert Decimal(save["sell_fee_rate"]) == Decimal("0.001")


def test_events_flag_defaults_off_and_is_set_on_create(registered_client: TestClient) -> None:
    client = registered_client
    assert _create(client)["events_enabled"] is False
    resp = client.post(SAVES, json={"name": "事件", "events_enabled": True, "clock_rules": 2})
    assert resp.status_code == 201
    body = resp.json()
    assert body["events_enabled"] is True
    assert client.get(f"{SAVES}/{body['id']}").json()["events_enabled"] is True


def test_export_of_event_save_hides_seed_and_bumps_format(registered_client: TestClient) -> None:
    client = registered_client
    created = client.post(SAVES, json={"name": "事件", "events_enabled": True, "clock_rules": 2})
    sid = created.json()["id"]
    body = client.get(f"{SAVES}/{sid}/export").json()
    assert body["format_version"] == 2
    assert body["save"]["events_enabled"] is True
    assert body["save"]["events_ruleset"] == 1
    assert body["save"]["market_seed"] is None
    assert body["save"]["clock_rules"] == "v2"
    closed = _create(client)
    closed_body = client.get(f"{SAVES}/{closed['id']}/export").json()
    assert closed_body["save"]["events_enabled"] is False
    assert closed_body["save"]["events_ruleset"] == 0
    assert closed_body["save"]["market_seed"].isdigit()
