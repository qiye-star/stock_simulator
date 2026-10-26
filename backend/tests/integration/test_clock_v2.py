"""时钟 v2 接口行为（07 §9.2）：创建与默认值、节奏档、墙钟补推、午休与收盘停留、次日换日、
暂停、离线截断、跳过全表、收盘小结、旧存档迁移为 v1。

时间控制：把 saves.last_tick_at 回拨到“现在减去 X”，再发请求触发 advance_to_now。
回拨量都留有 ≥10 ms 余量，避免与服务端 utcnow 的微秒差产生边界抖动。
"""

import uuid
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.db.base import utcnow
from stocksim.models import Candle, EquitySnapshot, MarketState, Save

SAVES = "/api/v1/saves"
CODE = "600036"
CLOCK_KEYS = {
    "paused", "tick", "trading_day", "clock_minute", "session", "skipped_ticks",
    "clock_rules", "phase", "trading", "next_event", "ms_per_minute",
    "next_tick_at", "fast_forward_at", "server_time",
}  # fmt: skip


def _create(client: TestClient, **overrides) -> dict:
    resp = client.post(SAVES, json={"name": "v2", **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _backdate(app: FastAPI, sid: str, **delta) -> None:
    """把锚点回拨到 now - delta（服务端据此补推）。"""
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.last_tick_at = utcnow() - timedelta(**delta)
        db.commit()


def _db_save(app: FastAPI, sid: str) -> Save:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        db.expunge(save)
        return save


def _market(client: TestClient, sid: str) -> dict:
    resp = client.get(f"{SAVES}/{sid}/market?limit=1")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _skip(client: TestClient, sid: str) -> dict:
    resp = client.post(f"{SAVES}/{sid}/clock/skip")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_speed(client: TestClient, speed: str) -> None:
    assert client.patch("/api/v1/me", json={"clock_speed": speed}).status_code == 200


def test_v2_create_shape_and_defaults(registered_client: TestClient) -> None:
    save = _create(registered_client, clock_rules=2)
    assert save["clock_rules"] == "v2"
    view = _market(registered_client, save["id"])
    assert set(view) >= CLOCK_KEYS
    assert view["clock_rules"] == "v2"
    assert view["clock_minute"] == 570 and view["tick"] == 0
    assert view["phase"] == "morning" and view["trading"] is True
    assert view["ms_per_minute"] == 5000  # 默认 normal
    assert view["next_event"]["kind"] == "lunch" and view["next_event"]["minute"] == 690
    assert view["next_tick_at"] is not None and view["fast_forward_at"] is None
    assert view["server_time"].endswith("Z")


def test_create_without_clock_rules_is_v1(registered_client: TestClient) -> None:
    save = _create(registered_client)
    assert save["clock_rules"] == "v1"
    view = _market(registered_client, save["id"])
    assert view["clock_rules"] == "v1"
    assert 570 <= view["clock_minute"] <= 690  # v1 仍随机开局
    bad = registered_client.post(SAVES, json={"clock_rules": 3})
    assert bad.status_code == 422


def test_clock_speed_setting_drives_ms_per_minute(registered_client: TestClient) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    _set_speed(registered_client, "fast")
    assert _market(registered_client, sid)["ms_per_minute"] == 2500
    assert registered_client.get("/api/v1/me").json()["clock_speed"] == "fast"
    bad = registered_client.patch("/api/v1/me", json={"clock_speed": "warp"})
    assert bad.status_code == 422


def test_wall_clock_catch_up_advances_one_minute_per_ms(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    _set_speed(registered_client, "fast")  # 2500 ms / 分钟
    _backdate(app, sid, milliseconds=4 * 2500 + 10)
    view = _market(registered_client, sid)
    assert view["clock_minute"] == 574 and view["tick"] == 4
    # 再读一次不会重复推进
    assert _market(registered_client, sid)["tick"] == 4


def test_lunch_dwell_blocks_orders_then_jumps_to_afternoon(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    skipped = _skip(registered_client, sid)
    assert skipped["clock_minute"] == 689 and skipped["skipped_ticks"] == 119

    _backdate(app, sid, milliseconds=5000 + 10)  # 11:29 -> 11:30（午间收盘 tick）
    view = _market(registered_client, sid)
    assert view["clock_minute"] == 690 and view["phase"] == "lunch"
    assert view["trading"] is False and view["fast_forward_at"] is not None
    assert view["next_event"] == {
        "kind": "reopen",
        "minute": 780,
        "at": view["next_event"]["at"],
    }
    db_save = _db_save(app, sid)
    assert view["fast_forward_at"] == (
        db_save.last_tick_at + timedelta(milliseconds=5000)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    order = registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": 100}
    )
    assert order.status_code == 409 and order.json()["code"] == "MARKET_CLOSED"

    tick_at_lunch = view["tick"]
    _backdate(app, sid, milliseconds=5000 + 10)  # 停留结束：跳到 12:59（+89 分钟，价格不变）
    jumped = _market(registered_client, sid)
    assert jumped["clock_minute"] == 779 and jumped["tick"] == tick_at_lunch + 89
    assert jumped["phase"] == "lunch"

    _backdate(app, sid, milliseconds=5000 + 10)  # 13:00 午后开盘
    assert _market(registered_client, sid)["clock_minute"] == 780
    assert _market(registered_client, sid)["phase"] == "afternoon"


def test_close_dwell_summary_and_next_day_rollover(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    for _ in range(6):  # 570 -> 689 -> 690 -> 779 -> 780 -> 899 -> 900
        _skip(registered_client, sid)
    view = _market(registered_client, sid)
    assert view["clock_minute"] == 900 and view["phase"] == "closed"
    assert view["fast_forward_at"] is not None and view["trading"] is False
    assert view["next_event"]["kind"] == "open"

    summary = registered_client.get(f"{SAVES}/{sid}/day-summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["status"] == "closed" and body["trading_day"] == 0
    assert body["holdings"] == [] and body["market"]["total"] == 385
    assert body["next_open_at"] is not None  # 15:00 停留中，下一次开盘即 next_event.at

    # 停留 15 秒后跳到次日 9:29，再过一个节奏单位到 9:30（换日）
    _backdate(app, sid, milliseconds=15_000 + 10)
    pre = _market(registered_client, sid)
    assert pre["clock_minute"] == 569 and pre["trading_day"] == 0 and pre["phase"] == "pre_open"

    _backdate(app, sid, milliseconds=5000 + 10)
    rolled = _market(registered_client, sid)
    assert rolled["clock_minute"] == 570 and rolled["trading_day"] == 1
    assert rolled["phase"] == "morning"

    with app.state.session_factory() as db:
        candles = db.scalar(
            select(func.count())
            .select_from(Candle)
            .where(Candle.save_id == uuid.UUID(sid), Candle.trading_day == 0)
        )
        snaps = db.scalar(
            select(func.count()).select_from(EquitySnapshot).where(
                EquitySnapshot.save_id == uuid.UUID(sid), EquitySnapshot.trading_day == 0
            )
        )
    assert candles == 385 and snaps == 1

    past = registered_client.get(f"{SAVES}/{sid}/day-summary?trading_day=0").json()
    assert past["status"] == "closed" and past["clock_rules"] == "v2"
    assert past["prev_equity_cents"] == past["equity_cents"] == 100_000_000
    assert past["day_pnl_cents"] == 0 and past["day_pnl_bp"] == 0
    assert past["holdings"] is None and past["next_open_at"] is None


def test_day_summary_range_and_ownership(registered_client: TestClient, app: FastAPI) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    ahead = registered_client.get(f"{SAVES}/{sid}/day-summary?trading_day=2")
    assert ahead.status_code == 422
    assert ahead.json()["code"] == "VALIDATION_ERROR"
    assert ahead.json()["params"] == {"field": "trading_day"}
    negative = registered_client.get(f"{SAVES}/{sid}/day-summary?trading_day=-1")
    assert negative.status_code == 422
    current = registered_client.get(f"{SAVES}/{sid}/day-summary").json()
    assert current["trading_day"] == 0 and current["status"] == "trading"
    assert current["holdings"] == [] and current["next_open_at"] is None
    assert registered_client.get(f"{SAVES}/{uuid.uuid4()}/day-summary").status_code == 404


def test_pause_at_close_freezes_dwell_and_resume_restarts_it(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    for _ in range(6):
        _skip(registered_client, sid)
    paused = registered_client.post(f"{SAVES}/{sid}/clock/pause").json()
    assert paused["paused"] is True and paused["fast_forward_at"] is None
    assert paused["next_event"]["at"] is None and paused["next_tick_at"] is None

    _backdate(app, sid, milliseconds=60_000)  # 暂停中不跳转
    assert _market(registered_client, sid)["clock_minute"] == 900

    resumed = registered_client.post(f"{SAVES}/{sid}/clock/resume").json()
    assert resumed["paused"] is False and resumed["fast_forward_at"] is not None
    assert resumed["clock_minute"] == 900


def test_offline_catch_up_is_capped_then_stops(registered_client: TestClient, app: FastAPI) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    _backdate(app, sid, hours=3)
    first = _market(registered_client, sid)
    with app.state.session_factory() as db:
        trading_tick = db.get(MarketState, uuid.UUID(sid)).payload["_meta"]["trading_tick"]
    assert trading_tick == 300  # TICK_CATCHUP_MAX 按交易 tick 计
    second = _market(registered_client, sid)
    assert second["tick"] == first["tick"]


def test_eight_skips_complete_one_trading_day(registered_client: TestClient, app: FastAPI) -> None:
    sid = _create(registered_client, clock_rules=2)["id"]
    expected = [689, 690, 779, 780, 899, 900, 569, 570]
    seen = [_skip(registered_client, sid)["clock_minute"] for _ in range(8)]
    assert seen == expected
    final = _market(registered_client, sid)
    assert final["trading_day"] == 1 and final["clock_minute"] == 570


def test_export_and_legacy_fields(registered_client: TestClient) -> None:
    save = _create(registered_client, clock_rules=2)
    export = registered_client.get(f"{SAVES}/{save['id']}/export").json()
    assert export["save"]["clock_rules"] == "v2"
    assert export["format_version"] == 2  # 01 §9.3：导出格式 v2（含 events_enabled）
