"""行情 WebSocket：/api/v1/ws/saves/{id}。鉴权、归属、首帧全量、增量事件与客户端指令。"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stocksim.models import AutoTradeEvent, SaveAchievement, Trade
from stocksim.services.seed import seed_stock_table

PASSWORD = "secret1"
MAX_FRAMES = 30  # 等待某类消息的上限（防止测试挂起）


def _ws_path(save_id: str) -> str:
    return f"/api/v1/ws/saves/{save_id}"


def _until(ws, predicate, limit: int = MAX_FRAMES) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message not received")


@pytest.fixture
def ctx(registered_client: TestClient, app: FastAPI) -> tuple[TestClient, FastAPI, str]:
    with app.state.session_factory() as db:
        seed_stock_table(db)
    # 刷新周期降到最小值（PATCH /me 允许 500ms）以加快测试
    assert registered_client.patch("/api/v1/me", json={"refresh_rate_ms": 500}).status_code == 200
    resp = registered_client.post(
        "/api/v1/saves", json={"name": "ws", "initial_fund_cents": 100_000_000}
    )
    assert resp.status_code == 201, resp.text
    return registered_client, app, resp.json()["id"]


def test_missing_session_is_rejected_with_close_code(app: FastAPI, ctx) -> None:
    _, _, save_id = ctx
    anon = TestClient(app)
    with anon.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json() == {"t": "error", "code": "AUTH_REQUIRED"}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_other_users_save_is_not_found(app: FastAPI, ctx) -> None:
    _, _, save_id = ctx
    bob = TestClient(app)
    assert (
        bob.post(
            "/api/v1/auth/register", json={"username": "bob", "password": PASSWORD}
        ).status_code
        == 201
    )
    with bob.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json() == {"t": "error", "code": "SAVE_NOT_FOUND"}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4404


def test_first_frame_is_full_and_later_frames_are_deltas(ctx) -> None:
    client, _, save_id = ctx
    with client.websocket_connect(_ws_path(save_id)) as ws:
        first = ws.receive_json()
        assert first["t"] == "tick" and first["full"] is True
        assert set(first["clock"]) == {"minute", "trading_day", "paused", "trading"}
        codes = [row[0] for row in first["q"]]
        assert len(codes) == len(set(codes)) >= 300
        assert all(len(row) == 4 for row in first["q"])


def test_paused_clock_sends_empty_deltas(ctx) -> None:
    client, _, save_id = ctx
    assert client.post(f"/api/v1/saves/{save_id}/clock/pause").status_code == 200
    with client.websocket_connect(_ws_path(save_id)) as ws:
        first = ws.receive_json()
        assert first["full"] is True and first["clock"]["paused"] is True
        assert len(first["q"]) >= 300
        second = ws.receive_json()
        assert second["t"] == "tick" and second["full"] is False
        assert second["advanced"] == 0 and second["q"] == []


def test_ping_and_subscribe_commands(ctx) -> None:
    client, _, save_id = ctx
    with client.websocket_connect(_ws_path(save_id)) as ws:
        ws.receive_json()  # 首帧
        ws.send_json({"t": "ping"})
        assert _until(ws, lambda m: m["t"] == "pong")["t"] == "pong"

        ws.send_json({"t": "subscribe", "code": "600519"})
        assert _until(ws, lambda m: m["t"] == "subscribed")["code"] == "600519"
        frame = _until(ws, lambda m: m["t"] == "tick")
        assert "600519" in [row[0] for row in frame["q"]]  # 订阅的股票每帧都带行情

        ws.send_json({"t": "subscribe", "code": "abc"})
        assert _until(ws, lambda m: m["t"] == "error")["code"] == "VALIDATION_ERROR"

        ws.send_json({"t": "unknown"})
        assert _until(ws, lambda m: m["t"] == "error")["code"] == "VALIDATION_ERROR"


def test_new_trade_is_pushed(ctx) -> None:
    client, app, save_id = ctx
    with client.websocket_connect(_ws_path(save_id)) as ws:
        ws.receive_json()
        with app.state.session_factory() as db:
            db.add(
                Trade(
                    id=uuid.uuid4(),
                    save_id=uuid.UUID(save_id),
                    seq=1,
                    stock_code="600519",
                    side="buy",
                    source="manual",
                    price_type="market",
                    price_cents=100,
                    quantity=10,
                    gross_cents=1000,
                    fee_cents=0,
                    cash_delta_cents=-1000,
                    realized_pnl_cents=0,
                    prev_close_cents=100,
                    tick=0,
                    trading_day=0,
                    clock_minute=600,
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()
        msg = _until(ws, lambda m: m["t"] == "trade")
        assert msg == {"t": "trade", "seq": 1, "count": 1}


def test_new_achievement_is_pushed_once(ctx) -> None:
    client, app, save_id = ctx
    with client.websocket_connect(_ws_path(save_id)) as ws:
        ws.receive_json()
        with app.state.session_factory() as db:
            db.add(
                SaveAchievement(
                    id=uuid.uuid4(),
                    save_id=uuid.UUID(save_id),
                    achievement_id="first_trade",
                    unlocked_at=datetime.now(UTC),
                )
            )
            db.commit()
        assert _until(ws, lambda m: m["t"] == "achievement")["ids"] == ["first_trade"]


def test_auto_event_is_pushed(ctx) -> None:
    client, app, save_id = ctx
    with client.websocket_connect(_ws_path(save_id)) as ws:
        ws.receive_json()
        with app.state.session_factory() as db:
            db.add(
                AutoTradeEvent(
                    id=uuid.uuid4(),
                    save_id=uuid.UUID(save_id),
                    stock_code="600519",
                    direction="buy",
                    condition_type="price",
                    success=False,
                    message="TRADE_INSUFFICIENT_FUNDS",
                    tick=0,
                    trading_day=0,
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()
        msg = _until(ws, lambda m: m["t"] == "auto_event")
        assert msg["count"] == 1
