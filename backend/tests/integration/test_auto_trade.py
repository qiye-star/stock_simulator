"""自动交易：条件单 CRUD、启停状态机、事件分页，以及 run_auto_trade 的触发/冷却/上限规则。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from stocksim.models import AutoTradeConfig, AutoTradeEvent, MarketState, Save, Trade
from stocksim.services import auto_trade as auto_service
from stocksim.services.seed import seed_stock_table

PASSWORD = "secret1"
CODE = "600519"  # 贵州茅台（股票池中的普通股）
OTHER = "600036"
MORNING = 600  # 10:00，交易时段内
TICK_DEFAULT = 10


def _api(save_id: str, suffix: str = "") -> str:
    return f"/api/v1/saves/{save_id}/auto-trade{suffix}"


def _config_body(**overrides):
    body = {
        "code": CODE,
        "direction": "buy",
        "condition_type": "price",
        "condition_operator": "above",
        "condition_value_cents": 1_000,
        "quantity": 100,
        "price_type": "market",
    }
    body.update(overrides)
    return body


def _create_save(client: TestClient) -> str:
    resp = client.post("/api/v1/saves", json={"name": "t", "initial_fund_cents": 100_000_000})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _set_price(app: FastAPI, save_id: str, code: str, price: int) -> None:
    """把某只股票的现价（与昨收同值，避免涨跌停/熔断干扰）写入行情快照。"""
    with app.state.session_factory() as db:
        row = db.get(MarketState, uuid.UUID(save_id))
        payload = dict(row.payload)
        raw = list(payload[code])
        raw[0] = raw[1] = price
        raw[2] = raw[3] = raw[4] = price
        raw[8] = 0
        payload[code] = raw
        row.payload = payload
        db.commit()


def _prepare_run(app: FastAPI, save_id: str, *, clock: int = MORNING, tick: int = TICK_DEFAULT):
    """直接设置存档为可交易状态（交易时段、启用自动交易）。"""
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(save_id))
        save.clock_minute = clock
        save.tick = tick
        save.auto_enabled = True
        save.auto_paused = False
        save.paused = False
        db.commit()


def _run(app: FastAPI, save_id: str) -> list[Trade]:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(save_id))
        return auto_service.run_auto_trade(db, save)


def _events(app: FastAPI, save_id: str) -> list[AutoTradeEvent]:
    with app.state.session_factory() as db:
        return list(
            db.scalars(
                select(AutoTradeEvent)
                .where(AutoTradeEvent.save_id == uuid.UUID(save_id))
                .order_by(AutoTradeEvent.created_at, AutoTradeEvent.id)
            )
        )


def _set_tick(app: FastAPI, save_id: str, tick: int) -> None:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(save_id))
        save.tick = tick
        db.commit()


@pytest.fixture
def ctx(registered_client: TestClient, app: FastAPI) -> tuple[TestClient, FastAPI, str]:
    with app.state.session_factory() as db:
        seed_stock_table(db)
    return registered_client, app, _create_save(registered_client)


# ---------------------------------------------------------------- 配置 CRUD


def test_config_crud_roundtrip(ctx) -> None:
    client, _, save_id = ctx
    created = client.post(_api(save_id, "/configs"), json=_config_body())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == CODE and body["name"] and body["quantity"] == 100

    listed = client.get(_api(save_id, "/configs")).json()["items"]
    assert [c["id"] for c in listed] == [body["id"]]

    updated = client.put(
        _api(save_id, f"/configs/{body['id']}"),
        json=_config_body(quantity=200, enabled=False),
    )
    assert updated.status_code == 200 and updated.json()["quantity"] == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete(_api(save_id, f"/configs/{body['id']}"))
    assert deleted.status_code == 204
    assert client.get(_api(save_id, "/configs")).json()["items"] == []


def test_duplicate_code_and_direction_conflicts(ctx) -> None:
    client, _, save_id = ctx
    assert client.post(_api(save_id, "/configs"), json=_config_body()).status_code == 201
    resp = client.post(_api(save_id, "/configs"), json=_config_body(condition_value_cents=5))
    assert resp.status_code == 409
    assert resp.json()["code"] == "AUTO_CONFIG_DUPLICATE"
    # 同一股票的反方向是另一条配置
    other_dir = _config_body(direction="sell", condition_type="time", condition_operator=None)
    other_dir.pop("condition_value_cents")
    assert client.post(_api(save_id, "/configs"), json=other_dir).status_code == 201


def test_unknown_stock_is_rejected(ctx) -> None:
    client, _, save_id = ctx
    resp = client.post(_api(save_id, "/configs"), json=_config_body(code="000001"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "STOCK_NOT_FOUND"


def test_unknown_config_id_is_404_auto_config_not_found(ctx) -> None:
    client, _, save_id = ctx
    missing = str(uuid.uuid4())
    put = client.put(_api(save_id, f"/configs/{missing}"), json=_config_body())
    assert put.status_code == 404
    assert put.json()["code"] == "AUTO_CONFIG_NOT_FOUND"
    delete = client.delete(_api(save_id, f"/configs/{missing}"))
    assert delete.status_code == 404
    assert delete.json()["code"] == "AUTO_CONFIG_NOT_FOUND"


def test_profit_condition_only_for_sell(ctx) -> None:
    client, _, save_id = ctx
    body = _config_body(condition_type="profit", condition_value_cents=10_000)
    resp = client.post(_api(save_id, "/configs"), json=body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_limit_order_requires_limit_price(ctx) -> None:
    client, _, save_id = ctx
    resp = client.post(_api(save_id, "/configs"), json=_config_body(price_type="limit"))
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_percentage_is_stored_as_basis_points(ctx) -> None:
    client, app, save_id = ctx
    body = _config_body(
        condition_type="percentage",
        condition_value_cents=None,
        condition_percent=2.5,
        stop_loss_percent=5,
    )
    resp = client.post(_api(save_id, "/configs"), json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["condition_percent"] == 2.5
    with app.state.session_factory() as db:
        row = db.scalar(
            select(AutoTradeConfig).where(AutoTradeConfig.id == uuid.UUID(resp.json()["id"]))
        )
        assert row.condition_pct100 == 250
        assert row.stop_loss_pct100 == 500


def test_other_user_cannot_touch_save(ctx, app: FastAPI) -> None:
    _, _, save_id = ctx
    bob = TestClient(app)
    assert (
        bob.post(
            "/api/v1/auth/register", json={"username": "bob", "password": PASSWORD}
        ).status_code
        == 201
    )
    resp = bob.get(_api(save_id, "/configs"))
    assert resp.status_code == 404
    assert resp.json()["code"] == "SAVE_NOT_FOUND"


def test_unauthenticated_request_is_rejected(ctx, app: FastAPI) -> None:
    _, _, save_id = ctx
    resp = TestClient(app).get(_api(save_id, "/configs"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------- 启停状态机


def test_start_pause_resume_stop_flags(ctx) -> None:
    client, _, save_id = ctx
    assert client.post(_api(save_id, "/start")).json()["enabled"] is True
    paused = client.post(_api(save_id, "/pause")).json()
    assert paused["enabled"] is True and paused["paused"] is True
    resumed = client.post(_api(save_id, "/resume")).json()
    assert resumed["paused"] is False
    stopped = client.post(_api(save_id, "/stop")).json()
    assert stopped["enabled"] is False and stopped["paused"] is False


def test_reset_clears_configs_events_and_stops(ctx) -> None:
    client, app, save_id = ctx
    client.post(_api(save_id, "/configs"), json=_config_body())
    client.post(_api(save_id, "/start"))
    with app.state.session_factory() as db:
        db.add(
            AutoTradeEvent(
                id=uuid.uuid4(),
                save_id=uuid.UUID(save_id),
                stock_code=CODE,
                direction="buy",
                condition_type="price",
                success=False,
                message="TRADE_INSUFFICIENT_FUNDS",
                tick=1,
                trading_day=0,
            )
        )
        db.commit()
    status = client.post(_api(save_id, "/reset")).json()
    assert status["enabled"] is False
    assert client.get(_api(save_id, "/configs")).json()["items"] == []
    assert client.get(_api(save_id, "/events")).json()["items"] == []


# ---------------------------------------------------------------- 事件分页


def test_events_are_paged_newest_first(ctx) -> None:
    client, app, save_id = ctx
    base = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)
    with app.state.session_factory() as db:
        for i in range(5):
            db.add(
                AutoTradeEvent(
                    id=uuid.uuid4(),
                    save_id=uuid.UUID(save_id),
                    stock_code=CODE,
                    direction="buy",
                    condition_type="price",
                    success=i % 2 == 0,
                    message="" if i % 2 == 0 else "TRADE_INSUFFICIENT_FUNDS",
                    tick=i,
                    trading_day=0,
                    created_at=base + timedelta(seconds=i),
                )
            )
        db.commit()
    page1 = client.get(_api(save_id, "/events"), params={"limit": 2}).json()
    assert [e["tick"] for e in page1["items"]] == [4, 3]
    assert page1["items"][0]["success"] is True
    assert page1["items"][1]["reason_code"] == "TRADE_INSUFFICIENT_FUNDS"
    page2 = client.get(
        _api(save_id, "/events"), params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    assert [e["tick"] for e in page2["items"]] == [2, 1]
    page3 = client.get(
        _api(save_id, "/events"), params={"limit": 2, "cursor": page2["next_cursor"]}
    ).json()
    assert [e["tick"] for e in page3["items"]] == [0]
    assert page3["next_cursor"] is None


def test_bad_cursor_is_validation_error(ctx) -> None:
    client, _, save_id = ctx
    resp = client.get(_api(save_id, "/events"), params={"cursor": "%%%"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 评估与执行


def test_price_condition_executes_auto_buy(ctx) -> None:
    client, app, save_id = ctx
    cfg = client.post(
        _api(save_id, "/configs"), json=_config_body(condition_value_cents=1_000)
    ).json()
    _set_price(app, save_id, CODE, 20_000)
    _prepare_run(app, save_id)

    trades = _run(app, save_id)
    assert len(trades) == 1
    assert trades[0].source == "auto"
    assert trades[0].auto_config_id == uuid.UUID(cfg["id"])
    assert trades[0].quantity == 100

    events = _events(app, save_id)
    assert [e.success for e in events] == [True]
    assert events[0].amount_cents == trades[0].cash_delta_cents
    assert events[0].message == ""


def test_cooldown_blocks_repeat_within_two_ticks(ctx) -> None:
    client, app, save_id = ctx
    client.post(_api(save_id, "/configs"), json=_config_body(condition_value_cents=1_000))
    _set_price(app, save_id, CODE, 20_000)
    _prepare_run(app, save_id, tick=10)
    assert len(_run(app, save_id)) == 1

    _set_tick(app, save_id, 11)
    assert _run(app, save_id) == []  # 冷却 2 tick 内不再尝试
    _set_tick(app, save_id, 12)
    assert len(_run(app, save_id)) == 1  # 冷却结束，再次成交


def test_no_run_outside_trading_hours_or_when_paused(ctx) -> None:
    client, app, save_id = ctx
    client.post(_api(save_id, "/configs"), json=_config_body(condition_value_cents=1_000))
    _set_price(app, save_id, CODE, 20_000)

    _prepare_run(app, save_id, clock=12 * 60)  # 午休，非交易时段
    assert _run(app, save_id) == []

    _prepare_run(app, save_id)
    client.post(_api(save_id, "/pause"))
    assert _run(app, save_id) == []

    client.post(_api(save_id, "/resume"))
    client.post(_api(save_id, "/stop"))
    assert _run(app, save_id) == []
    assert _events(app, save_id) == []


def test_config_max_trades_counts_successes_only(ctx) -> None:
    client, app, save_id = ctx
    client.post(
        _api(save_id, "/configs"),
        json=_config_body(condition_value_cents=1_000, max_trades=1),
    )
    _set_price(app, save_id, CODE, 20_000)
    _prepare_run(app, save_id, tick=10)
    assert len(_run(app, save_id)) == 1
    _set_tick(app, save_id, 12)
    assert _run(app, save_id) == []
    reasons = [e.message for e in _events(app, save_id) if not e.success]
    assert reasons == ["AUTO_LIMIT_REACHED"]


def test_global_limit_stops_further_trades(ctx) -> None:
    client, app, save_id = ctx
    client.post(_api(save_id, "/configs"), json=_config_body(condition_value_cents=1_000))
    client.post(
        _api(save_id, "/configs"), json=_config_body(code=OTHER, condition_value_cents=1_000)
    )
    _set_price(app, save_id, CODE, 20_000)
    _set_price(app, save_id, OTHER, 20_000)
    with app.state.session_factory() as db:
        db.get(Save, uuid.UUID(save_id)).auto_max_total_trades = 1
        db.commit()
    _prepare_run(app, save_id)
    assert len(_run(app, save_id)) == 1
    events = _events(app, save_id)
    assert [e.success for e in events] == [True, False]
    assert events[1].message == "AUTO_LIMIT_REACHED"


def test_max_amount_is_enforced_as_event(ctx) -> None:
    client, app, save_id = ctx
    client.post(
        _api(save_id, "/configs"),
        json=_config_body(condition_value_cents=1_000, max_amount_cents=1_000_000),
    )
    _set_price(app, save_id, CODE, 20_000)  # 20000 * 100 = 2,000,000 > 1,000,000
    _prepare_run(app, save_id)
    assert _run(app, save_id) == []
    events = _events(app, save_id)
    assert len(events) == 1 and events[0].message == "AUTO_MAX_AMOUNT_EXCEEDED"


def test_place_order_failure_is_recorded_with_code(ctx) -> None:
    client, app, save_id = ctx
    client.post(
        _api(save_id, "/configs"), json=_config_body(condition_value_cents=1_000, quantity=100)
    )
    _set_price(app, save_id, CODE, 20_000)
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(save_id))
        save.cash_cents = 1_000  # 资金不足
        db.commit()
    _prepare_run(app, save_id)
    assert _run(app, save_id) == []
    events = _events(app, save_id)
    assert [e.message for e in events] == ["TRADE_INSUFFICIENT_FUNDS"]
    assert events[0].success is False
