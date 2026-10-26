"""决策 16：复盘存档不提供产业链；能取到产业链或真实代码的事件接口对复盘存档一律拒绝。

- `/supply-chain` → 409 `REPLAY_UNSUPPORTED {feature:"supply_chain"}`。
- `/news`、`/events`、`/events/{id}`、`/market/{code}/event-marks`、`/intel`、情报卡购买与传闻提示
  → 409 `EVENTS_DISABLED`（复盘存档 `events_enabled=false`，入口守卫即拒绝）。
- 响应中不含夹具关卡的真实代码与名称。普通 / 事件存档的行为不变。
"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_support import (
    ALIAS,
    REAL,
    REAL_NAMES,
    advance,
    build_app,
    create_session,
    register,
)

API = "/api/v1"
SUPPLY_CHAIN_REJECTED = {"code": "REPLAY_UNSUPPORTED", "params": {"feature": "supply_chain"}}

# (方法, 路径后缀, 请求体)：复盘存档下全部应被拒绝的事件 / 情报接口
REJECTED_EVENT_CALLS = [
    ("GET", "/news", None),
    ("GET", "/events", None),
    ("GET", "/events/e1-0", None),
    ("GET", f"/market/{ALIAS['s1']}/event-marks", None),
    ("GET", "/intel", None),
    ("POST", "/intel/edges", {"edge_id": "电子>汽车", "level": 1}),
    ("POST", "/intel/rumor-hints", {"event_id": "e1-0"}),
]


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return build_app(tmp_path / "app")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client, "alice")
        yield test_client


def _call(client: TestClient, method: str, url: str, body: dict | None) -> object:
    if method == "GET":
        return client.get(url)
    return client.post(url, json=body)


def _leaks(text: str) -> list[str]:
    return [s for s in (*REAL.values(), *REAL_NAMES) if s in text]


def test_replay_save_is_closed_for_events(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    save = client.get(f"{API}/saves/{sid}").json()
    assert save["mode"] == "replay"
    assert save["events_enabled"] is False


def test_supply_chain_rejected_for_replay(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    resp = client.get(f"{API}/saves/{sid}/supply-chain")
    assert resp.status_code == 409
    assert resp.json() == SUPPLY_CHAIN_REJECTED
    assert _leaks(resp.text) == []


def test_supply_chain_rejected_after_advancing_and_settling(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")
    assert client.get(f"{API}/saves/{sid}/supply-chain").json() == SUPPLY_CHAIN_REJECTED
    assert client.post(f"{API}/replay/sessions/{sid}/finish").status_code == 200
    resp = client.get(f"{API}/saves/{sid}/supply-chain")
    assert resp.status_code == 409
    assert resp.json() == SUPPLY_CHAIN_REJECTED
    assert _leaks(resp.text) == []


@pytest.mark.parametrize(("method", "suffix", "body"), REJECTED_EVENT_CALLS)
def test_event_endpoints_rejected_for_replay(
    client: TestClient, method: str, suffix: str, body: dict | None
) -> None:
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")
    resp = _call(client, method, f"{API}/saves/{sid}{suffix}", body)
    assert resp.status_code == 409, (suffix, resp.text)
    assert resp.json()["code"] == "EVENTS_DISABLED", (suffix, resp.text)
    assert resp.json()["params"] == {"save_id": sid}
    assert _leaks(resp.text) == [], (suffix, resp.text)


def test_no_real_code_in_any_rejected_response(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")
    calls = [("GET", "/supply-chain", None), *REJECTED_EVENT_CALLS]
    for method, suffix, body in calls:
        url = f"{API}/saves/{sid}{suffix}"
        resp = _call(client, method, url, body)
        assert resp.status_code == 409, (url, resp.text)
        assert _leaks(resp.text) == [], (url, resp.text)


def test_normal_and_event_saves_unchanged(client: TestClient) -> None:
    for events in (False, True):
        sid = client.post(
            f"{API}/saves", json={"name": f"普通{events}", "events_enabled": events}
        ).json()["id"]
        body = client.get(f"{API}/saves/{sid}/supply-chain")
        assert body.status_code == 200, body.text
        out = body.json()
        assert len(out["nodes"]) == 82
        assert any(node["leaders"] for node in out["nodes"])
        assert out["edges"] and all(e["strength"] is None for e in out["edges"])
        assert client.get(f"{API}/saves/{sid}/news").status_code == (200 if events else 409)
        assert client.get(f"{API}/saves/{sid}/intel").status_code == (200 if events else 409)


def test_other_user_cannot_reach_replay_supply_chain(client: TestClient, app: FastAPI) -> None:
    sid = create_session(client)["save_id"]
    other = TestClient(app)
    register(other, "bob")
    assert other.get(f"{API}/saves/{sid}/supply-chain").json()["code"] == "SAVE_NOT_FOUND"
