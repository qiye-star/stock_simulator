"""真实复盘预测与积分（05 §1.5、§5.6、§8.2 第 8 点）：作答校验、截止、计分等于 domain.scoring。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_support import (
    ALIAS,
    REAL,
    SLUG,
    advance,
    answer,
    build_app,
    create_session,
    load_fixture,
    register,
    session_state,
    user_id,
)

from stocksim.domain.scoring import bucket_of, ndcg_at_k_score, rps_score
from stocksim.models import LedgerEntry, PointAccount, ReplayLevel
from stocksim.services.points import WELCOME_POINTS

API = "/api/v1"
Q1_PROBS = [10, 20, 40, 20, 10]
Q2_ORDER = [ALIAS["s2"], ALIAS["s3"], ALIAS["s1"]]
RAW = load_fixture()
Q1 = next(q for q in RAW["questions"] if q["id"] == "q1")
Q2 = next(q for q in RAW["questions"] if q["id"] == "q2")
EXPECTED_Q1 = rps_score(Q1_PROBS, bucket_of(Q1["answer"]["return_bp"], Q1["edges_bp"]))
EXPECTED_Q2 = ndcg_at_k_score(
    ["s2", "s3", "s1"], {k: int(v) for k, v in Q2["answer"]["relevance"].items()}, k=Q2["top_k"]
)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return build_app(tmp_path / "app")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client, "alice")
        yield test_client


def _play_to_resolution(
    client: TestClient, sid: str, *, masked: bool = True
) -> dict[str, list[str]]:
    """逐步推进到结算，作答两题；返回每一步推进中计分的题目（用于断言计分时点）。"""
    scored_at: dict[str, list[str]] = {}
    for _ in range(40):
        state = session_state(client, sid)
        if state["status"] == "settled":
            break
        if (state["day_idx"], state["phase"]) == (1, "pre_open") and state["pending_question_ids"]:
            assert answer(client, sid, "q1", {"probs": Q1_PROBS}).status_code == 200
            codes = Q2_ORDER if masked else [REAL["s2"], REAL["s3"], REAL["s1"]]
            assert answer(client, sid, "q2", {"order": codes}).status_code == 200
        out = advance(client, sid, expected_tick=state["tick"]).json()
        if out["scored_question_ids"]:
            scored_at[f"{out['session']['day_idx']}-{out['session']['phase']}"] = out[
                "scored_question_ids"
            ]
    return scored_at


def test_answer_validation(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    # 0 日盘前：题目尚未开放
    early = answer(client, sid, "q1", {"probs": Q1_PROBS})
    assert early.json() == {
        "code": "REPLAY_QUESTION_CLOSED",
        "params": {"question_id": "q1", "state": "not_open"},
    }
    # 进入 1 日盘前（开放且截止）后作答校验
    for _ in range(40):
        state = session_state(client, sid)
        if (state["day_idx"], state["phase"]) == (1, "pre_open"):
            break
        advance(client, sid, expected_tick=state["tick"], to="next_day")
    assert session_state(client, sid)["open_question_ids"] == ["q1", "q2"]
    bad_sum = answer(client, sid, "q1", {"probs": [10, 20, 40, 20, 9]})
    assert bad_sum.status_code == 422
    assert bad_sum.json()["code"] == "VALIDATION_ERROR"
    short = answer(client, sid, "q1", {"probs": [50, 50]})
    assert short.json()["code"] == "VALIDATION_ERROR"
    assert answer(client, sid, "q1", {"order": Q2_ORDER}).json()["params"]["field"] == "order"
    assert answer(client, sid, "q2", {"probs": Q1_PROBS}).json()["params"]["field"] == "probs"
    dup = answer(client, sid, "q2", {"order": [ALIAS["s1"], ALIAS["s1"], ALIAS["s2"]]})
    assert dup.json()["params"] == {"field": "order"}
    real_code = answer(client, sid, "q2", {"order": ["600001", ALIAS["s2"], ALIAS["s3"]]})
    assert real_code.json()["params"] == {"field": "order"}
    unknown = answer(client, sid, "no-such", {"probs": Q1_PROBS})
    assert unknown.json()["params"] == {"field": "question_id"}
    # 合法作答可反复覆盖
    assert answer(client, sid, "q1", {"probs": Q1_PROBS}).json()["status"] == "answered"
    again = answer(client, sid, "q1", {"probs": [20, 20, 20, 20, 20]}).json()
    assert again["my_answer"] == {"probs": [20, 20, 20, 20, 20]}


def test_closed_after_position_passes_and_settled_rejects(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    for _ in range(40):
        state = session_state(client, sid)
        if (state["day_idx"], state["phase"]) == (1, "pre_open"):
            break
        advance(client, sid, expected_tick=state["tick"], to="next_day")
    assert answer(client, sid, "q1", {"probs": Q1_PROBS}).status_code == 200
    assert answer(client, sid, "q2", {"order": Q2_ORDER}).status_code == 200
    moved = advance(client, sid, expected_tick=session_state(client, sid)["tick"]).json()
    assert moved["session"]["phase"] == "open"  # 两题已答，越过截止
    closed = answer(client, sid, "q1", {"probs": Q1_PROBS})
    assert closed.json()["params"] == {"question_id": "q1", "state": "closed"}
    client.post(f"{API}/replay/sessions/{sid}/finish")
    settled = answer(client, sid, "q2", {"order": Q2_ORDER})
    assert settled.json()["code"] == "REPLAY_SESSION_SETTLED"


def test_skipped_question_records_zero(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")  # 停在 1 日盘前
    out = advance(client, sid, expected_tick=session_state(client, sid)["tick"], skip_pending=True)
    assert sorted(out.json()["scored_question_ids"]) == ["q1", "q2"]
    items = {
        q["id"]: q for q in client.get(f"{API}/replay/sessions/{sid}/questions").json()["items"]
    }
    assert items["q1"]["status"] == "skipped"
    assert items["q1"]["result"]["score"] == 0


def test_scores_equal_domain_and_points_credited_once(app: FastAPI, client: TestClient) -> None:
    created = create_session(client)  # 匿名：积分 ×1.0
    sid = created["save_id"]
    scored_at = _play_to_resolution(client, sid)
    # 两题在结算点（resolves = 5 日收盘）计分，分数等于 domain.scoring 的纯函数结果
    assert scored_at == {"5-close": ["q1", "q2"]}
    state = session_state(client, sid)
    assert state["status"] == "settled"
    assert state["settled"]["points_total"] == EXPECTED_Q1 + EXPECTED_Q2
    items = {
        q["id"]: q for q in client.get(f"{API}/replay/sessions/{sid}/questions").json()["items"]
    }
    assert items["q1"]["result"]["score"] == EXPECTED_Q1
    assert items["q2"]["result"]["score"] == EXPECTED_Q2
    assert items["q1"]["result"]["outcome_bucket"] == 2

    uid = user_id(app, "alice")
    with app.state.session_factory() as db:
        level_id = db.scalar(select(ReplayLevel.id).where(ReplayLevel.slug == SLUG))
        rows = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.user_id == uid, LedgerEntry.reason == "replay_prediction"
            )
        ).all()
        keys = sorted(r.idempotency_key for r in rows)
        assert keys == sorted(
            [f"replay:{uid.hex}:{level_id.hex}:q1", f"replay:{uid.hex}:{level_id.hex}:q2"]
        )
        balance = db.get(PointAccount, uid).balance
        assert balance == WELCOME_POINTS + EXPECTED_Q1 + EXPECTED_Q2


def test_second_attempt_same_level_scores_but_earns_no_points(
    app: FastAPI, client: TestClient
) -> None:
    _play_to_resolution(client, create_session(client)["save_id"])
    uid = user_id(app, "alice")
    with app.state.session_factory() as db:
        before = db.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.user_id == uid, LedgerEntry.reason == "replay_prediction")
        )
        balance_before = db.get(PointAccount, uid).balance

    second = create_session(client)["save_id"]
    _play_to_resolution(client, second)
    state = session_state(client, second)
    assert state["settled"]["points_total"] == 0
    items = {
        q["id"]: q for q in client.get(f"{API}/replay/sessions/{second}/questions").json()["items"]
    }
    assert items["q1"]["result"]["score"] == EXPECTED_Q1  # 分数照常记录
    assert items["q1"]["result"]["points"] == 0
    with app.state.session_factory() as db:
        after = db.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.user_id == uid, LedgerEntry.reason == "replay_prediction")
        )
        assert after == before
        assert db.get(PointAccount, uid).balance == balance_before


def test_real_names_halve_points(app: FastAPI) -> None:
    """实名首次会话：积分 ×0.5（05 Q1 建议值），四舍五入。"""
    with TestClient(app) as client:
        register(client, "bob")
        created = create_session(client, masked=False)
        _play_to_resolution(client, created["save_id"], masked=False)
        state = session_state(client, created["save_id"])
    expected = (EXPECTED_Q1 * 50 + 50) // 100 + (EXPECTED_Q2 * 50 + 50) // 100
    assert state["settled"]["points_total"] == expected


def test_pending_question_blocks_advance_and_skip_is_explicit(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    for _ in range(40):
        state = session_state(client, sid)
        if (state["day_idx"], state["phase"]) == (1, "pre_open"):
            break
        advance(client, sid, expected_tick=state["tick"], to="next_day")
    blocked = advance(client, sid, expected_tick=state["tick"])
    assert blocked.status_code == 409
    assert blocked.json() == {
        "code": "REPLAY_PREDICTION_PENDING",
        "params": {"question_ids": ["q1", "q2"]},
    }
    assert session_state(client, sid)["tick"] == state["tick"]
