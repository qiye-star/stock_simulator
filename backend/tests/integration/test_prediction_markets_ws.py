"""预测市场 WebSocket 集成测试（04 §8、§11.2）：鉴权、订阅、成交推送、结算推送、错误帧。

用例开启后台 Hub（PM_BACKGROUND_ENABLED=true，轮询 100 ms），
与 TestClient 的 lifespan 同一事件循环。
时间由 fake_clock 控制；结算由测试线程直接调用生命周期函数推进。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stocksim.models import PredictionMarket
from stocksim.services import auth as auth_service
from stocksim.services import pm_lifecycle
from stocksim.services import points as points_service
from stocksim.services.challenges import generate, registry

API = "/api/v1"
PASSWORD = "secret1"
DAY = date(2026, 10, 26)


def _setup(app: FastAPI, fake_clock) -> dict[str, Any]:
    """建挑战、开第一个分档市场、注册两名用户（积分充足）。返回 id 与时点。"""
    with app.state.session_factory() as db:
        ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
        m = next(
            x
            for x in db.query(PredictionMarket).filter_by(challenge_id=ch.id).all()
            if x.kind == "bucket"
        )
        info = registry.get_challenge(db, ch.id)
        fake_clock.value = registry.real_time_of(info, m.open_tt)
        pm_lifecycle.sync_market(db, m.id)
        for name in ("pm_watch", "pm_trade"):
            user = auth_service.register(db, name, PASSWORD)
            user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            db.commit()
            points_service.credit(
                db,
                user_id=user.id,
                delta=10_000,
                reason="admin_adjust",
                ref=f"test:{name}",
                idempotency_key=f"admin_adjust:ws-{name}",
            )
            db.commit()
        info = registry.get_challenge(db, ch.id)
        return {
            "challenge_id": ch.id,
            "market_id": m.id,
            "close_real": registry.real_time_of(info, m.close_tt),
            "resolve_real": registry.real_time_of(info, m.resolve_tt),
        }


def _login(app: FastAPI, name: str) -> TestClient:
    client = TestClient(app)
    resp = client.post(f"{API}/auth/login", json={"username": name, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client


def _login_on(client: TestClient, name: str) -> None:
    resp = client.post(f"{API}/auth/login", json={"username": name, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _until(ws, pred: Callable[[dict[str, Any]], bool], limit: int = 60) -> dict[str, Any]:
    for _ in range(limit):
        msg = ws.receive_json()
        if pred(msg):
            return msg
    raise AssertionError("expected message not received")


def test_ws_requires_login(challenge_app_factory) -> None:
    app = challenge_app_factory("pm_ws_auth", PM_BACKGROUND_ENABLED=False)
    with TestClient(app) as client, client.websocket_connect(f"{API}/ws/prediction-markets") as ws:
        first = ws.receive_json()
        assert first == {"t": "error", "code": "AUTH_REQUIRED"}
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4401


def test_ws_pushes_trades_resolution_and_errors(challenge_app_factory, fake_clock) -> None:
    app = challenge_app_factory(
        "pm_ws", PM_BACKGROUND_ENABLED=True, PM_POLL_MS=100, PM_SWEEP_MS=600_000
    )
    ids = _setup(app, fake_clock)
    mid = ids["market_id"]
    cid = ids["challenge_id"]
    # 进入上下文即运行 lifespan（启动 Hub）。WS 必须与 Hub 同一事件循环，故关注者用同一个客户端。
    with TestClient(app) as watcher:
        _login_on(watcher, "pm_watch")
        trader = _login(app, "pm_trade")
        with watcher.websocket_connect(f"{API}/ws/prediction-markets") as ws:
            ws.send_json({"t": "ping"})
            assert ws.receive_json() == {"t": "pong"}
            ws.send_json({"t": "watch", "challenge_id": str(cid)})
            ws.send_json({"t": "subscribe", "market_id": str(mid)})
            _until(ws, lambda m: m["t"] == "subscribed" and m["market_id"] == str(mid))

            # 另一用户成交 → 已订阅的市场推送 pm_tick（seq 递增）
            resp = trader.post(
                f"{API}/prediction-markets/{mid}/trades",
                json={"side": "buy", "outcome": 0, "shares": 1},
                headers={"Idempotency-Key": "ws-trade-1"},
            )
            assert resp.status_code == 201, resp.text
            tick = _until(ws, lambda m: m["t"] == "pm_tick" and m["seq"] >= 1)
            assert tick["id"] == str(mid) and tick["status"] == "open"
            assert tick["prices_ppm"] and sum(tick["prices_ppm"]) == 1_000_000
            assert "user_id" not in tick and "positions" not in tick

            # 未知市场 → VALIDATION_ERROR
            ws.send_json({"t": "subscribe", "market_id": str(uuid.uuid4())})
            err = _until(ws, lambda m: m["t"] == "error")
            assert err["code"] == "VALIDATION_ERROR"
            ws.send_json({"t": "bogus"})
            assert _until(ws, lambda m: m["t"] == "error")["code"] == "VALIDATION_ERROR"

            ws.send_json({"t": "unsubscribe", "market_id": str(mid)})
            _until(ws, lambda m: m["t"] == "unsubscribed")

            # 结算：测试线程推进到关市与结算时点，Hub 轮询后推 pm_resolved
            ws.send_json({"t": "subscribe", "market_id": str(mid)})
            _until(ws, lambda m: m["t"] == "subscribed")
            with app.state.session_factory() as db:
                fake_clock.value = ids["close_real"]
                pm_lifecycle.sync_market(db, mid)
                fake_clock.value = ids["resolve_real"]
                pm_lifecycle.sync_market(db, mid)
            resolved = _until(ws, lambda m: m["t"] == "pm_resolved")
            assert resolved["id"] == str(mid) and resolved["status"] == "resolved"
            assert resolved["winning_outcome"] is not None
