"""真实复盘的揭示与隔离（05 §1.6、§1.7、§5.7、§8.2 第 4 点（feed 部分）、第 9、10 点）。"""

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

from stocksim.schemas.events import NewsOut

API = "/api/v1"
Q1_PROBS = [10, 20, 40, 20, 10]
Q2_ORDER = [ALIAS["s2"], ALIAS["s3"], ALIAS["s1"]]


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return build_app(tmp_path / "app")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client, "alice")
        yield test_client


def _finish_game(client: TestClient, sid: str) -> None:
    """走完游戏：第 1 日盘前作答，之后逐步推进到结算。"""
    for _ in range(40):
        state = session_state(client, sid)
        if state["status"] == "settled":
            return
        if (state["day_idx"], state["phase"]) == (1, "pre_open") and state["pending_question_ids"]:
            answer(client, sid, "q1", {"probs": Q1_PROBS})
            answer(client, sid, "q2", {"order": Q2_ORDER})
        assert advance(client, sid, expected_tick=state["tick"]).status_code == 200
    raise AssertionError("game did not settle")


def test_reveal_locked_until_settled(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    locked = client.get(f"{API}/replay/sessions/{sid}/reveal")
    assert locked.json() == {"code": "REPLAY_REVEAL_LOCKED", "params": {"save_id": sid}}


def test_reveal_shows_real_identity_and_full_bars(client: TestClient) -> None:
    raw = load_fixture()
    sid = create_session(client)["save_id"]
    _finish_game(client, sid)
    resp = client.get(f"{API}/replay/sessions/{sid}/reveal")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["commentary"] == raw["commentary"]
    stocks = {s["real_code"]: s for s in body["stocks"]}
    assert set(stocks) == set(REAL.values())
    s1 = stocks[REAL["s1"]]
    assert s1["real_name"] == REAL_NAMES[0]
    assert s1["code"] == ALIAS["s1"]  # 会话内代码仍是别名
    # 完整 K 线：回看 15 + 游戏 6 + 揭示 4 = 25 根，真实日期
    assert len(s1["candles"]) == len(raw["calendar"])
    assert [c["date"] for c in s1["candles"]] == raw["calendar"]
    assert s1["play_range"] == [0, 5]

    assert len(body["benchmark"]["points"]) == len(raw["calendar"])
    assert body["benchmark"]["name"] == "沪深300"

    # 事件：真实标题与正文 + 影响；匿名时被隐藏的事件在揭示页出现
    titles = {e["event_id"]: e["title"] for e in body["events"]}
    assert titles["replay:e0001"] == raw["events"][0]["title"]
    assert "replay:e0013" in titles
    hidden = next(e for e in body["events"] if e["event_id"] == "replay:e0013")
    assert hidden["title"] == "测试甲董事长接受采访"
    assert hidden["impact"] == {"ar_1d_bp": 290, "ar_5d_bp": 16}
    assert hidden["sentiment"] is None
    assert hidden["url"] is None  # 揭示页的 url 与原文件一致：夹具中为空

    # 题目：对错与得分
    questions = {q["id"]: q for q in body["questions"]}
    assert questions["q1"]["result"]["outcome_bucket"] == 2
    assert questions["q1"]["result"]["return_bp"] == -60
    assert questions["q1"]["my_answer"] == {"probs": Q1_PROBS}
    # 真实前三（按真实收益降序：s2 +1689bp > s1 -60bp > s3 -470bp），给真实代码
    assert questions["q2"]["result"]["true_top"] == [REAL["s2"], REAL["s1"], REAL["s3"]]

    # 资产曲线与对照指标
    assert body["equity"][0]["kind"] == "initial"
    assert isinstance(body["hold_all_return_bp"], int)
    assert body["trades_count"] == 0
    assert body["session"]["settled"]["points_total"] >= 0
    assert body["benchmark_return_bp"] == body["session"]["settled"]["benchmark_return_bp"]


def test_feed_items_are_a_compatible_news_shape(client: TestClient) -> None:
    """to_feed_item 是唯一的 A 适配点：字段名覆盖 A 的 NewsOut（05 §5.7）。"""
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")
    items = client.get(f"{API}/replay/sessions/{sid}/feed", params={"limit": 50}).json()["items"]
    assert items
    news_fields = set(NewsOut.model_fields)
    for item in items:
        assert news_fields <= set(item)
        assert item["stage"] == "publish"
        assert item["kind"] in {"announcement", "news", "policy"}
        assert item["news_id"] == item["event_id"]
        assert item["news_id"].startswith("replay:")
        assert item["url"] is None  # 匿名不下发链接


def test_normal_save_cannot_use_replay_routes(client: TestClient) -> None:
    normal = client.post(f"{API}/saves", json={"name": "普通", "clock_rules": 1}).json()["id"]
    assert client.get(f"{API}/replay/sessions/{normal}/reveal").json()["code"] == "SAVE_NOT_FOUND"
    assert (
        client.post(f"{API}/replay/sessions/{normal}/advance", json={"expected_tick": 0}).json()[
            "code"
        ]
        == "SAVE_NOT_FOUND"
    )


def test_events_endpoints_are_disabled_for_replay(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    assert client.get(f"{API}/saves/{sid}/news").json()["code"] == "EVENTS_DISABLED"
    assert client.get(f"{API}/saves/{sid}/events").json()["code"] == "EVENTS_DISABLED"
    assert client.get(f"{API}/saves/{sid}/supply-chain").json()["code"] == "REPLAY_UNSUPPORTED"


def test_export_has_no_seed_and_no_pack(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    _finish_game(client, sid)
    export = client.get(f"{API}/saves/{sid}/export").json()
    assert export["save"]["mode"] == "replay"
    assert export["save"]["market_seed"] == "0"
    assert export["save"]["clock_rules"] == "v1"
    text = client.get(f"{API}/saves/{sid}/export").text
    for leaked in (*REAL.values(), *REAL_NAMES):
        assert leaked not in text


def test_deleting_replay_save_removes_session_and_keeps_level(
    app: FastAPI, client: TestClient
) -> None:
    sid = create_session(client)["save_id"]
    assert client.delete(f"{API}/saves/{sid}").status_code == 204
    assert client.get(f"{API}/replay/sessions").json()["items"] == []
    assert client.get(f"{API}/replay/levels/{SLUG}").status_code == 200


def test_other_save_endpoints_never_500_for_replay(client: TestClient) -> None:
    """复盘存档访问普通存档的其它接口：不得 500，要么正常返回，要么给出业务错误码。"""
    sid = create_session(client)["save_id"]
    advance(client, sid, expected_tick=0, to="next_day")  # 1 日盘前，行情已有开盘前的数据
    code = ALIAS["s1"]
    paths = [
        f"{API}/saves/{sid}/predictions",
        f"{API}/saves/{sid}/predictions/settings",
        f"{API}/saves/{sid}/intel",
        f"{API}/saves/{sid}/auto-trade/status",
        f"{API}/saves/{sid}/auto-trade/configs",
        f"{API}/saves/{sid}/auto-trade/events",
        f"{API}/saves/{sid}/market/{code}/intraday",
        f"{API}/saves/{sid}/market/{code}/event-marks",
        f"{API}/saves/{sid}/market?sort=change&limit=2",
        f"{API}/saves/{sid}/portfolio",
        f"{API}/saves/{sid}/equity-curve?range=7d",
        f"{API}/saves/{sid}/trades",
        f"{API}/saves/{sid}/export",
        f"{API}/saves/{sid}/supply-chain",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code < 500, (path, resp.status_code, resp.text)
    intraday = client.get(f"{API}/saves/{sid}/market/{code}/intraday").json()
    assert intraday["points"] == []  # 盘前无分时点
    assert intraday["exact"] is True
