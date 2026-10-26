#!/usr/bin/env python3
"""端到端 HTTP 冒烟脚本：只用标准库（urllib + http.cookiejar），逐步打印 PASS/FAIL。

用法：
    BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py

流程：注册随机用户 -> 建存档 -> 读行情 -> 买入 100 股 -> T+1 卖出应被拒绝 ->
持仓 -> 加自选 -> 建自动交易条件单 -> 导出存档 -> v2 时钟一交易日循环 -> v2
事件存档（快讯/详情/关闭 409）。任一步失败则以非零码退出。
若开局不在交易时段，会尝试调用 debug/time（需 ENABLE_DEBUG_API=true），否则该步记为 FAIL。

每日挑战场景 s_challenge 与预测市场场景 s_prediction_market 只在 E2E_CHALLENGE=1
时执行（默认跳过并打印 SKIP），
服务端需 CHALLENGE_SCHEDULE=compact CHALLENGE_MIN_ACCOUNT_AGE_HOURS=0 ENABLE_DEBUG_API=true
CHALLENGE_SEED_KEY=<任意串>。预测市场场景使用明天（北京时间）的挑战日期，与 s_challenge 互不影响。
"""

from __future__ import annotations

import functools
import hashlib
import http.cookiejar
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

BASE_URL = os.environ.get("BASE_URL", "http://localhost:18000").rstrip("/")
API = f"{BASE_URL}/api/v1"
TIMEOUT = 15

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_results: list[tuple[str, bool, str]] = []


class HttpError(Exception):
    def __init__(self, status: int, body: dict[str, Any] | None) -> None:
        super().__init__(f"HTTP {status} {body}")
        self.status = status
        self.body = body or {}

    @property
    def code(self) -> str:
        return str(self.body.get("code", ""))


def call(
    method: str,
    path: str,
    body: Any = None,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    headers_extra: dict[str, str] | None = None,
) -> Any:
    data = None
    headers = {"Accept": "application/json", **(headers_extra or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with (opener or _opener).open(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = {"raw": raw[:200].decode("utf-8", "replace")}
        raise HttpError(exc.code, parsed) from None


def step(name: str):
    """把步骤函数包装为：捕获异常、记录 PASS/FAIL；返回 False 表示失败（后续步骤跳过）。"""

    def deco(fn):
        @functools.wraps(fn)
        def run(state: dict[str, Any]) -> bool:
            try:
                detail = fn(state) or "ok"
                _results.append((name, True, str(detail)))
                return True
            except Exception as exc:  # 冒烟脚本需要捕获一切并记录
                _results.append((name, False, f"{type(exc).__name__}: {exc}"))
                return False

        run.step_name = name  # type: ignore[attr-defined]
        return run

    return deco


def expect(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


@step("register random user")
def s_register(state):
    username = "smoke" + secrets.token_hex(3)  # 字符集与长度满足后端规则
    password = "pw" + secrets.token_hex(4)
    user = call("POST", "/auth/register", {"username": username, "password": password})
    expect(user.get("username") == username, "username not echoed")
    state["username"] = username
    return f"user={username}"


@step("create save")
def s_create_save(state):
    save = call("POST", "/saves", {"name": "smoke", "initial_fund_cents": 100_000_000})
    expect(save.get("cash_cents") == 100_000_000, f"cash {save.get('cash_cents')}")
    state["save_id"] = save["id"]
    return f"save={save['id']}"


@step("read market")
def s_market(state):
    market = call("GET", f"/saves/{state['save_id']}/market")
    stocks = market.get("stocks") or []
    expect(len(stocks) > 0, "no stocks in market")
    if not _trading(market):
        _ensure_trading_time(state)
        market = call("GET", f"/saves/{state['save_id']}/market")
    quote = next((q for q in market["stocks"] if q.get("price_cents", 0) > 0), None)
    expect(quote is not None, "no priced stock")
    state["code"] = quote["code"]
    state["price_cents"] = quote["price_cents"]
    detail = call("GET", f"/saves/{state['save_id']}/market/{quote['code']}")
    expect("order_book" in detail and "candles" in detail, "detail shape")
    return f"{len(stocks)} stocks, code={quote['code']}"


def _trading(market: dict[str, Any]) -> bool:
    minute = market.get("clock_minute", -1)
    return (570 <= minute <= 690) or (780 <= minute <= 900)


def _ensure_trading_time(state) -> None:
    """开局不在交易时段时，尝试 debug/time 拨到 10:00（需要 ENABLE_DEBUG_API=true）。"""
    try:
        call("POST", f"/saves/{state['save_id']}/debug/time", {"minute_of_day": 600})
    except HttpError as exc:
        raise AssertionError(
            f"market closed and debug time unavailable ({exc.code}); "
            "start the server with ENABLE_DEBUG_API=true or retry during trading hours"
        ) from None


@step("buy 100 shares at market")
def s_buy(state):
    res = call(
        "POST",
        f"/saves/{state['save_id']}/orders",
        {"code": state["code"], "side": "buy", "quantity": 100, "price_type": "market"},
    )
    expect(res["trade"]["quantity"] == 100, "quantity")
    expect(res["trade"]["side"] == "buy", "side")
    state["cash_after_buy"] = res["cash_cents"]
    return f"fill={res['trade']['price_cents']} cash={res['cash_cents']}"


@step("T+1 sell is blocked the same day")
def s_t1(state):
    try:
        call(
            "POST",
            f"/saves/{state['save_id']}/orders",
            {"code": state["code"], "side": "sell", "quantity": 100, "price_type": "market"},
        )
    except HttpError as exc:
        expect(exc.code == "TRADE_T1_SELL_BLOCKED", f"unexpected code {exc.code}")
        return exc.code
    raise AssertionError("sell was not blocked")


@step("portfolio reflects holding with 0 sellable")
def s_portfolio(state):
    pf = call("GET", f"/saves/{state['save_id']}/portfolio")
    holding = next((h for h in pf["holdings"] if h["code"] == state["code"]), None)
    expect(holding is not None, "holding missing")
    expect(holding["quantity"] == 100, f"quantity {holding['quantity']}")
    expect(holding["sellable_quantity"] == 0, f"sellable {holding['sellable_quantity']}")
    expect(pf["cash_cents"] == state["cash_after_buy"], "cash mismatch with order response")
    return f"equity={pf['equity_cents']}"


@step("add watchlist item")
def s_watch(state):
    call("PUT", f"/saves/{state['save_id']}/watchlist/{state['code']}")
    market = call("GET", f"/saves/{state['save_id']}/market")
    quote = next(q for q in market["stocks"] if q["code"] == state["code"])
    expect(quote["watchlisted"] is True, "watchlisted flag not set")


@step("create auto-trade config")
def s_auto(state):
    cfg = call(
        "POST",
        f"/saves/{state['save_id']}/auto-trade/configs",
        {
            "code": state["code"],
            "direction": "sell",
            "condition_type": "percentage",
            "condition_operator": "above",
            "condition_percent": 5.0,
            "quantity": 100,
            "price_type": "market",
            "stop_loss_percent": 3.0,
        },
    )
    expect(cfg["condition_percent"] == 5.0, "condition_percent round-trip")
    items = call("GET", f"/saves/{state['save_id']}/auto-trade/configs")["items"]
    expect(any(i["id"] == cfg["id"] for i in items), "config not listed")
    status = call("GET", f"/saves/{state['save_id']}/auto-trade/status")
    expect("total_trades" in status, "status shape")
    return f"config={cfg['id']}"


@step("export save")
def s_export(state):
    exported = call("GET", f"/saves/{state['save_id']}/export")
    expect(exported.get("format") and exported.get("save"), "export shape")
    return f"format={exported['format']}"


@step("clock v2 day cycle")
def s_clock_v2(state):
    """v2 存档：一交易日 8 次跳过（11:30 停留、15:00 收盘小结、次日 9:30 换日），再核对节奏档。"""
    save = call("POST", "/saves", {"name": "v2", "clock_rules": 2})
    expect(save.get("clock_rules") == "v2", f"clock_rules {save.get('clock_rules')}")
    sid = save["id"]
    view = call("GET", f"/saves/{sid}/market?limit=1")
    expect(view.get("clock_minute") == 570 and view.get("phase") == "morning", "v2 open shape")
    expect(view.get("trading") is True and view.get("clock_rules") == "v2", "v2 trading flag")
    for expected in (689, 690, 779, 780, 899, 900):
        skipped = call("POST", f"/saves/{sid}/clock/skip")
        expect(skipped.get("clock_minute") == expected, f"skip -> {skipped.get('clock_minute')}")
    closed = call("GET", f"/saves/{sid}/market?limit=1")
    expect(closed.get("phase") == "closed", f"phase {closed.get('phase')}")
    expect(closed.get("fast_forward_at") is not None, "fast_forward_at missing at 15:00")
    summary = call("GET", f"/saves/{sid}/day-summary")
    expect(summary.get("status") == "closed" and summary.get("market", {}).get("total") == 385,
           "day-summary shape")
    for expected in (569, 570):
        skipped = call("POST", f"/saves/{sid}/clock/skip")
        expect(skipped.get("clock_minute") == expected, f"skip -> {skipped.get('clock_minute')}")
    expect(skipped.get("trading_day") == 1, f"trading_day {skipped.get('trading_day')}")
    detail = call("GET", f"/saves/{sid}/market/600036")
    days = [c.get("trading_day") for c in detail.get("candles", [])]
    expect(0 in days, "closed day 0 candle missing")
    call("PATCH", "/me", {"clock_speed": "fast"})
    fast = call("GET", f"/saves/{sid}/market?limit=1")
    expect(fast.get("ms_per_minute") == 2500, f"ms_per_minute {fast.get('ms_per_minute')}")
    state["v2_save_id"] = sid
    return f"v2 save={sid} trading_day=1"


@step("v2 event save: supply chain, news, event detail, closed save 409")
def s_events(state):
    """事件模式 v2 存档（01 §11 第 9 步）：产业链只公开结构；按交易日循环跳过至第 2 日，
    重大事件每个交易日都有，取其一查详情；关闭事件的存档请求 /news 得 409。"""
    save = call("POST", "/saves", {"name": "events", "clock_rules": 2, "events_enabled": True})
    expect(save.get("events_enabled") is True, "events_enabled not set on create")
    sid = save["id"]
    chain = call("GET", f"/saves/{sid}/supply-chain")
    expect(len(chain.get("nodes", [])) == 82, f"supply nodes {len(chain.get('nodes', []))}")
    expect(
        all(e.get("strength") is None for e in chain.get("edges", [])),
        "strength revealed by default",
    )
    # 一交易日 8 次跳过（v2），最多 24 次，直到交易日 >= 2
    trading_day = 0
    for _ in range(24):
        if trading_day >= 2:
            break
        trading_day = call("POST", f"/saves/{sid}/clock/skip").get("trading_day", 0)
    expect(trading_day >= 2, f"trading_day {trading_day} after skips")
    news = call("GET", f"/saves/{sid}/news?major=true&limit=30")
    majors = news.get("items", [])
    expect(majors and all(i.get("major") for i in majors), "no major news after two trading days")
    event_id = majors[0]["event_id"]
    detail = call("GET", f"/saves/{sid}/events/{event_id}")
    expect(
        detail.get("event_id") == event_id and detail.get("propagation") is not None,
        "event detail shape",
    )
    expect(
        detail["propagation"] and detail["propagation"][0]["hop"] == 0,
        "propagation hop 0 missing",
    )
    closed = call("POST", "/saves", {"name": "closed", "clock_rules": 2})
    try:
        call("GET", f"/saves/{closed['id']}/news")
        raise AssertionError("closed save /news did not return 409")
    except HttpError as exc:
        expect(
            exc.status == 409 and exc.code == "EVENTS_DISABLED",
            f"closed news {exc.status} {exc.code}",
        )
    state["events_save_id"] = sid
    return f"events save={sid} major_news={len(majors)} event={event_id}"


@step("prediction cards: open, answer, settle, points, intel")
def s_predictions(state):
    """预测卡（02 §13.3）：事件存档 → 余额 200 → 跳过至出卡 → 作答并继续 → 跳过至首张卡结算 →
    余额 = 200 + 积分 → 买第一条边的 L1 情报 → 关闭事件的存档 /predictions 得 409。"""

    def probs_from_pick(pick: int, conf: int, k: int) -> list[int]:
        # 与 domain.scoring.probs_from_pick 同算法（余数按离 pick 近优先、同距下标小优先）
        rest = 100 - conf
        others = sorted((j for j in range(k) if j != pick), key=lambda j: (abs(j - pick), j))
        base, rem = divmod(rest, k - 1)
        out = [0] * k
        out[pick] = conf
        for j in others:
            out[j] = base
        for j in others[:rem]:
            out[j] += 1
        return out

    save = call("POST", "/saves", {"name": "predictions", "clock_rules": 2, "events_enabled": True})
    sid = save["id"]
    balance = call("GET", "/points")["balance"]
    expect(balance == 200, f"welcome balance {balance}")

    def open_cards():
        return call("GET", f"/saves/{sid}/predictions?status=open")["items"]

    card = None
    for _ in range(60):
        cards = open_cards()
        if cards:
            card = cards[0]
            break
        call("POST", f"/saves/{sid}/clock/skip")
    expect(card is not None, "no prediction card opened within 60 skips")
    expect(call("GET", f"/saves/{sid}")["clock_rules"] == "v2", "save is not v2")
    qs = {q["qid"]: q for q in card["questions"]}
    answers = {"dir": {"probs": probs_from_pick(2, 50, 5)}}
    if "rank" in qs:
        answers["rank"] = {"order": qs["rank"]["candidates"][:3]}
    if "rumor" in qs:
        answers["rumor"] = {"probs": [50, 50]}
    out = call(
        "POST",
        f"/saves/{sid}/predictions/{card['id']}/answer",
        {"answers": answers, "resume": True},
    )
    expect(out["card"]["status"] == "answered", "card not answered")
    expect(out["clock"]["paused"] is False, "clock still paused after resume=true answer")

    first_id = card["id"]
    settled = None
    for _ in range(120):
        call("POST", f"/saves/{sid}/clock/skip")
        cur = call("GET", f"/saves/{sid}/predictions/{first_id}")
        if cur["status"] == "settled":
            settled = cur
            break
        for other in open_cards():  # 途中新出的卡：不答直接跳过（恢复行情）
            call("POST", f"/saves/{sid}/predictions/{other['id']}/skip", {"resume": True})
    expect(settled is not None, "first card did not settle within 120 skips")
    expect(settled["points"] is not None, "settled card has no points")
    balance = call("GET", "/points")["balance"]
    expect(balance == 200 + settled["points"], f"balance {balance} != 200 + {settled['points']}")

    edge = call("GET", f"/saves/{sid}/supply-chain")["edges"][0]["id"]
    bought = call("POST", f"/saves/{sid}/intel/edges", {"edge_id": edge, "level": 1})
    expect(
        bought["charged"] == 100 and bought["balance"] == balance - 100,
        f"intel purchase {bought}",
    )
    after = next(e for e in call("GET", f"/saves/{sid}/supply-chain")["edges"] if e["id"] == edge)
    expect(after["strength"] is not None, "edge strength not revealed after L1")

    closed = call("POST", "/saves", {"name": "closed-pred", "clock_rules": 2})
    try:
        call("GET", f"/saves/{closed['id']}/predictions")
        raise AssertionError("closed save /predictions did not return 409")
    except HttpError as exc:
        expect(
            exc.status == 409 and exc.code == "EVENTS_DISABLED",
            f"closed predictions {exc.status} {exc.code}",
        )
    return f"save={sid} card={first_id} points={settled['points']} balance={bought['balance']}"


CHALLENGE_USERS = 6
CHALLENGE_POLL_S = 0.2


def _new_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _poll(fn: Callable[[], Any], timeout: float, what: str) -> Any:
    """反复调用 fn 直到返回真值；超时抛 AssertionError（附最后一次 HTTP 错误）。"""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while True:
        try:
            value = fn()
            if value:
                return value
        except HttpError as exc:
            last_exc = exc
        if time.monotonic() >= deadline:
            hint = f" (last error: {last_exc})" if last_exc else ""
            raise AssertionError(f"timeout after {timeout:.0f}s waiting for {what}{hint}")
        time.sleep(CHALLENGE_POLL_S)


def _challenge_answers(questions: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    """与 tests/integration/test_challenge_lifecycle.py::_answers 同口径，按 idx 轮转分布，
    使同一回合内各人的答案互不相同。"""
    out: dict[str, Any] = {}
    for q in questions:
        if q["kind"] in ("bucket", "binary"):
            k = len(q["edges_bp"]) + 1 if q["kind"] == "bucket" else 2
            weights = [1 + ((j + idx) % k) for j in range(k)]
            total = sum(weights)
            probs = [w * 100 // total for w in weights]
            probs[-1] += 100 - sum(probs)
            out[q["qid"]] = {"probs": probs}
        else:
            cands = list(q["candidates"])
            r = idx % len(cands)
            out[q["qid"]] = {"order": (cands[r:] + cands[:r])[:3]}
    return {"answers": out}


@step("challenge: daily flow (register, run, enter, answer, trade, settle, reveal)")
def s_challenge(state):
    """每日挑战（03 §13.3）：注册 6 人 → ensure → 轮询 running → 全部报名 → 轮询第 1 回合 open →
    各自作答（不同概率）→ 2 人下单 → shift 快进到结算 → 日榜 6 人且名次合法 →
    reveal 的 sha256(commitment_input) == seed_commitment → 挑战存档 clock/skip 得 409。"""
    users: list[dict[str, Any]] = []
    for _ in range(CHALLENGE_USERS):
        opener = _new_opener()
        username = "chal" + secrets.token_hex(3)
        password = "pw" + secrets.token_hex(4)
        call("POST", "/auth/register", {"username": username, "password": password}, opener=opener)
        users.append({"name": username, "opener": opener})
    op0 = users[0]["opener"]

    ensured = call("POST", "/debug/challenges/ensure", opener=op0)
    cid = ensured["id"]
    commitment = ensured["seed_commitment"]
    expect(ensured["schedule_mode"] == "compact", f"schedule_mode {ensured['schedule_mode']}")
    expect(ensured["clock_rules"] == "v2", f"clock_rules {ensured['clock_rules']}")
    expect(ensured["status"] == "scheduled", f"status after ensure {ensured['status']}")
    expect(ensured["seed_commitment"] and ensured["commitment_scheme"], "commitment missing")

    def is_running():
        ch = call("GET", f"/challenges/{cid}", opener=op0)
        return ch if ch["status"] == "running" else None

    _poll(is_running, 20, "challenge running (<=20s)")

    for u in users:
        ent = call("POST", f"/challenges/{cid}/entry", opener=u["opener"])
        expect(ent["eligible"] is True, f"entry not eligible for {u['name']}")
        expect(ent["save_id"] is not None, "entry without save")
        u["save_id"] = ent["save_id"]

    def round1_open():
        items = call("GET", f"/challenges/{cid}/rounds", opener=op0)["items"]
        return next((r for r in items if r["round_index"] == 1 and r["state"] == "open"), None)

    card = _poll(round1_open, 60, "round 1 open")
    questions = card["questions"]
    expect(questions and card["event"] is not None, "round 1 card without questions or event")

    for idx, u in enumerate(users):
        out = call(
            "PUT",
            f"/challenges/{cid}/rounds/1/answer",
            _challenge_answers(questions, idx),
            opener=u["opener"],
        )
        expect(out["my_revision"] == 1, f"revision {out['my_revision']} for {u['name']}")
        expect(len(out["my_answers"]) == len(questions), "answers not all stored")

    # 停顿期下单：挑第一只有价的股票，前两人各买 100 股
    market = call("GET", f"/saves/{users[0]['save_id']}/market?limit=20", opener=op0)
    quote = next((q for q in market["stocks"] if q.get("price_cents", 0) > 0), None)
    expect(quote is not None, "no priced stock in challenge market")
    for u in users[:2]:
        res = call(
            "POST",
            f"/saves/{u['save_id']}/orders",
            {"code": quote["code"], "side": "buy", "quantity": 100, "price_type": "market"},
            opener=u["opener"],
        )
        expect(res["trade"]["quantity"] == 100, f"challenge order for {u['name']} not filled")

    # 快进：整体前移 1 小时，run_due 推到终局并结算
    call("POST", f"/debug/challenges/{cid}/shift", {"seconds": 3600}, opener=op0)

    def is_settled():
        ch = call("GET", f"/challenges/{cid}", opener=op0)
        return ch if ch["status"] == "settled" else None

    _poll(is_settled, 20, "challenge settled after shift")

    board = call("GET", f"/challenges/{cid}/leaderboard?board=total&limit=50", opener=op0)
    expect(board["eligible_count"] == CHALLENGE_USERS, f"eligible_count {board['eligible_count']}")
    expect(len(board["items"]) == CHALLENGE_USERS, f"day board items {len(board['items'])}")
    ranks = [item["rank"] for item in board["items"]]
    expect(ranks[0] == 1 and ranks == sorted(ranks), f"ranks not ordered: {ranks}")
    expect(all(1 <= r <= CHALLENGE_USERS for r in ranks), f"rank out of range: {ranks}")
    expect(board["me"] is not None and board["me"]["is_me"] is True, "me missing on day board")

    reveal = call("GET", f"/challenges/{cid}/reveal", opener=op0)
    expect(reveal["status"] == "settled", f"reveal status {reveal['status']}")
    expect(reveal["seed_commitment"] == commitment, "commitment changed between ensure and reveal")
    digest = hashlib.sha256(reveal["commitment_input"].encode("utf-8")).hexdigest()
    expect(digest == reveal["seed_commitment"], "sha256(commitment_input) != seed_commitment")
    seed_field = f"|seed={reveal['market_seed']}|"
    expect(seed_field in reveal["commitment_input"], "seed not in commitment_input")

    try:
        call("POST", f"/saves/{users[0]['save_id']}/clock/skip", opener=op0)
        raise AssertionError("challenge clock/skip was not refused")
    except HttpError as exc:
        expect(exc.status == 409 and exc.code == "CHALLENGE_UNSUPPORTED",
               f"challenge clock/skip {exc.status} {exc.code}")

    state["challenge_id"] = cid
    return f"challenge={cid} players={CHALLENGE_USERS} my_rank={board['me']['rank']} reveal=ok"


@step("prediction market: open -> quote -> trade (idempotent) -> sell -> settle -> ledger")
def s_prediction_market(state):
    """预测市场（04 §11.4）：注册 → ensure（明天的挑战）→ 开市 → 报价 → 带幂等键买 2 份 →
    重复提交得 replayed
    → 卖 1 份 → shift 快进到结算 → 结算记录 ≥ 1 条 → 积分余额与流水末条 balance_after 相符。"""
    tz8 = timezone(timedelta(hours=8))
    day = (datetime.now(tz8).date() + timedelta(days=1)).isoformat()
    opener = _new_opener()
    username = "pm" + secrets.token_hex(3)
    password = "pw" + secrets.token_hex(4)
    call("POST", "/auth/register", {"username": username, "password": password}, opener=opener)
    ensured = call("POST", "/debug/challenges/ensure", {"date": day}, opener=opener)
    cid = ensured["id"]

    def open_market():
        call("POST", "/debug/prediction-markets/sync", opener=opener)
        page = call("GET", f"/prediction-markets?challenge_id={cid}&status=open", opener=opener)
        items = page["items"]
        bucket = next((m for m in items if m["kind"] == "bucket"), None)
        return bucket or (items[0] if items else None)

    market = _poll(open_market, 40, "open prediction market")
    mid = market["id"]
    expect(market["status"] == "open", f"market status {market['status']}")
    expect(sum(o["price_ppm"] for o in market["outcomes"]) == 1_000_000, "prices not normalized")

    quote = call(
        "GET", f"/prediction-markets/{mid}/quote?side=buy&outcome=0&shares=2", opener=opener
    )
    expect(quote["shares"] == 2 and quote["points"] > 0, f"quote {quote}")
    balance0 = call("GET", "/points", opener=opener)["balance"]
    key = "e2e-buy-" + secrets.token_hex(6)
    body = {"side": "buy", "outcome": 0, "shares": 2}
    first = call(
        "POST", f"/prediction-markets/{mid}/trades", body, opener=opener,
        headers_extra={"Idempotency-Key": key},
    )
    expect(first["replayed"] is False and first["trade"]["points"] == quote["points"],
           f"buy points {first['trade']['points']} != quote {quote['points']}")
    again = call(
        "POST", f"/prediction-markets/{mid}/trades", body, opener=opener,
        headers_extra={"Idempotency-Key": key},
    )
    expect(again["replayed"] is True and again["trade"]["id"] == first["trade"]["id"],
           "idempotent replay did not return the original trade")
    sell = call(
        "POST", f"/prediction-markets/{mid}/trades",
        {"side": "sell", "outcome": 0, "shares": 1}, opener=opener,
        headers_extra={"Idempotency-Key": "e2e-sell-" + secrets.token_hex(6)},
    )
    expect(sell["trade"]["shares"] == 1 and sell["trade"]["points"] > 0, "sell not filled")
    balance1 = call("GET", "/points", opener=opener)["balance"]
    expect(balance1 == balance0 - first["trade"]["points"] + sell["trade"]["points"],
           f"balance {balance1} does not match trades")

    call("POST", f"/debug/challenges/{cid}/shift", {"seconds": 3600}, opener=opener)

    def settled():
        call("POST", "/debug/prediction-markets/sync", opener=opener)
        page = call("GET", "/me/prediction-settlements", opener=opener)
        return page if page["items"] else None

    page = _poll(settled, 40, "prediction settlement after shift")
    expect(
        any(item["market_id"] == mid for item in page["items"]),
        "settlement for our market missing",
    )
    ledger = call("GET", "/points/ledger", opener=opener)
    balance = call("GET", "/points", opener=opener)["balance"]
    expect(ledger["items"][0]["balance_after"] == balance,
           f"ledger balance_after {ledger['items'][0]['balance_after']} != balance {balance}")
    state["prediction_challenge_id"] = cid
    return (
        f"market={mid} quote={quote['points']} replay=ok "
        f"sell={sell['trade']['points']} settled=ok"
    )


@step("replay: list → session → open buy → questions → settle → reveal")
def s_replay(state: dict[str, Any]) -> str:
    """真实复盘（E3.4）：夹具关卡包（服务端以 REPLAY_PACKS_DIR 导入，不联网）。

    列关卡 → 建会话 → 推进到开盘买入 → 推进到第 1 日盘前（题目截止处停下）作答 → 推进到结算 → 揭示。
    """
    slug = os.environ.get("REPLAY_SLUG", "fixture-min")
    levels = call("GET", "/replay/levels")["items"]
    expect(any(item["slug"] == slug for item in levels), f"level {slug} not listed")
    created = call("POST", "/replay/sessions", {"level_slug": slug, "masked": True})
    sid = created["save_id"]
    expect(created["phase"] == "pre_open" and created["day_idx"] == 0, "bad start position")

    def session() -> dict[str, Any]:
        return call("GET", f"/replay/sessions/{sid}")

    moved = call("POST", f"/replay/sessions/{sid}/advance",
                 {"to": "next_phase", "expected_tick": session()["tick"]})
    expect(moved["session"]["phase"] == "open", "did not reach open phase")
    code = call("GET", f"/saves/{sid}/market")["stocks"][0]["code"]
    trade = call("POST", f"/saves/{sid}/orders",
                 {"code": code, "side": "buy", "quantity": 100, "price_type": "market"})["trade"]
    expect(trade["clock_minute"] == 570, "open-phase order not at 570")
    stop = call("POST", f"/replay/sessions/{sid}/advance",
                {"to": "next_day", "expected_tick": session()["tick"]})
    expect(
        stop["stopped_reason"] == "question_open",
        f"expected question_open, got {stop['stopped_reason']}",
    )
    questions = call("GET", f"/replay/sessions/{sid}/questions")["items"]
    expect(len(questions) == 2, "expected two open questions on day 1")
    for question in questions:
        if question["kind"] == "direction_bucket":
            body = {"probs": [10, 20, 40, 20, 10]}
        else:
            body = {"order": question["codes"][: question["top_k"]]}
        call("PUT", f"/replay/sessions/{sid}/questions/{question['id']}/answer", body)
    scored: list[str] = []
    for _ in range(40):
        current = session()
        if current["status"] == "settled":
            break
        out = call("POST", f"/replay/sessions/{sid}/advance",
                   {"to": "next_phase", "expected_tick": current["tick"]})
        scored += out["scored_question_ids"]
    expect(session()["status"] == "settled", "game did not settle")
    expect(sorted(scored) == ["q1", "q2"], f"questions not scored: {scored}")
    reveal = call("GET", f"/replay/sessions/{sid}/reveal")
    expect(
        len(reveal["stocks"]) == 3 and reveal["stocks"][0]["real_code"],
        "reveal has no real stocks",
    )
    return f"settled, points_total={reveal['session']['settled']['points_total']}"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    print(f"e2e smoke against {BASE_URL}")
    try:
        call("GET", "/healthz")
    except Exception as exc:
        print(f"FAIL server not reachable: {exc}")
        return 2
    state: dict[str, Any] = {}
    steps = [
        s_register, s_create_save, s_market, s_buy, s_t1, s_portfolio,
        s_watch, s_auto, s_export, s_clock_v2, s_events, s_predictions,
    ]
    if _flag("E2E_CHALLENGE"):
        steps.append(s_prediction_market)
        steps.append(s_challenge)
    else:
        print("SKIP  challenge scenario (set E2E_CHALLENGE=1; compact env, see CLAUDE.md)")
    if _flag("REPLAY_SMOKE"):
        steps.append(s_replay)
    else:
        print(
            "SKIP  replay scenario (set REPLAY_SMOKE=1; "
            "server needs REPLAY_PACKS_DIR with the fixture pack)"
        )
    for index, fn in enumerate(steps):
        if not fn(state):
            for rest in steps[index + 1 :]:
                _results.append((rest.step_name, False, "skipped after earlier failure"))
            break
    passed = 0
    for name, ok, detail in _results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        passed += ok
    print(f"{passed}/{len(_results)} passed")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
