"""真实复盘：建会话、逐阶段推进的防剧透断言、预测截止与停止原因、结算后拒绝（05 §8.2）。"""

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
    SLUG,
    advance,
    answer,
    build_app,
    create_session,
    load_fixture,
    register,
    session_state,
)

from stocksim.domain.replay import event_visible, phase_tick

API = "/api/v1"
PHASES = ("pre_open", "open", "close", "post_close")
PLAY_DAYS = 6
Q1_PROBS = [10, 20, 40, 20, 10]  # 方向题 5 档
Q2_ORDER = [ALIAS["s2"], ALIAS["s3"], ALIAS["s1"]]


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return build_app(tmp_path / "app")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client, "alice")
        yield test_client


def _saves(client: TestClient) -> list[dict]:
    return client.get(f"{API}/saves").json()


def test_create_session_is_replay_save_and_hidden_from_saves(
    client: TestClient, app: FastAPI
) -> None:
    created = create_session(client)
    sid = created["save_id"]
    assert created["status"] == "active"
    assert created["masked"] is True
    assert created["phase"] == "pre_open"
    assert created["day_idx"] == 0
    assert created["tick"] == 0
    assert created["date_label"] == "T+0"
    assert created["cash_cents"] == 100_000_000
    assert created["level"]["title"] == "某个周末的监管政策"

    # 复盘存档不进普通存档列表，但进复盘会话列表
    assert _saves(client) == []
    listed = client.get(f"{API}/replay/sessions").json()["items"]
    assert [item["save_id"] for item in listed] == [sid]

    save = client.get(f"{API}/saves/{sid}").json()
    assert save["mode"] == "replay"
    assert save["clock_rules"] == "v1"
    assert save["events_enabled"] is False
    assert save["paused"] is True


def test_session_limit_is_separate_from_normal_saves(tmp_path: Path) -> None:
    app = build_app(tmp_path / "app", MAX_REPLAY_SESSIONS_PER_USER=2)
    with TestClient(app) as client:
        register(client)
        create_session(client)
        create_session(client)
        resp = client.post(f"{API}/replay/sessions", json={"level_slug": SLUG, "masked": True})
        assert resp.status_code == 409
        assert resp.json() == {
            "code": "SAVE_LIMIT_REACHED",
            "params": {"limit": 2, "mode": "replay"},
        }
        # 普通存档的上限不受复盘会话影响
        assert (
            client.post(f"{API}/saves", json={"name": "普通", "clock_rules": 1}).status_code == 201
        )


def test_other_users_and_normal_saves_are_not_found(client: TestClient, app: FastAPI) -> None:
    sid = create_session(client)["save_id"]
    normal = client.post(f"{API}/saves", json={"name": "普通", "clock_rules": 1}).json()["id"]
    assert client.get(f"{API}/replay/sessions/{normal}").json()["code"] == "SAVE_NOT_FOUND"
    assert (
        client.get(f"{API}/replay/sessions/{normal}/questions").json()["code"] == "SAVE_NOT_FOUND"
    )

    other = TestClient(app)
    register(other, "bob")
    assert other.get(f"{API}/replay/sessions/{sid}").json()["code"] == "SAVE_NOT_FOUND"
    assert (
        other.post(f"{API}/replay/sessions/{sid}/advance", json={"expected_tick": 0}).json()["code"]
        == "SAVE_NOT_FOUND"
    )


def _expected_visible_events(day: int, phase: str) -> set[str]:
    """预期可见事件（匿名）：domain 的可见性 + 回看窗口 + 去掉 hide_in_masked。"""
    out = set()
    for e in load_fixture()["events"]:
        if e["hide_in_masked"]:
            continue
        if e["day_idx"] < -10 and e["importance"] < 3:
            continue
        if event_visible(e["day_idx"], e["slot"], day, phase):
            out.add(f"replay:{e['id']}")
    return out


def _check_invariants(client: TestClient, sid: str, state: dict) -> None:
    day, phase = state["day_idx"], state["phase"]
    pos = phase_tick(day, phase)
    # K 线：只到已过的日子；pre_open 不含当日
    candles = client.get(f"{API}/saves/{sid}/market/{ALIAS['s1']}").json()["candles"]
    days = [c["trading_day"] for c in candles]
    assert max(days) <= day
    if phase == "pre_open":
        assert day not in days
    if phase == "open":
        today = candles[-1]
        assert today["trading_day"] == day
        assert today["open_cents"] == today["high_cents"] == today["low_cents"]
        assert today["volume"] == 0
    # 快讯：只含应可见的事件
    feed = client.get(f"{API}/replay/sessions/{sid}/feed", params={"limit": 100}).json()["items"]
    shown = {item["news_id"] for item in feed}
    assert shown == _expected_visible_events(day, phase)
    assert all(
        item["title"] in {e["title_masked"] for e in load_fixture()["events"]} for item in feed
    )
    # 基准：不越界
    bench_days = [
        p["trading_day"]
        for p in client.get(f"{API}/replay/sessions/{sid}/benchmark").json()["points"]
    ]
    assert max(bench_days) <= (day if phase in ("close", "post_close") else day - 1)
    # 题目：只有已开放的
    for q in client.get(f"{API}/replay/sessions/{sid}/questions").json()["items"]:
        assert phase_tick(q["opens"]["day_idx"], q["opens"]["phase"]) <= pos
    # 匿名：响应里不出现真实代码与真实名称
    body = client.get(f"{API}/replay/sessions/{sid}").text
    body += client.get(f"/api/v1/saves/{sid}/market").text
    for leaked in (*REAL.values(), *REAL_NAMES):
        assert leaked not in body


def test_full_game_step_by_step_no_leak_and_settles(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    state = session_state(client, sid)
    steps = 0
    while state["status"] == "active":
        _check_invariants(client, sid, state)
        if (state["day_idx"], state["phase"]) == (1, "pre_open"):
            # 第 1 日盘前：题目截止，必须先作答，否则 next_phase 被拒
            pending = advance(client, sid, expected_tick=state["tick"])
            assert pending.status_code == 409
            assert pending.json()["code"] == "REPLAY_PREDICTION_PENDING"
            assert pending.json()["params"]["question_ids"] == ["q1", "q2"]
            assert answer(client, sid, "q1", {"probs": Q1_PROBS}).status_code == 200
            resp = answer(client, sid, "q2", {"order": Q2_ORDER})
            assert resp.status_code == 200
            assert resp.json()["status"] == "answered"
        resp = advance(client, sid, expected_tick=state["tick"])
        assert resp.status_code == 200, resp.text
        out = resp.json()
        assert out["stale"] is False
        state = out["session"]
        steps += 1
        assert steps < 40, "game did not terminate"
    assert state["status"] == "settled"
    assert state["settled"] is not None
    assert state["settled"]["final_equity_cents"] > 0
    # 结算后推进被拒
    again = advance(client, sid, expected_tick=state["tick"])
    assert again.status_code == 409
    assert again.json()["code"] == "REPLAY_SESSION_SETTLED"


def test_stale_expected_tick_does_not_advance(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    out = advance(client, sid, expected_tick=99).json()
    assert out["stale"] is True
    assert out["session"]["tick"] == 0
    assert out["session"]["phase"] == "pre_open"


def test_next_day_stops_when_question_opens(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    out = advance(client, sid, expected_tick=0, to="next_day").json()
    assert out["stopped_reason"] == "question_open"
    assert (out["session"]["day_idx"], out["session"]["phase"]) == (1, "pre_open")
    assert out["session"]["open_question_ids"] == ["q1", "q2"]
    # 盘前有未答题：next_day 不推进，只提示 question_due
    again = advance(client, sid, expected_tick=out["session"]["tick"], to="next_day").json()
    assert again["stopped_reason"] == "question_due"
    assert again["session"]["tick"] == out["session"]["tick"]


def test_skip_pending_scores_zero_and_continues(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    state = advance(client, sid, expected_tick=0, to="next_day").json()["session"]
    out = advance(client, sid, expected_tick=state["tick"], skip_pending=True).json()
    assert out["stale"] is False
    assert sorted(out["scored_question_ids"]) == ["q1", "q2"]
    assert out["session"]["phase"] == "open"
    rows = client.get(f"{API}/replay/sessions/{sid}/questions").json()["items"]
    assert {r["status"] for r in rows} == {"skipped"}
    assert all(r["result"]["score"] == 0 and r["result"]["points"] == 0 for r in rows)


def test_finish_settles_early_and_reveal_locked_until_then(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    locked = client.get(f"{API}/replay/sessions/{sid}/reveal")
    assert locked.status_code == 409
    assert locked.json()["code"] == "REPLAY_REVEAL_LOCKED"

    resp = client.post(f"{API}/replay/sessions/{sid}/finish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "settled"
    assert resp.json()["settled"]["final_equity_cents"] == 100_000_000
    assert resp.json()["settled"]["return_bp"] == 0
    assert (
        client.post(f"{API}/replay/sessions/{sid}/finish").json()["code"]
        == "REPLAY_SESSION_SETTLED"
    )
    assert client.get(f"{API}/replay/sessions/{sid}/reveal").status_code == 200


def test_feed_cursor_pages_newest_first(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")
    first = client.get(f"{API}/replay/sessions/{sid}/feed", params={"limit": 3}).json()
    assert len(first["items"]) == 3
    assert first["next_cursor"] is not None
    second = client.get(
        f"{API}/replay/sessions/{sid}/feed",
        params={"limit": 3, "cursor": first["next_cursor"]},
    ).json()
    ids_first = {i["news_id"] for i in first["items"]}
    ids_second = {i["news_id"] for i in second["items"]}
    assert ids_first.isdisjoint(ids_second)
    assert (
        client.get(f"{API}/replay/sessions/{sid}/feed", params={"cursor": "x"}).json()["code"]
        == "VALIDATION_ERROR"
    )
