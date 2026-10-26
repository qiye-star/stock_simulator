#!/usr/bin/env python3
"""时钟 v2 波动标定报告（docs/10.26-plan/07-时钟v2.md §4.3）。

用真实确定性引擎（domain.market_engine.advance, rules=2）跑全量股票池，从 9:30 逐分钟推进，
统计 §4.3 表中的指标。纯标准库；只 import stocksim.domain；股票池与行业区间自行读取 data/*.json。

用法：
  python3 scripts/clock_v2_sim_report.py --seeds 3 --days 60 [--check]
  --check：任一指标越界即以非零码退出（CI 用 --seeds 2 --days 40）。
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from stocksim.domain import clock as c  # noqa: E402
from stocksim.domain.market_engine import advance, init_market  # noqa: E402
from stocksim.domain.rules import limit_down_cents, limit_up_cents  # noqa: E402

DATA = ROOT / "backend" / "src" / "stocksim" / "data"
AS_OF = date(2026, 1, 1)
LOW_PRICE_CENTS = 1_000  # < 10 元
BULL_PROFILE = "bull_bias"

# (名称, 目标下界, 目标上界, 单位说明)
TARGETS: dict[str, tuple[float, float]] = {
    "stock_day_sigma": (0.019, 0.027),
    "trend_free_sigma": (0.014, 0.021),
    "index_sigma": (0.005, 0.011),
    "amplitude_median": (0.018, 0.035),
    "limit_touch_ratio": (0.004, 0.013),
    "limit_close_ratio": (0.0015, 0.007),
    "max_tick_move": (0.0, 0.01),  # 上界为开区间
    "mean_daily_return_abs": (0.0, 0.0005),
    "touch_up_down_ratio": (0.7, 1.4),
    "bull_up_day_share": (0.8, 1.0),
    "low_price_sigma_ratio": (0.0, 1.3),
    "volume_drift_median": (0.5, 2.0),
    "volume_monotone_share": (1.0, 1.0),
    "breaker_triggers": (0.0, 0.0),
    "advance_p95_ms": (0.0, 8.0),
}


def load_stocks() -> tuple[list[dict[str, Any]], dict[str, tuple[int, int]]]:
    pool = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
    rows = json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
    stocks = [
        {
            "code": str(r["code"]),
            "name": str(r["name"]),
            "industry": str(r["industry"]),
            "profile": str(r.get("profile", "normal")),
        }
        for r in pool
    ]
    ranges = {
        str(r["name"]): (int(r["base_price_range_yuan"][0]), int(r["base_price_range_yuan"][1]))
        for r in rows
    }
    return stocks, ranges


def simulate(seed: int, days: int) -> dict[str, Any]:
    """跑一个种子，返回原始样本（供汇总）。"""
    stocks, ranges = load_stocks()
    state = init_market(seed, stocks, AS_OF, ranges)
    n = len(state["stocks"])
    prev_close_low: list[int] = []  # 低价股样本的 (日收益) 已在下面按股收集
    returns: list[float] = []  # 所有 stock·day 的日收益
    trend_free: list[float] = []
    low_returns: list[float] = []
    bull_days: list[float] = []
    index_by_day: list[list[float]] = []
    amplitudes: list[float] = []
    touch_up = touch_down = close_up = close_down = 0
    stock_days = 0
    volume_series: list[list[int]] = [[] for _ in range(n)]
    mean_returns: list[float] = []
    max_tick_move = 0.0
    breaker_triggers = 0
    volume_checks = volume_ok = 0
    times_ms: list[float] = []
    tick = 0
    minute = c.V2_START_MINUTE
    target_day = days
    _ = prev_close_low

    while state["trading_day"] < target_day:
        tick += 1
        minute = c.advance_minute(minute)
        if not c.is_trading_time(minute):
            continue
        before = state
        t0 = time.perf_counter()
        state = advance(before, seed, tick, minute, rules=c.CLOCK_RULES_V2)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
        if state["breaker"]:
            breaker_triggers += 1
        if state["trading_day"] == before["trading_day"]:
            for i, (sb, sa) in enumerate(zip(before["stocks"], state["stocks"], strict=True)):
                volume_checks += 1
                if int(sa["daily_volume"]) >= int(sb["daily_volume"]):
                    volume_ok += 1
                if sb["price"] > 0:
                    mv = abs(sa["price"] / sb["price"] - 1.0)
                    if mv > max_tick_move:
                        max_tick_move = mv
            continue
        # 换日：before 的状态就是“已收盘的一日”
        day_idx = before["trading_day"]
        cache = before.get("regime") or {"trend": {}}
        day_rets: list[float] = []
        for i, s in enumerate(before["stocks"]):
            prev = int(s["prev_close"])
            price = int(s["price"])
            if prev <= 0:
                continue
            ret = (price - prev) / prev
            day_rets.append(ret)
            stock_days += 1
            returns.append(ret)
            if int(s["prev_close"]) < LOW_PRICE_CENTS:
                low_returns.append(ret)
            trend = cache["trend"].get(i, 0)
            if trend == 0:
                trend_free.append(ret)
            if s["profile"] == BULL_PROFILE:
                bull_days.append(1.0 if ret > 0 else 0.0)
            high, low = int(s["high"]), int(s["low"])
            amplitudes.append((high - low) / prev)
            up_lim, dn_lim = limit_up_cents(prev), limit_down_cents(prev)
            if high >= up_lim:
                touch_up += 1
            if low <= dn_lim:
                touch_down += 1
            if price >= up_lim:
                close_up += 1
            if price <= dn_lim:
                close_down += 1
            volume_series[i].append(int(s["daily_volume"]))
        index_by_day.append(day_rets)
        mean_returns.append(statistics.fmean(day_rets))
        _ = day_idx
    return {
        "returns": returns,
        "trend_free": trend_free,
        "low_returns": low_returns,
        "bull_days": bull_days,
        "index": [statistics.fmean(r) for r in index_by_day if r],
        "amplitudes": amplitudes,
        "touch_up": touch_up,
        "touch_down": touch_down,
        "close_up": close_up,
        "close_down": close_down,
        "stock_days": stock_days,
        "volume_series": volume_series,
        "mean_returns": mean_returns,
        "max_tick_move": max_tick_move,
        "breaker_triggers": breaker_triggers,
        "volume_checks": volume_checks,
        "volume_ok": volume_ok,
        "times_ms": times_ms,
    }


def _std(xs: list[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def summarize(parts: list[dict[str, Any]]) -> dict[str, float]:
    returns = [x for p in parts for x in p["returns"]]
    all_sigma = _std(returns)
    low_sigma = _std([x for p in parts for x in p["low_returns"]])
    vol_ratios: list[float] = []
    for p in parts:
        for series in p["volume_series"]:
            if len(series) >= 2 and series[0] > 0:
                vol_ratios.append(series[-1] / series[0])
    touch = sum(p["touch_up"] + p["touch_down"] for p in parts)
    stock_days = sum(p["stock_days"] for p in parts)
    touch_up = sum(p["touch_up"] for p in parts)
    touch_down = sum(p["touch_down"] for p in parts)
    times = sorted(t for p in parts for t in p["times_ms"])
    p95 = times[int(0.95 * (len(times) - 1))] if times else 0.0
    vc = sum(p["volume_checks"] for p in parts)
    vo = sum(p["volume_ok"] for p in parts)
    bull = [x for p in parts for x in p["bull_days"]]
    return {
        "stock_day_sigma": all_sigma,
        "trend_free_sigma": _std([x for p in parts for x in p["trend_free"]]),
        "index_sigma": _std([x for p in parts for x in p["index"]]),
        "amplitude_median": statistics.median([x for p in parts for x in p["amplitudes"]]),
        "limit_touch_ratio": touch / stock_days if stock_days else 0.0,
        "limit_close_ratio": sum(p["close_up"] + p["close_down"] for p in parts) / stock_days
        if stock_days
        else 0.0,
        "max_tick_move": max(p["max_tick_move"] for p in parts),
        "mean_daily_return_abs": abs(statistics.fmean(returns)) if returns else 0.0,
        "touch_up_down_ratio": touch_up / touch_down if touch_down else float("inf"),
        "bull_up_day_share": statistics.fmean(bull) if bull else 0.0,
        "low_price_sigma_ratio": low_sigma / all_sigma if all_sigma else 0.0,
        "volume_drift_median": statistics.median(vol_ratios) if vol_ratios else 0.0,
        "volume_monotone_share": vo / vc if vc else 0.0,
        "breaker_triggers": float(sum(p["breaker_triggers"] for p in parts)),
        "advance_p95_ms": p95,
        "stock_days": float(stock_days),
    }


def check(metrics: dict[str, float]) -> list[str]:
    bad: list[str] = []
    for name, (lo, hi) in TARGETS.items():
        v = metrics[name]
        if name == "max_tick_move":
            ok = v < hi
        else:
            ok = lo <= v <= hi
        if not ok:
            bad.append(f"{name}={v:.6f} 不在 [{lo}, {hi}]")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--check", action="store_true", help="越界时非零退出")
    ap.add_argument("--base-seed", type=int, default=20261026)
    args = ap.parse_args()

    seeds = [args.base_seed + 7919 * i for i in range(args.seeds)]
    with ProcessPoolExecutor() as pool:
        parts = list(pool.map(simulate, seeds, [args.days] * len(seeds)))
    m = summarize(parts)

    print(f"seeds={len(seeds)} days={args.days} stock_days={int(m['stock_days'])}")
    print(f"{'指标':<24}{'值':>14}   目标")
    for name, (lo, hi) in TARGETS.items():
        v = m[name]
        if name == "max_tick_move":
            target = f"< {hi}"
        else:
            target = f"[{lo}, {hi}]"
        flag = "OK" if (v < hi if name == "max_tick_move" else lo <= v <= hi) else "FAIL"
        print(f"{name:<24}{v:>14.6f}   {target}  {flag}")
    bad = check(m)
    if bad:
        print("未达标：")
        for line in bad:
            print("  -", line)
    else:
        print("全部指标达标")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
