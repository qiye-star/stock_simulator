"""情报卡（02 §7、§13.2）：L1/L2 扣费与补差价、max_level、未知边不扣费、日限额、按用户揭示。"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.services import points
from stocksim.services import predictions as pred_service

SAVES = "/api/v1/saves"


@pytest.fixture(autouse=True)
def _policies():
    pred_service.clear_card_policies()
    yield
    pred_service.clear_card_policies()


def _event_save(client: TestClient) -> str:
    resp = client.post(SAVES, json={"name": "intel", "events_enabled": True, "clock_rules": 2})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _edges(client: TestClient, sid: str) -> list[str]:
    resp = client.get(f"{SAVES}/{sid}/supply-chain")
    assert resp.status_code == 200, resp.text
    return [e["id"] for e in resp.json()["edges"]]


def _top_up(app: FastAPI, client: TestClient, amount: int, key: str) -> None:
    uid = uuid.UUID(client.get("/api/v1/me").json()["id"])
    with app.state.session_factory() as db:
        points.credit(
            db, user_id=uid, delta=amount, reason="admin_adjust", ref="test:topup",
            idempotency_key=f"admin_adjust:{key}",
        )  # fmt: skip
        db.commit()


def _buy_edge(client: TestClient, sid: str, edge_id: str, level: int):
    return client.post(f"{SAVES}/{sid}/intel/edges", json={"edge_id": edge_id, "level": level})


def test_intel_disabled_when_events_off(registered_client: TestClient):
    resp = registered_client.post(SAVES, json={"name": "plain", "events_enabled": False})
    sid = resp.json()["id"]
    resp = registered_client.get(f"{SAVES}/{sid}/intel")
    assert resp.status_code == 409
    assert resp.json()["code"] == "EVENTS_DISABLED"


def test_edge_l1_then_l2_upgrade_charges_difference(registered_client: TestClient):
    sid = _event_save(registered_client)
    edge = _edges(registered_client, sid)[0]
    supply = registered_client.get(f"{SAVES}/{sid}/supply-chain").json()["edges"][0]
    assert supply["revealed_level"] == 0 and supply["strength"] is None

    resp = _buy_edge(registered_client, sid, edge, 1)
    assert resp.status_code == 200, resp.text
    assert resp.json()["charged"] == 100 and resp.json()["balance"] == 100
    assert resp.json()["edge"]["level"] == 1 and resp.json()["edge"]["lag_days"] is None
    after = next(
        e
        for e in registered_client.get(f"{SAVES}/{sid}/supply-chain").json()["edges"]
        if e["id"] == edge
    )
    assert (
        after["revealed_level"] == 1 and after["strength"] is not None and after["lag_days"] is None
    )

    resp = _buy_edge(registered_client, sid, edge, 2)
    assert resp.status_code == 200, resp.text
    assert resp.json()["charged"] == 100 and resp.json()["balance"] == 0
    assert resp.json()["edge"]["lag_days"] is not None

    resp = _buy_edge(registered_client, sid, edge, 2)
    assert resp.status_code == 409
    assert resp.json()["code"] == "INTEL_UNAVAILABLE"
    assert resp.json()["params"] == {"card": "edge", "reason": "max_level"}


def test_unknown_edge_is_404_and_not_charged(registered_client: TestClient):
    sid = _event_save(registered_client)
    resp = _buy_edge(registered_client, sid, "no>such", 1)
    assert resp.status_code == 404
    assert resp.json()["code"] == "SUPPLY_EDGE_NOT_FOUND"
    assert registered_client.get("/api/v1/points").json()["balance"] == 200


def test_insufficient_points_is_422(registered_client: TestClient):
    sid = _event_save(registered_client)
    edges = _edges(registered_client, sid)
    assert _buy_edge(registered_client, sid, edges[0], 1).status_code == 200
    assert _buy_edge(registered_client, sid, edges[1], 1).status_code == 200
    resp = _buy_edge(registered_client, sid, edges[2], 1)
    assert resp.status_code == 422
    assert resp.json()["code"] == "POINTS_INSUFFICIENT"
    assert resp.json()["params"] == {"required": 100, "balance": 0}


def test_daily_limit_is_eight(app: FastAPI, registered_client: TestClient):
    _top_up(app, registered_client, 2000, "limit")
    sid = _event_save(registered_client)
    edges = _edges(registered_client, sid)
    for i in range(8):
        assert _buy_edge(registered_client, sid, edges[i], 1).status_code == 200
    resp = _buy_edge(registered_client, sid, edges[8], 1)
    assert resp.status_code == 409
    assert resp.json()["code"] == "INTEL_LIMIT_REACHED"
    assert resp.json()["params"] == {"limit": 8}
    state = registered_client.get(f"{SAVES}/{sid}/intel").json()
    assert state["used_today"] == 8 and state["daily_limit"] == 8
    assert len(state["edges"]) == 8


def test_state_and_prices(registered_client: TestClient):
    sid = _event_save(registered_client)
    state = registered_client.get(f"{SAVES}/{sid}/intel").json()
    assert state["prices"] == {"edge_l1": 100, "edge_l2": 200, "rumor_hint": 80}
    assert state["edges"] == [] and state["rumor_hints"] == []
    assert state["balance"] == 200 and state["used_today"] == 0


def test_rumor_hint_rejects_non_rumor_and_unknown_events(registered_client: TestClient):
    sid = _event_save(registered_client)
    resp = registered_client.post(f"{SAVES}/{sid}/intel/rumor-hints", json={"event_id": "e999-0"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "EVENT_NOT_FOUND"
    resp = registered_client.post(f"{SAVES}/{sid}/intel/rumor-hints", json={"event_id": "bad"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert registered_client.get("/api/v1/points").json()["balance"] == 200


def test_edge_reveal_is_per_user_not_per_save(registered_client: TestClient):
    sid_a = _event_save(registered_client)
    sid_b = _event_save(registered_client)
    edge = _edges(registered_client, sid_a)[0]
    assert _buy_edge(registered_client, sid_a, edge, 1).status_code == 200
    b_edge = next(
        e
        for e in registered_client.get(f"{SAVES}/{sid_b}/supply-chain").json()["edges"]
        if e["id"] == edge
    )
    assert b_edge["revealed_level"] == 1  # 同一用户的另一存档可见已揭示
