"""行情 WebSocket：/api/v1/ws/saves/{id}。鉴权、归属、首帧全量、增量事件与客户端指令。"""

import uuid
from datetime import UTC, date, datetime, timedelta

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
        assert set(first["clock"]) == {
            "minute",
            "trading_day",
            "paused",
            "trading",
            "clock_rules",
            "phase",
            "next_event",
            "ms_per_minute",
            "next_tick_at",
            "fast_forward_at",
            "server_time",
        }
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


# ---- 时钟 v2：phase 消息与推送节奏（直接调用 tick_once，避免依赖真实等待）----


def test_v2_phase_message_is_sent_once_after_the_tick_frame(ctx) -> None:
    from stocksim.api.ws import snapshot, tick_once
    from stocksim.models import Save

    client, app, _ = ctx
    sid = client.post("/api/v1/saves", json={"clock_rules": 2}).json()["id"]
    with app.state.session_factory() as db:
        state = snapshot(db, db.get(Save, uuid.UUID(sid)))
    state.refresh_ms = 500
    session_factory = app.state.session_factory

    messages, _ = tick_once(session_factory, uuid.UUID(sid), state)  # 首帧：只记录相位
    assert next(m["t"] for m in messages) == "tick"
    assert not any(m["t"] == "phase" for m in messages)

    for _ in range(6):  # 570 -> 900（收盘停留）
        assert client.post(f"/api/v1/saves/{sid}/clock/skip").status_code == 200
    messages, delay = tick_once(session_factory, uuid.UUID(sid), state)
    types = [m["t"] for m in messages]
    assert types[:2] == ["tick", "phase"]
    phase = messages[1]
    assert phase["from"] == "morning" and phase["to"] == "closed"
    assert phase["clock_minute"] == 900
    # 收盘停留：下一轮醒在快进时刻，但不超过 ms_per_minute（默认 5000）
    assert delay == 5000

    messages, _ = tick_once(session_factory, uuid.UUID(sid), state)
    assert not any(m["t"] == "phase" for m in messages)  # 同一相位不重复发送


def test_v2_pause_polls_every_two_seconds_and_v1_keeps_refresh_rate(ctx) -> None:
    from stocksim.api.ws import snapshot, tick_once
    from stocksim.models import Save

    client, app, v1_sid = ctx
    v2_sid = client.post("/api/v1/saves", json={"clock_rules": 2}).json()["id"]
    session_factory = app.state.session_factory

    with session_factory() as db:
        v1_state = snapshot(db, db.get(Save, uuid.UUID(v1_sid)))
        v2_state = snapshot(db, db.get(Save, uuid.UUID(v2_sid)))
    v1_state.refresh_ms = v2_state.refresh_ms = 500

    _, v1_delay = tick_once(session_factory, uuid.UUID(v1_sid), v1_state)
    assert v1_delay == 500

    assert client.post(f"/api/v1/saves/{v2_sid}/clock/pause").status_code == 200
    _, paused_delay = tick_once(session_factory, uuid.UUID(v2_sid), v2_state)
    assert paused_delay == 2000


def test_v2_delay_wakes_at_next_minute_within_bounds(ctx) -> None:
    from stocksim.api.ws import next_delay_ms

    view = {
        "clock_rules": "v2",
        "paused": False,
        "next_tick_at": "2026-10-26T10:00:05.000Z",
        "fast_forward_at": None,
        "ms_per_minute": 5000,
    }
    from datetime import UTC, datetime

    now = datetime(2026, 10, 26, 10, 0, 0, tzinfo=UTC)
    assert next_delay_ms({**view, "next_tick_at": "2026-10-26T10:00:03.000Z"}, 500, now) == 3050
    assert next_delay_ms(view, 500, now) == 5000  # 5 s 后到期，夹在 ms_per_minute 上限内
    assert next_delay_ms({**view, "next_tick_at": "2026-10-26T10:00:00.010Z"}, 500, now) == 200
    assert next_delay_ms({**view, "next_tick_at": "2026-10-26T10:01:00.000Z"}, 500, now) == 5000
    assert next_delay_ms({**view, "clock_rules": "v1"}, 1234, now) == 1234


def _events_save(client: TestClient, app: FastAPI, *, events: bool) -> str:
    """v2 存档（快速节奏）；事件开关由参数决定。"""
    resp = client.post(
        "/api/v1/saves",
        json={"name": "news", "clock_rules": 2, "events_enabled": events},
    )
    assert resp.status_code == 201, resp.text
    client.patch("/api/v1/me", json={"clock_speed": "fast"})
    return resp.json()["id"]


def _advance_in_background_db(app: FastAPI, save_id: str, minutes: int) -> None:
    from stocksim.models import Save
    from stocksim.services.market import advance_ticks

    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(save_id)), minutes)


def test_news_frame_is_pushed_when_a_publish_tick_is_crossed(
    registered_client, app: FastAPI
) -> None:
    from stocksim.services.seed import seed_stock_table

    with app.state.session_factory() as db:
        seed_stock_table(db)
    client = registered_client
    save_id = _events_save(client, app, events=True)
    with client.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json()["t"] == "tick"  # 首帧
        _advance_in_background_db(app, save_id, 400)  # 跨过当日全部发布 tick（含 major）
        news = _until(ws, lambda m: m.get("t") == "news", limit=80)
    assert news["items"] and news["truncated"] in (True, False)
    required = {"news_id", "event_id", "stage", "major", "title", "trading_tick"}
    assert required <= set(news["items"][0])
    ticks = [item["trading_tick"] for item in news["items"]]
    assert ticks == sorted(ticks)
    assert any(item["major"] for item in news["items"])
    assert all(item["news_id"].split(":")[0] == item["event_id"] for item in news["items"])


def test_closed_save_never_sends_news_frames(registered_client, app: FastAPI) -> None:
    from stocksim.services.seed import seed_stock_table

    with app.state.session_factory() as db:
        seed_stock_table(db)
    client = registered_client
    save_id = _events_save(client, app, events=False)
    with client.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json()["t"] == "tick"
        _advance_in_background_db(app, save_id, 400)
        for _ in range(12):
            msg = ws.receive_json()
            assert msg.get("t") != "news", msg


def test_prediction_opened_then_expired_are_pushed(registered_client, app: FastAPI) -> None:
    """预测卡：跨过触发 tick → opened（同轮 clock.paused=true）；不答跳过 → expired。"""
    from stocksim.services.seed import seed_stock_table

    with app.state.session_factory() as db:
        seed_stock_table(db)
    client = registered_client
    save_id = _events_save(client, app, events=True)
    with client.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json()["t"] == "tick"
        _advance_in_background_db(app, save_id, 400)
        opened = _until(
            ws, lambda m: m.get("t") == "prediction" and m.get("op") == "opened", limit=80
        )
        assert opened["status"] == "open" and opened["event_id"].startswith("e")
        resp = client.post(
            f"/api/v1/saves/{save_id}/predictions/{opened['card_id']}/skip",
            json={"resume": True},
        )
        assert resp.status_code == 200, resp.text
        expired = _until(
            ws, lambda m: m.get("t") == "prediction" and m.get("op") == "expired", limit=80
        )
        assert expired["card_id"] == opened["card_id"]


# ---------------------------------------------------------------- 每日挑战存档（C10，03 §10.4）

CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)  # compact 整 5 秒对齐
CHALLENGE_DAY = date(2026, 10, 26)
CHALLENGE_KEYS = {
    "challenge_id",
    "status",
    "phase",
    "round_index",
    "next_change_at",
    "public_trading_tick",
    "resolved_qids",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _challenge_client(challenge_app, db, fake_clock, make_user):
    """alice 报名当日挑战（开局时钟），返回 (已登录的 client, 挑战, 玩家存档 id)。"""
    from stocksim.services.challenges import entries, generate

    user = make_user("alice")
    ch = generate.ensure_challenge(db, CHALLENGE_DAY, now=CHALLENGE_NOW)
    fake_clock.value = _aware(ch.starts_at)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    client = TestClient(challenge_app)
    resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client, ch, str(entry.save_id)


def test_challenge_save_first_frames_carry_the_challenge_message(
    challenge_app, db, fake_clock, make_user
) -> None:
    client, ch, save_id = _challenge_client(challenge_app, db, fake_clock, make_user)
    with client.websocket_connect(_ws_path(save_id)) as ws:
        first = ws.receive_json()
        assert first["t"] == "tick" and first["full"] is True
        # 挑战存档的 clock：快放段 ms_per_minute = tick_ms，fast_forward_at 恒 null
        assert first["clock"]["paused"] is False
        assert first["clock"]["ms_per_minute"] == ch.tick_ms
        assert first["clock"]["fast_forward_at"] is None
        assert first["clock"]["next_tick_at"] is not None
        challenge = _until(ws, lambda m: m.get("t") == "challenge")
        assert set(challenge) == {"t"} | CHALLENGE_KEYS
        assert challenge["challenge_id"] == str(ch.id)
        assert challenge["status"] == "running"
        assert challenge["phase"] == "burst" and challenge["round_index"] == 1
        assert challenge["resolved_qids"] == 0
        # 快放段的下一次变化是 hold_at，未到停顿前保密（03 §5 #8）：next_change_at 为 null
        assert challenge["next_change_at"] is None
        assert challenge["public_trading_tick"] == 0  # 开局即 tt = 0
        assert first["clock"]["next_event"]["at"] is None


def test_challenge_frames_follow_the_hold_and_pause_the_clock(
    challenge_app, db, fake_clock, make_user
) -> None:
    from stocksim.services.challenges import registry

    client, ch, save_id = _challenge_client(challenge_app, db, fake_clock, make_user)
    rnd1 = registry.round_by_index(db, ch, 1)
    with client.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json()["t"] == "tick"
        _until(ws, lambda m: m.get("t") == "challenge")
        # 拨过第 1 回合的停顿时刻：tick 帧 paused=true、ms_per_minute=null，challenge 变为 hold
        fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
        paused_tick = _until(
            ws, lambda m: m.get("t") == "tick" and m["clock"]["paused"] is True, limit=80
        )
        assert paused_tick["clock"]["ms_per_minute"] is None
        assert paused_tick["clock"]["next_tick_at"] is None
        assert paused_tick["clock"]["next_event"]["at"] is None
        hold = _until(
            ws, lambda m: m.get("t") == "challenge" and m["phase"] == "hold", limit=80
        )
        assert hold["round_index"] == 1 and hold["status"] == "running"
        assert hold["next_change_at"] is not None  # 停顿的恢复时刻（排程固定，公开）
        # 停顿期间同一相位不再重复推送 challenge（只在变化时推）
        for _ in range(4):
            msg = ws.receive_json()
            assert not (msg.get("t") == "challenge" and msg["phase"] == "hold"), msg


def test_challenge_frame_order_is_tick_phase_challenge(challenge_app, db, fake_clock, make_user):
    """跨过 11:30 且进入停顿的同一轮：tick → phase（07）→ challenge（03 §10.4，06 §3.1 顺序）。"""
    from stocksim.services.challenges import registry

    client, ch, save_id = _challenge_client(challenge_app, db, fake_clock, make_user)
    rnd1 = registry.round_by_index(db, ch, 1)
    assert rnd1.hold_tt > 120  # compact 固定 seed：第 1 回合停顿在 11:30 之后
    with client.websocket_connect(_ws_path(save_id)) as ws:
        assert ws.receive_json()["t"] == "tick"
        _until(ws, lambda m: m.get("t") == "challenge")
        fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
        batch: list[dict] = []
        for _ in range(MAX_FRAMES * 4):
            batch.append(ws.receive_json())
            if batch[-1].get("t") == "challenge" and batch[-1]["phase"] == "hold":
                break
    kinds = [m["t"] for m in batch]
    assert "phase" in kinds, kinds
    assert kinds.index("tick") < kinds.index("phase") < kinds.index("challenge"), kinds
    phase_msg = batch[kinds.index("phase")]
    assert {"from", "to", "trading_day", "clock_minute"} <= set(phase_msg)
    assert batch[kinds.index("tick")]["clock"]["paused"] is True
