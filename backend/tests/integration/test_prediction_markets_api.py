"""预测市场 REST 集成测试（04 §9）：HTTP 形状、状态码、错误码、保密、调试守门。

时间由 fake_clock 控制；账户经 HTTP 登录，积分经服务层补足。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.models import Challenge, PredictionMarket
from stocksim.services import auth as auth_service
from stocksim.services import pm_lifecycle
from stocksim.services import points as points_service
from stocksim.services.challenges import generate, registry

API = "/api/v1"
PASSWORD = "secret1"


def _challenge(db: Session, fake_clock) -> Challenge:
    return generate.ensure_challenge(db, date(2026, 10, 26), now=fake_clock.value)


def _markets(db: Session, ch: Challenge) -> list[PredictionMarket]:
    return list(
        db.scalars(
            select(PredictionMarket)
            .where(PredictionMarket.challenge_id == ch.id)
            .order_by(PredictionMarket.open_tt, PredictionMarket.event_id, PredictionMarket.kind)
        )
    )


def _at(db: Session, fake_clock, ch: Challenge, tt: int) -> None:
    info = registry.get_challenge(db, ch.id)
    fake_clock.value = registry.real_time_of(info, tt)


def _login(app: FastAPI, db: Session, name: str, *, funded: bool = True) -> TestClient:
    user = auth_service.register(db, name, PASSWORD)
    user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db.commit()
    if funded:
        points_service.credit(
            db,
            user_id=user.id,
            delta=10_000,
            reason="admin_adjust",
            ref=f"test:{name}",
            idempotency_key=f"admin_adjust:api-{name}",
        )
        db.commit()
    client = TestClient(app)
    resp = client.post(f"{API}/auth/login", json={"username": name, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client


def _keys(obj, acc: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def test_requires_login(challenge_app: FastAPI) -> None:
    client = TestClient(challenge_app)
    resp = client.get(f"{API}/prediction-markets")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


def test_list_detail_and_quote_flow(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    first = markets[0]
    _at(db, fake_clock, ch, first.open_tt)
    pm_lifecycle.sync_market(db, first.id)
    client = _login(challenge_app, db, "api_a")

    resp = client.get(f"{API}/prediction-markets", params={"challenge_id": str(ch.id)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [m["id"] for m in body["items"]] == [str(first.id)]
    assert body["public"]["challenge_id"] == str(ch.id)
    # 保密：不出现隐藏字段；scheduled 市场不出现
    names = _keys(body, set())
    for hidden in ("event_fingerprint", "magnitude_ppm", "knots", "impacts", "truth", "seed"):
        assert hidden not in names
    item = body["items"][0]
    assert item["status"] == "open" and item["my_shares"] is None
    if item["kind"] == "rumor":
        assert item["close_tt"] is None and item["resolve_tt"] is None

    detail = client.get(f"{API}/prediction-markets/{first.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["balance_points"] == 10_000 + 200

    q = client.get(
        f"{API}/prediction-markets/{first.id}/quote",
        params={"side": "buy", "outcome": 0, "shares": 2},
    )
    assert q.status_code == 200, q.text
    assert q.json()["shares"] == 2 and q.json()["points"] > 0

    sell = client.get(
        f"{API}/prediction-markets/{first.id}/quote",
        params={"side": "sell", "outcome": 0, "shares": 1},
    )
    assert sell.status_code == 422 and sell.json()["code"] == "PM_INSUFFICIENT_SHARES"

    missing = client.get(f"{API}/prediction-markets/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json()["code"] == "PM_NOT_FOUND"

    scheduled = next((m for m in markets if m.status == "scheduled"), None)
    if scheduled is not None:
        resp = client.get(f"{API}/prediction-markets/{scheduled.id}")
        assert resp.status_code == 404 and resp.json()["code"] == "PM_NOT_FOUND"


def test_trade_201_then_200_replay(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    client = _login(challenge_app, db, "api_b")
    payload = {"side": "buy", "outcome": 1, "shares": 2}
    headers = {"Idempotency-Key": "api-key-1"}
    first = client.post(f"{API}/prediction-markets/{m.id}/trades", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["replayed"] is False
    again = client.post(f"{API}/prediction-markets/{m.id}/trades", json=payload, headers=headers)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["trade"]["id"] == first.json()["trade"]["id"]
    my = client.get(f"{API}/prediction-markets/{m.id}").json()["my"]
    assert my["outcomes"][0]["shares"] == 2


def test_trade_requires_idempotency_key_and_rejects_extra_fields(
    challenge_app, db, fake_clock
) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    client = _login(challenge_app, db, "api_c")
    no_key = client.post(
        f"{API}/prediction-markets/{m.id}/trades", json={"side": "buy", "outcome": 0, "shares": 1}
    )
    assert no_key.status_code == 422
    extra = client.post(
        f"{API}/prediction-markets/{m.id}/trades",
        json={"side": "buy", "outcome": 0, "shares": 1, "user_id": "x"},
        headers={"Idempotency-Key": "k-extra"},
    )
    assert extra.status_code == 422
    too_many = client.post(
        f"{API}/prediction-markets/{m.id}/trades",
        json={"side": "buy", "outcome": 0, "shares": 201},
        headers={"Idempotency-Key": "k-big"},
    )
    assert too_many.status_code == 422


def test_settlements_and_positions_endpoints(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    client = _login(challenge_app, db, "api_d")
    client.post(
        f"{API}/prediction-markets/{m.id}/trades",
        json={"side": "buy", "outcome": 0, "shares": 1},
        headers={"Idempotency-Key": "k-settle"},
    )
    _at(db, fake_clock, ch, m.close_tt)
    pm_lifecycle.sync_market(db, m.id)
    _at(db, fake_clock, ch, m.resolve_tt)
    pm_lifecycle.sync_market(db, m.id)
    active = client.get(f"{API}/me/prediction-positions", params={"status": "active"})
    assert active.status_code == 200 and active.json()["items"] == []
    settled = client.get(f"{API}/me/prediction-positions", params={"status": "settled"})
    assert settled.status_code == 200
    assert [x["market"]["id"] for x in settled.json()["items"]] == [str(m.id)]
    records = client.get(f"{API}/me/prediction-settlements")
    assert records.status_code == 200
    assert len(records.json()["items"]) == 1
    assert records.json()["items"][0]["kind"] == "resolved"


def test_history_and_tape_endpoints(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    client = _login(challenge_app, db, "api_e")
    client.post(
        f"{API}/prediction-markets/{m.id}/trades",
        json={"side": "buy", "outcome": 0, "shares": 1},
        headers={"Idempotency-Key": "k-hist"},
    )
    hist = client.get(f"{API}/prediction-markets/{m.id}/history", params={"max_points": 10})
    assert hist.status_code == 200
    assert hist.json()["items"][0]["seq"] == 0
    bad = client.get(f"{API}/prediction-markets/{m.id}/history", params={"max_points": 5})
    assert bad.status_code == 422
    tape = client.get(f"{API}/prediction-markets/{m.id}/trades")
    assert tape.status_code == 200
    assert "user_id" not in tape.json()["items"][0]


def test_debug_routes_are_guarded(challenge_app_factory, db, fake_clock) -> None:
    # compact 调度要求调试接口开启，关闭调试时用 daily 调度
    app = challenge_app_factory("debug_off", ENABLE_DEBUG_API=False, CHALLENGE_SCHEDULE="daily")
    client = TestClient(app)
    resp = client.post(f"{API}/debug/prediction-markets/sync")
    assert resp.status_code == 403 and resp.json()["code"] == "DEBUG_DISABLED"


def test_debug_sync_and_void(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    _at(db, fake_clock, ch, min(m.open_tt for m in markets))
    client = _login(challenge_app, db, "api_f")
    sync = client.post(f"{API}/debug/prediction-markets/sync")
    assert sync.status_code == 200 and sync.json()["changed"] >= 1
    target = markets[0]
    db.refresh(target)
    voided = client.post(f"{API}/debug/prediction-markets/{target.id}/void", json={"reason": "ops"})
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided" and voided.json()["void_reason"] == "ops"
