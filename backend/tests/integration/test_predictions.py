"""预测卡接口与行为（02 §13.2）。

v2 存档（默认）：出卡、暂停、作答、不答过期、结算入账、称号、日上限、关闭模式。
行情随机种子不可控：用 skip 推进到出卡（每交易日约有重大事件），不对事件内容做断言。
"""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from stocksim.models import LedgerEntry
from stocksim.services import predictions as pred_service

SAVES = "/api/v1/saves"
PUBLIC_KEYS = {
    "dir": {
        "qid",
        "kind",
        "target_kind",
        "target",
        "target_name",
        "edges_bp",
        "from_day",
        "to_day",
    },
    "rank": {"qid", "kind", "k", "exclude", "candidates", "at_day"},
    "rumor": {"qid", "kind"},
}
HIDDEN = ("magnitude", "knots", "scale_ppm", "delay_ticks", "resolve", "truth")


@pytest.fixture(autouse=True)
def _policies():
    pred_service.clear_card_policies()
    yield
    pred_service.clear_card_policies()


def _early_major(seed: int, max_tick: int = 39) -> bool:
    """种子的重大事件是否在前两个 v1 交易日内触发（纯领域计算，用于挑选 v1 存档）。

    v1 每次跳过只推进约 0.4 个交易 tick，过晚的事件超出测试的跳过预算。
    """
    from stocksim.domain.events import generate_day, save_params
    from stocksim.services import events as events_service

    rs = events_service.ruleset(1, 1)
    params = save_params(seed, rs)
    return any(
        e.major and min(n.trading_tick for n in e.news) <= max_tick
        for d in range(3)
        for e in generate_day(seed, d, rs, params)
    )


def _event_save(client: TestClient, clock_rules: int = 2, name: str = "pred") -> str:
    """v2 直接创建；v1 的重大事件约每 12 个交易日一次，循环创建直到种子在前几天有重大事件。"""
    from stocksim.models import Save

    for _ in range(200):
        resp = client.post(
            SAVES, json={"name": name, "events_enabled": True, "clock_rules": clock_rules}
        )
        assert resp.status_code == 201, resp.text
        sid = resp.json()["id"]
        if clock_rules == 2:
            return sid
        with client.app.state.session_factory() as db:  # type: ignore[attr-defined]
            seed = db.get(Save, uuid.UUID(sid)).market_seed
        if _early_major(seed):
            return sid
        client.delete(f"{SAVES}/{sid}")  # 不匹配的存档立即删除（每用户上限 10）
    raise AssertionError("no v1 seed with an early major event")


def _skip(client: TestClient, sid: str) -> dict:
    resp = client.post(f"{SAVES}/{sid}/clock/skip")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _step(client: TestClient, sid: str, clock_rules: int | None = None) -> None:
    """推进一步：v2 用 skip；v1 的 skip 会在部分分钟停住（legacy 跳过表），改为推进 10 分钟。"""
    if clock_rules is None:
        clock_rules = 2 if client.get(f"{SAVES}/{sid}").json()["clock_rules"] == "v2" else 1
    if clock_rules == 2:
        _skip(client, sid)
        return
    from stocksim.models import Save
    from stocksim.services.market import advance_ticks

    with client.app.state.session_factory() as db:  # type: ignore[attr-defined]
        advance_ticks(db, db.get(Save, uuid.UUID(sid)), 10)


def _open_cards(client: TestClient, sid: str) -> list[dict]:
    resp = client.get(f"{SAVES}/{sid}/predictions", params={"status": "open"})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _until_card(client: TestClient, sid: str, max_skips: int = 400) -> dict:
    for _ in range(max_skips):
        if _open_cards(client, sid):
            return _open_cards(client, sid)[0]
        _step(client, sid)
    raise AssertionError("no prediction card opened")


def _answer_body(card: dict, *, resume: bool = True, dir_probs=(7, 7, 8, 70, 8)) -> dict:
    body: dict = {"resume": resume, "answers": {}}
    qs = {q["qid"]: q for q in card["questions"]}
    if "dir" in qs:
        body["answers"]["dir"] = {"probs": list(dir_probs)}
    if "rank" in qs:
        body["answers"]["rank"] = {"order": qs["rank"]["candidates"][:3]}
    if "rumor" in qs:
        body["answers"]["rumor"] = {"probs": [20, 80]}
    return body


def test_events_disabled_save_returns_409(registered_client: TestClient):
    resp = registered_client.post(SAVES, json={"name": "plain", "events_enabled": False})
    sid = resp.json()["id"]
    resp = registered_client.get(f"{SAVES}/{sid}/predictions")
    assert resp.status_code == 409
    assert resp.json()["code"] == "EVENTS_DISABLED"


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_card_opens_pauses_and_has_public_questions_only(
    clock_rules: int, registered_client: TestClient
):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    assert card["status"] == "open"
    assert card["questions"][0]["qid"] == "dir"
    for q in card["questions"]:
        assert set(q) == PUBLIC_KEYS[q["qid"]]
    text = json.dumps(card["questions"], ensure_ascii=False)
    for word in HIDDEN:
        assert word not in text
    assert card["results"] and all(not r["resolved"] for r in card["results"])
    market = registered_client.get(f"{SAVES}/{sid}/market").json()
    assert market["paused"] is True


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_invalid_answers_return_422(clock_rules: int, registered_client: TestClient):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    url = f"{SAVES}/{sid}/predictions/{card['id']}/answer"
    body = _answer_body(card, dir_probs=(7, 7, 8, 70, 7))
    resp = registered_client.post(url, json=body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert resp.json()["params"]["field"] == "answers.dir.probs"
    resp = registered_client.post(url, json={"resume": True, "answers": {}})
    assert resp.status_code == 422
    assert resp.json()["params"]["field"] == "answers.dir"
    assert resp.json()["params"]["reason"] == "missing"


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_answer_with_resume_continues_and_without_stays_paused(
    clock_rules: int, registered_client: TestClient
):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    url = f"{SAVES}/{sid}/predictions/{card['id']}/answer"
    resp = registered_client.post(url, json=_answer_body(card, resume=False))
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["card"]["status"] == "answered"
    assert out["clock"]["paused"] is True
    # 截止前可覆盖
    resp = registered_client.post(url, json=_answer_body(card, resume=True))
    assert resp.status_code == 200, resp.text
    assert resp.json()["clock"]["paused"] is False


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_skip_expires_card_and_later_answer_is_closed(
    clock_rules: int, registered_client: TestClient
):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    url = f"{SAVES}/{sid}/predictions/{card['id']}"
    resp = registered_client.post(f"{url}/skip", json={"resume": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["card"]["status"] == "expired"
    assert resp.json()["clock"]["paused"] is False
    resp = registered_client.post(f"{url}/answer", json=_answer_body(card))
    assert resp.status_code == 409
    assert resp.json()["code"] == "PREDICTION_CLOSED"
    assert resp.json()["params"]["status"] == "expired"


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_expired_by_time_when_clock_moves_past_deadline(
    clock_rules: int, registered_client: TestClient
):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    # 恢复行情并推进一个交易 tick：截止 = 触发 tick，之后即过期
    registered_client.post(f"{SAVES}/{sid}/clock/resume")
    _skip(registered_client, sid)
    resp = registered_client.get(f"{SAVES}/{sid}/predictions/{card['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "expired"


def test_unknown_card_returns_404(registered_client: TestClient):
    sid = _event_save(registered_client)
    resp = registered_client.get(f"{SAVES}/{sid}/predictions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 404
    assert resp.json()["code"] == "PREDICTION_NOT_FOUND"


def test_other_users_save_is_404(client: TestClient, registered_client: TestClient):
    sid = _event_save(registered_client)
    client.post("/api/v1/auth/register", json={"username": "bob", "password": "secret1"})
    resp = client.get(f"{SAVES}/{sid}/predictions")
    assert resp.status_code == 404
    assert resp.json()["code"] == "SAVE_NOT_FOUND"


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_settle_credits_points_once_and_grants_title(
    clock_rules: int, registered_client: TestClient
):
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    url = f"{SAVES}/{sid}/predictions/{card['id']}/answer"
    assert registered_client.post(url, json=_answer_body(card, resume=True)).status_code == 200
    # 推进直到该卡结算：遇到新卡就不答直接跳过（expired，不影响这张卡）
    settled = None
    for _ in range(400):
        _step(registered_client, sid, clock_rules)
        resp = registered_client.get(f"{SAVES}/{sid}/predictions/{card['id']}").json()
        if resp["status"] == "settled":
            settled = resp
            break
        for other in _open_cards(registered_client, sid):
            registered_client.post(
                f"{SAVES}/{sid}/predictions/{other['id']}/skip", json={"resume": True}
            )
    assert settled is not None, "card did not settle"
    scores = [r["points"] for r in settled["results"] if r["points"] is not None]
    assert settled["points"] == sum(scores)
    assert all(r["resolved"] for r in settled["results"])
    dir_res = next(r for r in settled["results"] if r["qid"] == "dir")
    assert dir_res["change_bp"] is not None and dir_res["outcome_bucket"] in range(5)

    points = registered_client.get("/api/v1/points").json()
    assert points["balance"] == 200 + settled["points"]
    ledger = registered_client.get("/api/v1/points/ledger", params={"reason": "prediction"}).json()
    assert len(ledger["items"]) == 1
    assert ledger["items"][0]["delta"] == settled["points"]
    titles = registered_client.get("/api/v1/points/titles").json()
    unlocked = {t["id"]: t["unlocked_at"] for t in titles["items"]}
    assert unlocked["forecaster_1"] is not None

    # 再次结算（读接口）不重复入账
    registered_client.get(f"{SAVES}/{sid}/predictions")
    registered_client.get(f"{SAVES}/{sid}/predictions")
    assert registered_client.get("/api/v1/points").json()["balance"] == 200 + settled["points"]
    with registered_client.app.state.session_factory() as db:  # type: ignore[attr-defined]
        rows = db.scalars(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == f"prediction:{card['id']}")
        ).all()
        assert len(rows) == 1


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_daily_cap_limits_grant(clock_rules: int, registered_client: TestClient, app: FastAPI):
    from stocksim.services.predictions import CardPolicy, register_card_policy

    register_card_policy(lambda db, save: CardPolicy(daily_cap=1))
    sid = _event_save(registered_client, clock_rules)
    card = _until_card(registered_client, sid)
    url = f"{SAVES}/{sid}/predictions/{card['id']}/answer"
    registered_client.post(url, json=_answer_body(card, resume=True))
    settled = None
    for _ in range(400):
        _step(registered_client, sid, clock_rules)
        resp = registered_client.get(f"{SAVES}/{sid}/predictions/{card['id']}").json()
        if resp["status"] == "settled":
            settled = resp
            break
        for other in _open_cards(registered_client, sid):
            registered_client.post(
                f"{SAVES}/{sid}/predictions/{other['id']}/skip", json={"resume": True}
            )
    assert settled is not None
    assert settled["points_capped"] is True
    assert registered_client.get("/api/v1/points").json()["balance"] == 200 + 1


@pytest.mark.parametrize("clock_rules", [1, 2], ids=["v1", "v2"])
def test_mode_off_never_pauses(clock_rules: int, registered_client: TestClient):
    sid = _event_save(registered_client, clock_rules)
    resp = registered_client.put(f"{SAVES}/{sid}/predictions/settings", json={"mode": "off"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"mode": "off", "forced": False}
    for _ in range(40):
        clock = _skip(registered_client, sid)
        assert clock["paused"] is False
    assert registered_client.get(f"{SAVES}/{sid}/predictions").json()["items"] == []


def test_points_endpoint_opens_account_with_welcome(registered_client: TestClient):
    out = registered_client.get("/api/v1/points").json()
    assert out["balance"] == 200
    assert out["lifetime_earned"] == 200
    assert out["daily_cap"] == 1000
    assert out["today_prediction_points"] == 0
    ledger = registered_client.get("/api/v1/points/ledger").json()
    assert ledger["items"][0]["reason"] == "welcome"


def test_title_equip_rules(registered_client: TestClient):
    resp = registered_client.put("/api/v1/points/title", json={"title_id": "bullseye"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "TITLE_NOT_UNLOCKED"
    resp = registered_client.put("/api/v1/points/title", json={"title_id": "nope"})
    assert resp.status_code == 422
    resp = registered_client.put("/api/v1/points/title", json={"title_id": None})
    assert resp.status_code == 200 and resp.json()["equipped_title"] is None


def test_stats_shape(registered_client: TestClient):
    out = registered_client.get("/api/v1/points/stats").json()
    assert set(out) >= {"cards_answered", "cards_settled", "by_kind", "calibration", "recent"}
    assert len(out["calibration"]) == 10
    assert set(out["by_kind"]) == {"bucket", "rank", "binary"}


def test_bad_status_filter_is_422(registered_client: TestClient):
    sid = _event_save(registered_client)
    resp = registered_client.get(f"{SAVES}/{sid}/predictions", params={"status": "bogus"})
    assert resp.status_code == 422


def test_reset_market_voids_unsettled_cards(settings, migrated) -> None:
    """换 seed（debug/reset-market）前：未结算的卡 → void，不发积分（02 §3.5）。"""
    from stocksim.main import create_app

    app = create_app(settings.model_copy(update={"ENABLE_DEBUG_API": True}))
    client = TestClient(app)
    with client:
        resp = client.post(
            "/api/v1/auth/register", json={"username": "reset", "password": "secret1"}
        )
        assert resp.status_code == 201, resp.text
        sid = _event_save(client)
        card = _until_card(client, sid)
        resp = client.post(f"{SAVES}/{sid}/debug/reset-market")
        assert resp.status_code == 200, resp.text
        after = client.get(f"{SAVES}/{sid}/predictions/{card['id']}").json()
        assert after["status"] == "void"
        assert after["settled_at"] is not None
        assert client.get("/api/v1/points").json()["balance"] == 200
