"""真实复盘的交易：阶段成交价、T+1、停牌、封板、收盘可成交、守卫错误码与名称口径（05 §8.2）。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_support import (
    ALIAS,
    REAL,
    REAL_NAMES,
    advance,
    answer,
    build_app,
    create_session,
    register,
    session_state,
)

API = "/api/v1"
Q1_PROBS = [10, 20, 40, 20, 10]
Q2_ORDER = [ALIAS["s2"], ALIAS["s3"], ALIAS["s1"]]
S1, S2, S3 = ALIAS["s1"], ALIAS["s2"], ALIAS["s3"]


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return build_app(tmp_path / "app")


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client, "alice")
        yield test_client


def _quote(client: TestClient, sid: str, code: str) -> dict:
    return client.get(f"{API}/saves/{sid}/market/{code}").json()


def _order(client: TestClient, sid: str, code: str, side: str, qty: int = 100) -> object:
    return client.post(
        f"{API}/saves/{sid}/orders",
        json={"code": code, "side": side, "quantity": qty, "price_type": "market"},
    )


def _step(client: TestClient, sid: str) -> dict:
    state = session_state(client, sid)
    resp = advance(client, sid, expected_tick=state["tick"])
    assert resp.status_code == 200, resp.text
    return resp.json()["session"]


def _answer_day1_questions(client: TestClient, sid: str) -> None:
    assert answer(client, sid, "q1", {"probs": Q1_PROBS}).status_code == 200
    assert answer(client, sid, "q2", {"order": Q2_ORDER}).status_code == 200


def goto(client: TestClient, sid: str, day: int, phase: str) -> dict:
    """逐阶段推进到 (day, phase)；第 1 日盘前题目截止，先作答（05 §1.5）。"""
    for _ in range(60):
        state = session_state(client, sid)
        if (state["day_idx"], state["phase"]) == (day, phase):
            return state
        if (state["day_idx"], state["phase"]) == (1, "pre_open") and state["pending_question_ids"]:
            _answer_day1_questions(client, sid)
        _step(client, sid)
    raise AssertionError(f"cannot reach {(day, phase)}")


def test_pre_open_order_is_market_closed(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    resp = _order(client, sid, S2, "buy")
    assert resp.status_code == 409
    assert resp.json()["code"] == "MARKET_CLOSED"


def test_open_fill_at_open_price_t1_and_close_fill(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    _step(client, sid)  # → 0 日 open
    open_price = _quote(client, sid, S2)["price_cents"]
    resp = _order(client, sid, S2, "buy")
    assert resp.status_code == 201, resp.text
    trade = resp.json()["trade"]
    assert trade["price_cents"] == open_price  # 开盘价成交
    assert trade["clock_minute"] == 570
    assert trade["name"] == "券商B"  # 匿名：别名，不是真实名称
    assert trade["code"] == S2
    sell = _order(client, sid, S2, "sell")  # 当日买入不能卖（T+1）
    assert sell.status_code == 422
    assert sell.json()["code"] == "TRADE_T1_SELL_BLOCKED"

    _step(client, sid)  # → 0 日 close（900 分）
    close_price = _quote(client, sid, S3)["price_cents"]
    buy_close = _order(client, sid, S3, "buy")
    assert buy_close.status_code == 201, buy_close.text  # 收盘可成交，不是 MARKET_CLOSED
    assert buy_close.json()["trade"]["price_cents"] == close_price
    assert buy_close.json()["trade"]["clock_minute"] == 900

    _step(client, sid)  # → 0 日 post_close
    assert _order(client, sid, S3, "buy").json()["code"] == "MARKET_CLOSED"


def test_suspended_and_limit_up_open_locks(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    goto(client, sid, 0, "open")
    assert _order(client, sid, S1, "buy").status_code == 201  # 0 日 s1 无标志位
    goto(client, sid, 1, "open")  # s1 停牌（flags=1）
    # 行情详情直接给出停牌标记（前端据此禁用买卖）
    assert _quote(client, sid, S1)["suspended"] is True
    assert _quote(client, sid, S2)["suspended"] is False
    susp = _order(client, sid, S1, "buy")
    assert susp.status_code == 409
    assert susp.json() == {"code": "REPLAY_STOCK_SUSPENDED", "params": {"code": S1}}
    # s2 无标志位：当日买入后当日不可卖（T+1）
    assert _order(client, sid, S2, "buy").status_code == 201
    t1 = _order(client, sid, S2, "sell")
    assert t1.status_code == 422
    assert t1.json()["code"] == "TRADE_T1_SELL_BLOCKED"
    # 3 日开盘封涨停（flags=10）：买入被拒、卖出允许
    goto(client, sid, 3, "open")
    locked = _order(client, sid, S1, "buy")
    assert locked.status_code == 409
    assert locked.json() == {"code": "REPLAY_LIMIT_LOCKED", "params": {"code": S1, "side": "buy"}}
    sold = _order(client, sid, S1, "sell", qty=100)
    assert sold.status_code == 201, sold.text


def test_limit_down_close_locks_sell(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    goto(client, sid, 0, "open")
    assert _order(client, sid, S1, "buy").status_code == 201
    goto(client, sid, 5, "close")  # s1 在 5 日收盘封跌停（flags=16）
    locked = _order(client, sid, S1, "sell")
    assert locked.status_code == 409
    assert locked.json() == {"code": "REPLAY_LIMIT_LOCKED", "params": {"code": S1, "side": "sell"}}


def test_names_and_portfolio_use_alias_and_unsupported_features(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    _step(client, sid)
    assert _order(client, sid, S2, "buy").status_code == 201
    portfolio = client.get(f"{API}/saves/{sid}/portfolio").json()
    assert [h["name"] for h in portfolio["holdings"]] == ["券商B"]
    trades = client.get(f"{API}/saves/{sid}/trades").json()["items"]
    assert trades[0]["name"] == "券商B"
    text = (
        client.get(f"{API}/saves/{sid}/trades").text
        + client.get(f"{API}/saves/{sid}/portfolio").text
    )
    for leaked in (*REAL.values(), *REAL_NAMES):
        assert leaked not in text

    day_summary = client.get(f"{API}/saves/{sid}/day-summary")
    assert day_summary.status_code == 409
    assert day_summary.json() == {
        "code": "REPLAY_UNSUPPORTED",
        "params": {"feature": "day_summary"},
    }
    pause = client.post(f"{API}/saves/{sid}/clock/pause")
    assert pause.json() == {"code": "REPLAY_UNSUPPORTED", "params": {"feature": "clock"}}
    skip = client.post(f"{API}/saves/{sid}/clock/skip")
    assert skip.json()["code"] == "REPLAY_UNSUPPORTED"
    auto = client.post(
        f"{API}/saves/{sid}/auto-trade/configs",
        json={"code": S2, "direction": "buy", "condition_type": "time", "quantity": 100},
    )
    assert auto.json() == {"code": "REPLAY_UNSUPPORTED", "params": {"feature": "auto_trade"}}
    start = client.post(f"{API}/saves/{sid}/auto-trade/start")
    assert start.json() == {"code": "REPLAY_UNSUPPORTED", "params": {"feature": "auto_trade"}}


def test_watchlist_accepts_session_codes_only(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    assert client.put(f"{API}/saves/{sid}/watchlist/{S1}").status_code == 204
    assert client.put(f"{API}/saves/{sid}/watchlist/600036").json()["code"] == "STOCK_NOT_FOUND"


def test_clock_v1_and_null_time_fields(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    _step(client, sid)  # 0 日 open
    market = client.get(f"{API}/saves/{sid}/market").json()
    assert market["clock_rules"] == "v1"
    assert market["paused"] is True
    assert market["ms_per_minute"] is None
    assert market["next_tick_at"] is None
    assert market["fast_forward_at"] is None
    assert market["next_event"]["at"] is None
    assert market["trading"] is True


def test_websocket_refuses_replay_save(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    with client.websocket_connect(f"{API}/ws/saves/{sid}") as ws:
        assert ws.receive_json() == {"t": "error", "code": "REPLAY_UNSUPPORTED"}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4409


def test_order_after_finish_is_settled(client: TestClient) -> None:
    sid = create_session(client)["save_id"]
    client.post(f"{API}/replay/sessions/{sid}/finish")
    resp = _order(client, sid, S2, "buy")
    assert resp.status_code == 409
    assert resp.json()["code"] == "REPLAY_SESSION_SETTLED"


def test_equity_snapshot_written_when_leaving_close(client: TestClient) -> None:
    """离开收盘阶段写当日快照；资产曲线只取早于当前日的快照，次日盘前可见（与普通存档口径一致）。"""
    sid = create_session(client)["save_id"]
    goto(client, sid, 0, "open")
    _order(client, sid, S2, "buy")
    goto(client, sid, 0, "post_close")
    before = client.get(f"{API}/saves/{sid}/equity-curve", params={"range": "all"}).json()
    assert "close" not in [p["kind"] for p in before["items"]]
    goto(client, sid, 1, "pre_open")
    curve = client.get(f"{API}/saves/{sid}/equity-curve", params={"range": "all"}).json()["items"]
    day0 = next(p for p in curve if p["trading_day"] == 0 and p["kind"] == "close")
    assert day0["equity_cents"] == day0["cash_cents"] + day0["market_value_cents"]


def test_debug_service_entries_are_rejected(app: FastAPI, client: TestClient) -> None:
    """调试入口（05 §5.3）：服务层统一守卫，即使 ENABLE_DEBUG_API 打开也不作用于复盘存档。"""
    import uuid

    from stocksim.core.errors import AppError
    from stocksim.models import Save
    from stocksim.services import debug as debug_service

    sid = create_session(client)["save_id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        with pytest.raises(AppError) as exc:
            debug_service.set_cash(db, save, 1)
        assert exc.value.params == {"feature": "debug"}
        with pytest.raises(AppError) as exc2:
            debug_service.reset_market(db, save)
        assert exc2.value.params == {"feature": "debug"}
