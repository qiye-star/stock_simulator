"""行情列表（分页/搜索/排序/自选过滤）与个股当日分时。"""

import base64
import itertools
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.models import Save
from stocksim.services.market import advance_ticks

SAVES = "/api/v1/saves"
REFRESH_SLOW = 60_000


def _save(client: TestClient, app: FastAPI, *, minute: int = 600) -> str:
    client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret1"})
    assert client.patch("/api/v1/me", json={"refresh_rate_ms": REFRESH_SLOW}).status_code == 200
    sid = client.post(SAVES, json={}).json()["id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = minute
        db.commit()
    return sid


def _step(app: FastAPI, sid: str, n: int = 1) -> None:
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        advance_ticks(db, save, n)


def _list(client: TestClient, sid: str, **params):
    resp = client.get(f"{SAVES}/{sid}/market", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _all_pages(client: TestClient, sid: str, limit: int, **params) -> list[dict]:
    items: list[dict] = []
    cursor = None
    for _ in range(1000):
        extra = {"cursor": cursor} if cursor else {}
        body = _list(client, sid, limit=limit, **params, **extra)
        items += body["stocks"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("分页未终止")


# ---------- 列表 ----------


def test_no_params_is_backward_compatible(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    body = _list(registered_client, sid)
    assert len(body["stocks"]) == 385
    assert body["total"] == 385 and body["next_cursor"] is None
    # 无参顺序为股票池顺序，且与显式 sort=code 的全集一致（集合相同）
    codes = [s["code"] for s in body["stocks"]]
    assert sorted(codes) == sorted(
        s["code"] for s in _list(registered_client, sid, sort="code")["stocks"]
    )


def test_pagination_covers_everything_once(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    first = _list(registered_client, sid, limit=50)
    assert len(first["stocks"]) == 50 and first["next_cursor"] and first["total"] == 385
    items = _all_pages(registered_client, sid, 50)
    codes = [s["code"] for s in items]
    assert len(codes) == 385 and len(set(codes)) == 385
    assert codes == sorted(codes)  # 默认按代码升序


def test_pagination_boundaries(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    # limit 恰好等于总数：一页取完，没有下一页
    body = _list(registered_client, sid, limit=385)
    assert len(body["stocks"]) == 385 and body["next_cursor"] is None
    # limit=500（上限）
    assert _list(registered_client, sid, limit=500)["next_cursor"] is None
    # limit=1 逐条
    one = _list(registered_client, sid, limit=1)
    assert len(one["stocks"]) == 1 and one["next_cursor"]
    # 末页不足 limit
    last = _all_pages(registered_client, sid, 100)
    assert len(last) == 385
    # 非法 limit
    for bad in (0, -1, 501, "abc"):
        resp = registered_client.get(f"{SAVES}/{sid}/market", params={"limit": bad})
        assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


def test_cursor_stable_when_market_unchanged(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    _step(app, sid, 3)  # 行情已变动，排序值各异
    full = _list(registered_client, sid, sort="change", order="desc")["stocks"]
    paged = _all_pages(registered_client, sid, 37, sort="change", order="desc")
    assert [s["code"] for s in paged] == [s["code"] for s in full]
    # 同一游标重复请求结果相同
    page1 = _list(registered_client, sid, limit=20, sort="change")
    again = _list(registered_client, sid, limit=20, sort="change", cursor=page1["next_cursor"])
    again2 = _list(registered_client, sid, limit=20, sort="change", cursor=page1["next_cursor"])
    assert again == again2


def test_cursor_survives_ticks_without_duplicates_for_code_sort(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _save(registered_client, app)
    p1 = _list(registered_client, sid, limit=100)
    _step(app, sid, 2)  # 翻页期间行情推进；按代码排序不受影响
    p2 = _list(registered_client, sid, limit=100, cursor=p1["next_cursor"])
    c1 = {s["code"] for s in p1["stocks"]}
    assert not c1 & {s["code"] for s in p2["stocks"]}
    assert max(c1) < min(s["code"] for s in p2["stocks"])


def test_cursor_validation(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    for bad in (
        "not-base64!!",
        "e30",
        base64.urlsafe_b64encode(b'["code","asc","x","1"]').decode(),
    ):
        resp = registered_client.get(f"{SAVES}/{sid}/market", params={"limit": 5, "cursor": bad})
        assert resp.status_code == 422, bad
        assert resp.json() == {"code": "VALIDATION_ERROR", "params": {"field": "cursor"}}
    # 游标与当前 sort 不一致
    cur = _list(registered_client, sid, limit=5, sort="volume")["next_cursor"]
    resp = registered_client.get(f"{SAVES}/{sid}/market", params={"limit": 5, "cursor": cur})
    assert resp.status_code == 422 and resp.json()["params"] == {"field": "cursor"}
    # 构造的合法游标：从 999998 之后开始
    forged = base64.urlsafe_b64encode(
        json.dumps(["code", "asc", 999998, "999998"]).encode()
    ).decode()
    body = _list(registered_client, sid, limit=5, cursor=forged)
    assert [s["code"] for s in body["stocks"]] == ["999999"] and body["next_cursor"] is None


def test_search_by_code_and_name(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    body = _list(registered_client, sid, q="600036")
    assert [s["code"] for s in body["stocks"]] == ["600036"] and body["total"] == 1
    name = body["stocks"][0]["name"]
    by_name = _list(registered_client, sid, q=name[:2].upper())
    assert "600036" in {s["code"] for s in by_name["stocks"]}
    assert all(
        name[:2].casefold() in s["name"].casefold() or name[:2] in s["code"]
        for s in by_name["stocks"]
    )
    prefix = _list(registered_client, sid, q="6000")
    assert prefix["total"] == len(prefix["stocks"]) > 1
    assert all("6000" in s["code"] or "6000" in s["name"] for s in prefix["stocks"])
    empty = _list(registered_client, sid, q="不存在的名字zzz")
    assert empty["stocks"] == [] and empty["total"] == 0 and empty["next_cursor"] is None
    # 搜索 + 分页：total 为过滤后总数
    page = _list(registered_client, sid, q="6000", limit=2)
    assert page["total"] == prefix["total"] and len(page["stocks"]) == 2
    # 空白关键词等同无关键词
    assert _list(registered_client, sid, q="  ")["total"] == 385
    too_long = registered_client.get(f"{SAVES}/{sid}/market", params={"q": "x" * 33})
    assert too_long.status_code == 422


def test_sorting(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    _step(app, sid, 5)
    for sort, field in (("change", "change_bp"), ("volume", "volume"), ("price", "price_cents")):
        desc = _list(registered_client, sid, sort=sort)["stocks"]  # 默认降序
        vals = [s[field] for s in desc]
        assert vals == sorted(vals, reverse=True), sort
        asc = _list(registered_client, sid, sort=sort, order="asc")["stocks"]
        avals = [s[field] for s in asc]
        assert avals == sorted(avals), sort
        # 并列时按代码升序
        for a, b in itertools.pairwise(desc):
            if a[field] == b[field]:
                assert a["code"] < b["code"]
    codes_desc = [
        s["code"] for s in _list(registered_client, sid, sort="code", order="desc")["stocks"]
    ]
    assert codes_desc == sorted(codes_desc, reverse=True)
    bad = registered_client.get(f"{SAVES}/{sid}/market", params={"sort": "nope"})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    bad = registered_client.get(f"{SAVES}/{sid}/market", params={"order": "up"})
    assert bad.status_code == 422


def test_watchlist_filter(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    assert _list(registered_client, sid, watchlisted="true")["stocks"] == []
    for code in ("600036", "000002"):
        resp = registered_client.put(f"{SAVES}/{sid}/watchlist/{code}")
        assert resp.status_code in (200, 201, 204), resp.text
    body = _list(registered_client, sid, watchlisted="true", sort="code")
    assert [s["code"] for s in body["stocks"]] == ["000002", "600036"]
    assert all(s["watchlisted"] for s in body["stocks"]) and body["total"] == 2
    rest = _list(registered_client, sid, watchlisted="false")
    assert rest["total"] == 383
    both = _list(registered_client, sid, watchlisted="true", q="600036")
    assert [s["code"] for s in both["stocks"]] == ["600036"]


def test_market_list_permissions(registered_client: TestClient, app: FastAPI, settings) -> None:
    sid = _save(registered_client, app)
    with TestClient(app) as other:
        assert other.get(f"{SAVES}/{sid}/market", params={"limit": 5}).status_code == 401
        other.post("/api/v1/auth/register", json={"username": "bob", "password": "secret1"})
        resp = other.get(f"{SAVES}/{sid}/market", params={"limit": 5})
        assert resp.status_code == 404 and resp.json()["code"] == "SAVE_NOT_FOUND"
        resp = other.get(f"{SAVES}/{sid}/market/600036/intraday")
        assert resp.status_code == 404 and resp.json()["code"] == "SAVE_NOT_FOUND"


# ---------- 分时 ----------


def _intraday(client: TestClient, sid: str, code: str = "600036") -> dict:
    resp = client.get(f"{SAVES}/{sid}/market/{code}/intraday")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _quote(client: TestClient, sid: str, code: str) -> dict:
    return client.get(f"{SAVES}/{sid}/market/{code}").json()


def test_intraday_before_first_tick_is_empty(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    body = _intraday(registered_client, sid)
    q = _quote(registered_client, sid, "600036")
    assert body["points"] == [] and body["exact"] is True
    assert body["open_cents"] == q["open_cents"] == q["prev_close_cents"]
    assert body["trading_day"] == 0 and body["clock_minute"] == 600


def test_intraday_matches_every_step_across_lunch_and_rollover(
    registered_client: TestClient, app: FastAPI
) -> None:
    """逐 tick 记录真实价格/量，与重放结果逐点一致；覆盖午休（无点）与换日（点数重置）。"""
    sid = _save(registered_client, app, minute=670)  # 11:10，距午休 20 分钟
    seen: dict[int, tuple[int, int]] = {}  # tick -> (price, volume)
    day_of: dict[int, int] = {}
    minute_of: dict[int, int] = {}
    for _ in range(60):
        _step(app, sid)
        q = _quote(registered_client, sid, "600036")
        clock = _list(registered_client, sid, limit=1)
        seen[clock["tick"]] = (q["price_cents"], q["volume"])
        day_of[clock["tick"]] = clock["trading_day"]
        minute_of[clock["tick"]] = clock["clock_minute"]
        body = _intraday(registered_client, sid)
        assert body["exact"] is True
        pts = body["points"]
        assert pts, "已有交易 tick 时必有点"
        assert pts == sorted(pts, key=lambda p: p["tick"])
        # 终点即当前价；每个点都与当时的真实价格一致（同日内）
        assert (pts[-1]["price_cents"], pts[-1]["volume"]) == (q["price_cents"], q["volume"])
        for p in pts:
            if p["tick"] in seen and day_of[p["tick"]] == body["trading_day"]:
                assert (p["price_cents"], p["volume"]) == seen[p["tick"]]
                assert p["minute"] == minute_of[p["tick"]]
        minutes = [p["minute"] for p in pts]
        assert all(570 <= m <= 690 or 780 <= m <= 900 for m in minutes)  # 休市无点
    # 当日点数不超过 20，换日后重新累积
    assert len(pts) <= 20
    assert max(day_of.values()) >= 1


def test_intraday_covers_skipped_minutes(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app, minute=575)
    for _ in range(3):
        _step(app, sid)
    resp = registered_client.post(f"{SAVES}/{sid}/clock/skip")
    assert resp.status_code == 200, resp.text
    after = _intraday(registered_client, sid)
    # 跳过 575→689 之间的每个交易分钟都有点（不是线性插值：点数与 tick 数一一对应）
    assert after["exact"] is True
    ticks = [p["tick"] for p in after["points"]]
    assert ticks == list(range(ticks[0], ticks[0] + len(ticks)))
    assert resp.json()["skipped_ticks"] > 20  # 跳过的分钟数超过一个交易日，点数仍只取当日
    assert 1 <= len(after["points"]) <= 20
    assert (
        after["points"][-1]["price_cents"]
        == _quote(registered_client, sid, "600036")["price_cents"]
    )


def test_intraday_after_hours_keeps_today(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app, minute=895)
    _step(app, sid, 6)  # 到 15:01 之后：15:00 为最后一个交易分钟
    body = _intraday(registered_client, sid)
    assert body["clock_minute"] == 901 and body["exact"] is True
    assert body["points"][-1]["minute"] == 900
    assert len(body["points"]) == 5  # 896..900 五个交易分钟，901 休市


def test_intraday_debug_clock_degrades(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    _step(app, sid, 4)
    with app.state.session_factory() as db:  # 模拟 debug 改时钟：minute 与 tick 不再自洽
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = 100  # 非交易分钟，倒推凑不够 tick
        db.commit()
    body = _intraday(registered_client, sid)
    q = _quote(registered_client, sid, "600036")
    assert body["exact"] is False and len(body["points"]) == 1
    assert body["points"][0]["price_cents"] == q["price_cents"]


def test_intraday_unknown_stock_and_validation(registered_client: TestClient, app: FastAPI) -> None:
    sid = _save(registered_client, app)
    resp = registered_client.get(f"{SAVES}/{sid}/market/999998/intraday")
    assert resp.status_code == 404
    assert resp.json() == {"code": "STOCK_NOT_FOUND", "params": {"code": "999998"}}
    resp = registered_client.get(f"{SAVES}/{uuid.uuid4()}/market/600036/intraday")
    assert resp.status_code == 404 and resp.json()["code"] == "SAVE_NOT_FOUND"
