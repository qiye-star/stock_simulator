"""事件行情接口与行情耦合（01 §12.2）：开关、公开形态、保密、分页、暂停钩子、漂移逐位重放。

存档时钟版本：默认 v1（API 不传 clock_rules）；v2 显式 `clock_rules=2`。v2 每个交易日都有重大事件。
"""

import copy
import re
import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import advance_minute, is_trading_time
from stocksim.domain.market_engine import advance
from stocksim.models import MarketState, Save
from stocksim.services import event_hooks
from stocksim.services import events as events_service
from stocksim.services.market import (
    advance_ticks,
    advance_to_now,
    decode_state,
    encode_payload,
)

SAVES = "/api/v1/saves"
CODE = "600036"
NEWS_ID_RE = re.compile(r"^e\d{1,9}-\d{1,2}:(precursor|publish|confirm|deny)$")
EVENT_OUT_KEYS = {
    "event_id", "trading_day", "slot", "kind", "subtype", "scope", "source_industry",
    "source_code", "major", "sentiment", "title", "first_seen_trading_tick",
    "publish_trading_tick", "phase", "rumor_status", "resolved_trading_tick",
}  # fmt: skip
NEWS_OUT_KEYS = {
    "news_id", "event_id", "stage", "kind", "subtype", "scope", "major", "sentiment", "title",
    "industry", "code", "stock_name", "trading_day", "trading_tick", "day_offset", "tick",
    "clock_minute",
}  # fmt: skip
# 任何位置都不得出现的服务端隐藏字段（01 §1.8）
HIDDEN_KEYS = {"magnitude_ppm", "knots", "expectation", "channel", "impacts", "rumor", "truth"}


def _create(client: TestClient, *, v2: bool, events: bool, name: str = "ev") -> str:
    body: dict = {"name": name, "events_enabled": events}
    if v2:
        body["clock_rules"] = 2
    resp = client.post(SAVES, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _skip(client: TestClient, sid: str) -> dict:
    resp = client.post(f"{SAVES}/{sid}/clock/skip")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _walk_keys(obj, found: set[str]) -> None:
    if isinstance(obj, dict):
        found.update(obj.keys())
        for v in obj.values():
            _walk_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_keys(v, found)


def _assert_no_hidden(body) -> None:
    keys: set[str] = set()
    _walk_keys(body, keys)
    assert not (keys & HIDDEN_KEYS), keys & HIDDEN_KEYS


@pytest.fixture
def hooks():
    event_hooks.clear_hooks()
    yield event_hooks
    event_hooks.clear_hooks()


def _save_row(app: FastAPI, sid: str) -> Save:
    with app.state.session_factory() as db:
        return db.get(Save, uuid.UUID(sid))


def _cur_tt(app: FastAPI, sid: str) -> int:
    from stocksim.services.market import current_trading_tick

    with app.state.session_factory() as db:
        return current_trading_tick(db, db.get(Save, uuid.UUID(sid)))


def _advance_until_tt(app: FastAPI, sid: str, target: int) -> None:
    """逐分钟推进直到交易 tick 达到 target（v1 开局分钟随机，交易分钟不连续）。"""
    from stocksim.services.market import current_trading_tick

    for _ in range(10_000):
        with app.state.session_factory() as db:
            save = db.get(Save, uuid.UUID(sid))
            if current_trading_tick(db, save) >= target:
                return
            advance_ticks(db, save, 1)
    raise AssertionError("trading tick target not reached")


def _payload(app: FastAPI, sid: str) -> dict:
    with app.state.session_factory() as db:
        return copy.deepcopy(db.get(MarketState, uuid.UUID(sid)).payload)


# ---------------------------------------------------------------- 开关与关闭时的行为


@pytest.mark.parametrize("v2", [False, True], ids=["v1", "v2"])
def test_closed_save_event_endpoints_return_409(registered_client: TestClient, v2: bool) -> None:
    client = registered_client
    sid = _create(client, v2=v2, events=False)
    _skip(client, sid)
    for path in (
        f"{SAVES}/{sid}/news",
        f"{SAVES}/{sid}/events",
        f"{SAVES}/{sid}/events/e1-0",
        f"{SAVES}/{sid}/market/{CODE}/event-marks",
    ):
        resp = client.get(path)
        assert resp.status_code == 409, path
        assert resp.json()["code"] == "EVENTS_DISABLED", path
        assert resp.json()["params"] == {"save_id": sid}


@pytest.mark.parametrize("v2", [False, True], ids=["v1", "v2"])
def test_supply_chain_is_public_for_closed_saves(registered_client: TestClient, v2: bool) -> None:
    client = registered_client
    sid = _create(client, v2=v2, events=False)
    body = client.get(f"{SAVES}/{sid}/supply-chain").json()
    assert len(body["nodes"]) == 82
    assert body["edges"] and all(e["strength"] is None for e in body["edges"])
    assert all(e["lag_days"] is None and e["revealed_level"] == 0 for e in body["edges"])


def test_flags_and_immutability(registered_client: TestClient) -> None:
    client = registered_client
    sid_off = _create(client, v2=False, events=False)
    sid_on = _create(client, v2=True, events=True)
    assert client.get(f"{SAVES}/{sid_off}").json()["events_enabled"] is False
    assert client.get(f"{SAVES}/{sid_on}").json()["events_enabled"] is True
    # 开关只在创建时设置；PATCH 只改名，不得修改开关
    client.patch(f"{SAVES}/{sid_on}", json={"name": "renamed", "events_enabled": False})
    body = client.get(f"{SAVES}/{sid_on}").json()
    assert body["events_enabled"] is True and body["name"] == "renamed"


def test_closed_save_never_enters_event_services(
    registered_client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关闭事件模式的存档推进时，events 服务的任何入口都不得被调用。"""

    def boom(*_args, **_kwargs):
        raise AssertionError("event service must not be used by a closed save")

    client = registered_client
    sid = _create(client, v2=True, events=False)
    monkeypatch.setattr(events_service, "drift_for", boom)
    monkeypatch.setattr(events_service, "news_for_tick", boom)
    for _ in range(4):
        _skip(client, sid)
    assert client.get(f"{SAVES}/{sid}/market/{CODE}/intraday").status_code == 200
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        assert advance_ticks(db, save, 30) == 30


# ---------------------------------------------------------------- 行情逐位重放（漂移与截停）


def _replay_matches(app: FastAPI, sid: str, *, with_drift: bool) -> tuple[dict, dict]:
    """从存档创建时的初始 payload 出发，逐分钟重放 domain.advance，返回 (重放结果, 库内 payload)。

    仅覆盖同一交易日内（不跨换日），因此 prior 窗口为 None 即足够，与 _run_ticks 一致。
    """
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        row = db.get(MarketState, uuid.UUID(sid))
        init_payload, init = _INIT[sid]
        init_payload = copy.deepcopy(init_payload)
        final_tick, final_minute = save.tick, save.clock_minute
        stored = copy.deepcopy(row.payload)
        rules, seed = save.clock_rules, save.market_seed
        as_of = date.fromisoformat(stored["_meta"]["as_of"])
        state = decode_state(init_payload, None, rules)
        minute, tick = init
        for _ in range(final_tick - init[1]):
            minute = advance_minute(minute)
            tick += 1
            if not is_trading_time(minute):
                continue
            drift = None
            if with_drift:
                drift = events_service.drift_for(save, state["trading_tick"] + 1)
            state = advance(state, seed, tick, minute, drift=drift, rules=rules)
        assert minute == final_minute
        return encode_payload(state, as_of, rules), stored


_INIT: dict[str, tuple[dict, tuple[int, int]]] = {}  # sid -> (初始 payload, (minute, tick))


def _record_init(app: FastAPI, sid: str) -> None:
    """创建存档后立即调用：记下初始 payload 与时钟，之后用于逐分钟重放。"""
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        row = db.get(MarketState, uuid.UUID(sid))
        _INIT[sid] = (copy.deepcopy(row.payload), (save.clock_minute, save.tick))


def test_v2_drift_replay_is_bit_exact_and_drift_matters(
    registered_client: TestClient, app: FastAPI
) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    _record_init(app, sid)
    for _ in range(6):  # 570 → 900，跨午休与收盘，不跨换日
        _skip(client, sid)
    assert _payload(app, sid)["_meta"]["as_of"]  # 库内有行情
    replay, stored = _replay_matches(app, sid, with_drift=True)
    assert replay == stored
    no_drift, _ = _replay_matches(app, sid, with_drift=False)
    assert no_drift != stored  # 事件确实改变了走势


def test_v1_drift_replay_is_bit_exact(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = _create(client, v2=False, events=True)
    _record_init(app, sid)
    _advance_until_tt(app, sid, 19)  # 不跨 20 tick 换日
    replay, stored = _replay_matches(app, sid, with_drift=True)
    assert replay == stored
    no_drift, _ = _replay_matches(app, sid, with_drift=False)
    assert no_drift != stored


@pytest.mark.parametrize("v2", [False, True], ids=["v1", "v2"])
def test_intraday_stays_exact_with_events_enabled(registered_client: TestClient, v2: bool) -> None:
    client = registered_client
    sid = _create(client, v2=v2, events=True)
    steps = 10 if v2 else 6
    for _ in range(steps):
        _skip(client, sid)
        data = client.get(f"{SAVES}/{sid}/market/{CODE}/intraday").json()
        assert data["exact"] is True
        if data["points"]:
            market = client.get(f"{SAVES}/{sid}/market/{CODE}").json()
            assert data["points"][-1]["price_cents"] == market["price_cents"]


# ---------------------------------------------------------------- 公开形态、保密与分页


@pytest.mark.parametrize("v2", [False, True], ids=["v1", "v2"])
def test_public_news_and_events_shape(
    registered_client: TestClient, app: FastAPI, v2: bool
) -> None:
    client = registered_client
    sid = _create(client, v2=v2, events=True)
    if v2:
        for _ in range(16):  # 两个交易日
            _skip(client, sid)
    else:
        # v1 重大事件周期为 12 个交易日（240 个交易 tick）；v1 开局分钟随机，按交易 tick 推进到 240
        _advance_until_tt(app, sid, 240)
    cur_news = client.get(f"{SAVES}/{sid}/news?limit=100").json()
    items = cur_news["items"]
    assert items, "events-enabled save should have published news"
    for item in items:
        assert set(item) == NEWS_OUT_KEYS
        assert NEWS_ID_RE.match(item["news_id"])
        assert item["news_id"].startswith(item["event_id"] + ":")
    _assert_no_hidden(cur_news)
    assert any(i["major"] for i in items)
    listed = client.get(f"{SAVES}/{sid}/events?limit=100").json()
    assert listed["items"]
    for ev in listed["items"]:
        assert set(ev) == EVENT_OUT_KEYS
    _assert_no_hidden(listed)
    # 详情：已发布事件返回 200，传导回放 hop 0 最先到达，且只含已到达节点
    cur_tt = _cur_tt(app, sid)
    # 取一个已发布、非市场级的事件（有传导），检查详情
    published = [e for e in listed["items"] if e["publish_trading_tick"] is not None]
    detail_id = next(e["event_id"] for e in published if e["scope"] != "market")
    detail = client.get(f"{SAVES}/{sid}/events/{detail_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    _assert_no_hidden(body)
    assert body["news"] and all(n["trading_tick"] <= cur_tt for n in body["news"])
    assert body["propagation"][0]["hop"] == 0
    arrivals = [p["arrived_trading_tick"] for p in body["propagation"]]
    assert arrivals == sorted(arrivals) and max(arrivals) <= cur_tt


def test_unpublished_or_unknown_event_is_404(registered_client: TestClient) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    for event_id in ("e999-0", "e5-3", "bogus"):  # 未来日或格式非法
        resp = client.get(f"{SAVES}/{sid}/events/{event_id}")
        assert resp.status_code == 404, event_id
        assert resp.json()["code"] == "EVENT_NOT_FOUND"


def test_news_pagination_is_complete_and_duplicate_free(registered_client: TestClient) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    for _ in range(12):
        _skip(client, sid)
    full = client.get(f"{SAVES}/{sid}/news?limit=100").json()["items"]
    ids: list[str] = []
    cursor = None
    for _ in range(200):
        query = "?limit=4" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(f"{SAVES}/{sid}/news{query}").json()
        ids.extend(i["news_id"] for i in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids))
    assert ids == [i["news_id"] for i in full][: len(ids)]
    assert set(ids) == {i["news_id"] for i in full} or len(full) == 100


def test_news_filters_and_validation(registered_client: TestClient) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    for _ in range(8):
        _skip(client, sid)
    majors = client.get(f"{SAVES}/{sid}/news?limit=100&major=true").json()["items"]
    assert majors and all(i["major"] for i in majors)
    stock_news = client.get(f"{SAVES}/{sid}/news?limit=100&code={CODE}").json()["items"]
    for item in stock_news:
        assert item["scope"] == "market" or item["code"] == CODE or item["industry"] == "银行"
    assert client.get(f"{SAVES}/{sid}/news?cursor=!!!").status_code == 422
    bad = client.get(f"{SAVES}/{sid}/news?industry=不存在的行业")
    assert bad.status_code == 422 and bad.json()["params"] == {"field": "industry"}
    assert client.get(f"{SAVES}/{sid}/news?limit=0").status_code == 422


def test_other_users_cannot_read_event_endpoints(
    app: FastAPI, registered_client: TestClient
) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    bob = TestClient(app)
    assert (
        bob.post(
            "/api/v1/auth/register", json={"username": "bob", "password": "secret1"}
        ).status_code
        == 201
    )
    resp = bob.get(f"{SAVES}/{sid}/news")
    assert resp.status_code == 404 and resp.json()["code"] == "SAVE_NOT_FOUND"


# ---------------------------------------------------------------- 产业链揭示与情报服务


def test_supply_chain_reveal_provider_levels(
    registered_client: TestClient, app: FastAPI, hooks
) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    first = client.get(f"{SAVES}/{sid}/supply-chain").json()["edges"][0]["id"]
    hooks.register_reveal_provider(lambda _db, _save: {first: 2})
    edges = {e["id"]: e for e in client.get(f"{SAVES}/{sid}/supply-chain").json()["edges"]}
    assert edges[first]["revealed_level"] == 2
    assert edges[first]["strength"] in (1, 2, 3) and edges[first]["lag_days"] is not None
    others = [e for k, e in edges.items() if k != first]
    assert all(e["strength"] is None and e["lag_days"] is None for e in others)


def test_reveal_edge_service_levels_and_errors(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    edge_id = client.get(f"{SAVES}/{sid}/supply-chain").json()["edges"][0]["id"]
    save = _save_row(app, sid)
    one = events_service.reveal_edge(save, edge_id, 1)
    assert one["strength"] in (1, 2, 3) and one["lag_days"] is None and one["level"] == 1
    two = events_service.reveal_edge(save, edge_id, 2)
    assert two["lag_days"] is not None and two["level"] == 2
    with pytest.raises(AppError) as exc:
        events_service.reveal_edge(save, "不存在>边", 1)
    assert exc.value.code == ErrorCode.SUPPLY_EDGE_NOT_FOUND
    off = _create(client, v2=True, events=False)
    with pytest.raises(AppError) as exc:
        events_service.reveal_edge(_save_row(app, off), edge_id, 1)
    assert exc.value.code == ErrorCode.EVENTS_DISABLED


def test_rumor_hint_service(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    rumors: list[dict] = []
    listed: list[dict] = []
    for _ in range(200):  # 每次跳过 1/8 个交易日，直到出现已发布的传闻（约 1 个交易日内必现）
        listed = client.get(f"{SAVES}/{sid}/events?limit=100").json()["items"]
        rumors = [e for e in listed if e["kind"] == "rumor"]
        if rumors and any(e["kind"] != "rumor" for e in listed):
            break
        _skip(client, sid)
    assert rumors, "a published rumor should appear within 200 skips"
    save = _save_row(app, sid)
    with app.state.session_factory() as db:
        hint = events_service.rumor_hint(db, save, rumors[0]["event_id"])
        assert hint["hint"] in ("likely_true", "likely_false")
        if rumors[0]["rumor_status"] == "unresolved":
            assert hint["accuracy_pct"] == 80
        with pytest.raises(AppError) as exc:
            non_rumor = next(e for e in listed if e["kind"] != "rumor")
            events_service.rumor_hint(db, save, non_rumor["event_id"])
        assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_rumor_hint_visibility_matches_list_for_precursor_expectation(
    registered_client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归：priced_in 事件在铺垫快讯发布后（first_seen ≤ 当前、未正式发布）即在列表与详情可见，
    rumor_hint 的可见性判定必须与之一致：对可见的非传闻返回 not_rumor（422），
    而不是 EVENT_NOT_FOUND。

    固定种子 2：第 1 日第 2 槽为 priced_in，铺垫快讯 tick 185，正式发布 tick 453。
    只调用服务层（不走 HTTP，不触发墙钟补推），结果与时间无关。
    """
    monkeypatch.setattr("stocksim.services.saves.secrets.randbits", lambda _k: 2)
    sid = _create(registered_client, v2=True, events=True)
    save = _save_row(app, sid)
    assert save.market_seed == 2
    event_id = "e1-2"
    _advance_until_tt(app, sid, 185)
    with app.state.session_factory() as db:
        save = _save_row(app, sid)
        page = events_service.events_list(
            db, save, limit=100, cursor=None, major=None, code=None,
            industry=None, phase=None, lang="zh-CN",
        )  # fmt: skip
        item = next(e for e in page["items"] if e["event_id"] == event_id)
        assert item["kind"] != "rumor"
        assert item["phase"] == "expected" and item["publish_trading_tick"] is None
        detail = events_service.event_detail(db, save, event_id, "zh-CN")
        assert detail["event_id"] == event_id
        with pytest.raises(AppError) as exc:
            events_service.rumor_hint(db, save, event_id)
        assert exc.value.code == ErrorCode.VALIDATION_ERROR
        assert exc.value.params == {"field": "event_id", "reason": "not_rumor"}


def test_event_marks_and_industry_change(registered_client: TestClient, app: FastAPI) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    for _ in range(6):
        _skip(client, sid)
    body = client.get(f"{SAVES}/{sid}/market/{CODE}/event-marks?days=10").json()
    assert body["code"] == CODE
    cur = _cur_tt(app, sid)
    for m in body["items"]:
        assert m["role"] in ("source", "propagated", "market")
        assert m["trading_tick"] <= cur
    assert client.get(f"{SAVES}/{sid}/market/000000/event-marks").status_code == 404


# ---------------------------------------------------------------- 发布暂停钩子


def test_publish_hook_pauses_once_and_resumes_without_repeat(
    registered_client: TestClient, app: FastAPI, hooks
) -> None:
    client = registered_client
    sid = _create(client, v2=True, events=True)
    seen: list[int] = []

    def pause_on_major(_db, ctx) -> bool:
        if any(n.major for n in ctx.news):
            seen.append(ctx.trading_tick)
            return True
        return False

    hooks.register_publish_hook(pause_on_major)
    save = _save_row(app, sid)
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        done = advance_ticks(db, save, 500)
    assert done < 500 and len(seen) == 1
    assert _save_row(app, sid).paused is True
    stop_tt = seen[0]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        assert advance_to_now(db, save) == 0  # 暂停期间墙钟不推进
    client.post(f"{SAVES}/{sid}/clock/resume")
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        advance_ticks(db, save, 300)
    assert len(seen) >= 1 and all(t > stop_tt for t in seen[1:])
    assert len(set(seen)) == len(seen)


def test_publish_hook_runs_for_each_publish_and_not_on_disabled_saves(
    registered_client: TestClient, app: FastAPI, hooks
) -> None:
    client = registered_client
    off = _create(client, v2=True, events=False)
    calls: list[int] = []
    hooks.register_publish_hook(lambda _db, ctx: calls.append(ctx.trading_tick) or False)
    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(off)), 300)
    assert calls == []
    on = _create(client, v2=True, events=True)
    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(on)), 300)
    assert calls and calls == sorted(calls) and len(set(calls)) == len(calls)


def test_reset_market_runs_reset_hooks(settings, migrated: str, hooks) -> None:
    from stocksim.main import create_app
    from stocksim.services.seed import seed_stock_table

    app = create_app(settings.model_copy(update={"ENABLE_DEBUG_API": True}))
    with app.state.session_factory() as db:
        seed_stock_table(db)
    resets: list[str] = []
    hooks.register_reset_hook(lambda _db, save: resets.append(str(save.id)))
    client = TestClient(app)
    with client:
        assert (
            client.post(
                "/api/v1/auth/register", json={"username": "alice", "password": "secret1"}
            ).status_code
            == 201
        )
        sid = _create(client, v2=True, events=True)
        resp = client.post(f"/api/v1/saves/{sid}/debug/reset-market")
        assert resp.status_code == 200, resp.text
    assert resets == [sid]
