#!/usr/bin/env python3
"""端到端 HTTP 冒烟脚本：只用标准库（urllib + http.cookiejar），逐步打印 PASS/FAIL。

用法：
    BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py

流程：注册随机用户 -> 建存档 -> 读行情 -> 买入 100 股 -> T+1 卖出应被拒绝 ->
持仓 -> 加自选 -> 建自动交易条件单 -> 导出存档。任一步失败则以非零码退出。
若开局不在交易时段，会尝试调用 debug/time（需 ENABLE_DEBUG_API=true），否则该步记为 FAIL。
"""

from __future__ import annotations

import functools
import http.cookiejar
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
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


def call(method: str, path: str, body: Any = None) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=TIMEOUT) as resp:
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
            except Exception as exc:  # noqa: BLE001 - 冒烟脚本需要捕获一切并记录
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


def main() -> int:
    print(f"e2e smoke against {BASE_URL}")
    try:
        call("GET", "/healthz")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL server not reachable: {exc}")
        return 2
    state: dict[str, Any] = {}
    steps = [
        s_register, s_create_save, s_market, s_buy, s_t1, s_portfolio,
        s_watch, s_auto, s_export,
    ]
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
