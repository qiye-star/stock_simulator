#!/usr/bin/env python3
"""预测市场公开基率先验（04 §4.5）：只 import `stocksim.domain`，纯标准库，读仓库内的 data/*.json。

流程：build_ruleset(clock_rules=2) → 逐交易 tick 用 domain.advance 推演行情
（drift 来自 build_day_plan，
tick/分钟口径与 event_sim_report.py 的 clock_point 一致，即 v2_tick_of / v2_minute_of_offset）
→ 每日收盘价 →
对每个重大事件，用 domain.prediction_market.contracts_for_event 取 bucket 合约
（窗口、档位与挑战内完全相同），
按与服务层相同的真值口径（from_day−1 收盘 → to_day 收盘，逐股 bp 后等权）结算，
统计每个 (scope, sentiment)
的分档频率。只统计已完整结算的事件（resolve_tt ≤ 仿真末尾）。

先验是公开基率：只按公开字段（scope、sentiment）分组，不含单个事件的隐藏信息（真值、强度）。
每组先截到 PRIOR_FLOOR_PPM（10%），再按比例归一为整数 ppm 且和恰为 1e6（若有截断，保持 ≥ 下限）。

用法：
    python3 scripts/pm_prior_report.py --seeds 20 --days 120            # 打印统计与 constants 片段
    python3 scripts/pm_prior_report.py --seeds 20 --days 120 --check
        # 同时校验 domain 常量与统计一致，不一致退出码 1
    --workers N：进程数（默认 min(seeds, CPU 核数)）。仿真是确定性的：同参数输出逐字相同。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
DATA = ROOT / "backend" / "src" / "stocksim" / "data"

from stocksim.domain import market_engine as me  # noqa: E402
from stocksim.domain.clock import v2_minute_of_offset, v2_tick_of  # noqa: E402
from stocksim.domain.events import (  # noqa: E402
    build_day_plan,
    build_ruleset,
    generate_day,
    plan_window,
    save_params,
)
from stocksim.domain.money import round_half_up_div  # noqa: E402
from stocksim.domain.prediction_market import ContractContext, contracts_for_event, resolve_bucket  # noqa: E402
from stocksim.domain.prediction_market.constants import (  # noqa: E402
    BUCKET_PRIOR_PPM,
    PRICE_PPM_TOTAL,
    PRIOR_FLOOR_PPM,
)
from stocksim.domain.predictions import Structure  # noqa: E402

CLOCK_RULES = 2
TICKS_PER_DAY = 242  # 与 domain.clock.timebase(2) 一致
AS_OF = dt.date(2026, 10, 26)
SCOPES = ("industry", "stock", "market")
SENTIMENTS = (-1, 1)
BUCKETS = 5


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _ruleset():
    return build_ruleset(
        supply_chain=_load("supply_chain.json"),
        exposure=_load("stock_exposure.json"),
        templates=_load("news_templates.json"),
        industries=_load("industries.json"),
        stock_pool=_load("stock_pool.json"),
        version=1,
        clock_rules=CLOCK_RULES,
    )


def _structure(rs) -> Structure:
    return Structure(
        industries=tuple(rs.industries),
        stock_count={name: rs.stock_counts[i] for i, name in enumerate(rs.industries)},
        neighbors={name: frozenset() for name in rs.industries},  # 出题用邻接，先验不需要
        stock_total=len(rs.stocks),
        stock_names={s.code: s.name for s in rs.stocks},
    )


def _clock_point(tt: int) -> tuple[int, int]:
    """交易 tick tt → (推进用的全局 tick, 游戏分钟)，与服务层 save.tick 同口径。"""
    day, offset = divmod(tt, TICKS_PER_DAY)
    return v2_tick_of(day, offset), v2_minute_of_offset(offset)


def _members(rs, spec) -> list[int]:
    if spec.scope == "industry":
        return list(rs.industry_stocks[rs.industry_index[spec.industry]])
    if spec.scope == "stock":
        return [rs.stock_index[spec.code]]
    return list(range(len(rs.stocks)))


def _change_bp(closes, members, from_day, to_day):
    """与 services 的 change_bp_for / industry_change_bp 同口径：逐股 bp 取整后等权再取整。"""
    changes = []
    for i in members:
        base = closes[from_day - 1][i]
        last = closes[to_day][i]
        if base > 0:
            changes.append(round_half_up_div((last - base) * 10_000, base))
    if not changes:
        return None
    return round_half_up_div(sum(changes), len(changes))


def simulate_seed(args: tuple[int, int]) -> list[tuple[str, int, int]]:
    """返回 [(scope, sentiment, outcome)]，每条对应一个已完整结算的重大事件的分档结果。"""
    seed, days = args
    rs = _ruleset()
    params = save_params(seed, rs)
    stocks = [
        {
            "code": r["code"],
            "name": r["name"],
            "industry": r["industry"],
            "profile": r.get("profile", "normal"),
        }
        for r in _load("stock_pool.json")
    ]
    ranges = {r["name"]: tuple(r["base_price_range_yuan"]) for r in _load("industries.json")}
    state = me.init_market(seed, stocks, AS_OF, ranges)
    closes: dict[int, list[int]] = {-1: [s["history"][-2]["close"] for s in state["stocks"]]}
    for s in state["stocks"]:
        s["history"] = s["history"][-1:]  # 只保留推进所需的最后一根 K 线（同 event_sim_report）

    events_cache: dict[int, tuple] = {}

    def events_of(day: int):
        if day not in events_cache:
            events_cache[day] = generate_day(seed, day, rs, params)
        return events_cache[day]

    for day in range(days):
        window = [e for d in plan_window(day) for e in events_of(d)]
        plan = build_day_plan(day, window, rs, params)
        for offset in range(TICKS_PER_DAY):
            tt = day * TICKS_PER_DAY + offset
            if tt == 0:
                continue  # 开盘 tick 不推进（与服务层 _run_ticks 一致）
            tick, minute = _clock_point(tt)
            state = me.advance(state, seed, tick, minute, drift=plan[offset], rules=CLOCK_RULES)
        closes[day] = [int(s["price"]) for s in state["stocks"]]

    ctx = ContractContext(
        clock_rules=CLOCK_RULES,
        first_tt=0,
        last_tt=days * TICKS_PER_DAY - 1,
        structure=_structure(rs),
    )
    rows: list[tuple[str, int, int]] = []
    for day in range(days + 2):  # 排期日延伸到 days+1：窗口落在仿真内的事件都要计入
        for ev in events_of(day):
            if not ev.major:
                continue
            for spec in contracts_for_event(ev, ctx):
                if spec.kind != "bucket":
                    continue
                change = _change_bp(closes, _members(rs, spec), spec.from_day, spec.to_day)
                if change is None:
                    continue
                rows.append((ev.scope, ev.sentiment, resolve_bucket(spec, change)))
    return rows


def normalize_prior(counts: list[int], floor: int = PRIOR_FLOOR_PPM) -> tuple[int, ...]:
    """频数 → 先验 ppm：每档截到 floor 后按剩余质量比例分配，最后最大余数法取整，和恰为 1e6。"""
    total = sum(counts)
    if total <= 0:
        raise ValueError("no samples")
    raw = [Fraction(c * PRICE_PPM_TOTAL, total) for c in counts]
    fixed: set[int] = set()
    while True:
        free = [k for k in range(len(raw)) if k not in fixed]
        mass = PRICE_PPM_TOTAL - floor * len(fixed)
        free_sum = sum(raw[k] for k in free)
        scaled = {k: raw[k] * mass / free_sum for k in free}
        newly = {k for k in free if scaled[k] < floor}
        if not newly:
            break
        fixed |= newly
    values = {k: (Fraction(floor) if k in fixed else scaled[k]) for k in range(len(raw))}
    floors = {k: int(v) for k, v in values.items()}
    remain = PRICE_PPM_TOTAL - sum(floors.values())
    order = sorted(values, key=lambda k: (-(values[k] - floors[k]), k))
    out = dict(floors)
    for k in order[:remain]:
        out[k] += 1
    return tuple(out[k] for k in range(len(raw)))


def aggregate(rows) -> dict[tuple[str, int], list[int]]:
    counts: dict[tuple[str, int], list[int]] = {}
    for scope, sentiment, outcome in rows:
        counts.setdefault((scope, sentiment), [0] * BUCKETS)[outcome] += 1
    return counts


def report(seeds: int, days: int, workers: int) -> tuple[dict, dict]:
    rows: list[tuple[str, int, int]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(simulate_seed, [(s, days) for s in range(1, seeds + 1)]):
            rows.extend(part)
    counts = aggregate(rows)
    priors = {}
    for scope in SCOPES:
        for sentiment in SENTIMENTS:
            key = (scope, sentiment)
            cs = counts.get(key, [0] * BUCKETS)
            if sum(cs) == 0:
                raise SystemExit(f"no samples for {key}; increase --seeds/--days")
            priors[key] = normalize_prior(cs)
    summary = {
        "clock_rules": CLOCK_RULES,
        "seeds": seeds,
        "days": days,
        "events": len(rows),
        "groups": {
            f"{scope}|{sentiment}": {
                "n": sum(counts[(scope, sentiment)]),
                "counts": counts[(scope, sentiment)],
                "prior_ppm": list(priors[(scope, sentiment)]),
            }
            for scope in SCOPES
            for sentiment in SENTIMENTS
        },
    }
    return summary, priors


def check(priors: dict) -> list[str]:
    errors = []
    for key, prior in priors.items():
        if sum(prior) != PRICE_PPM_TOTAL:
            errors.append(f"{key}: sum {sum(prior)} != 1e6")
        if min(prior) < PRIOR_FLOOR_PPM:
            errors.append(f"{key}: below floor {min(prior)}")
        if tuple(BUCKET_PRIOR_PPM.get(key, ())) != tuple(prior):
            errors.append(f"{key}: domain constant {BUCKET_PRIOR_PPM.get(key)} != computed {prior}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--check", action="store_true", help="校验 BUCKET_PRIOR_PPM 与统计一致")
    args = parser.parse_args()
    workers = args.workers or min(args.seeds, os.cpu_count() or 1)
    summary, priors = report(args.seeds, args.days, workers)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n# constants.py 片段（BUCKET_PRIOR_PPM）")
    for (scope, sentiment), prior in priors.items():
        print(f'    ("{scope}", {sentiment}): {prior},')
    if args.check:
        errors = check(priors)
        for line in errors:
            print("CHECK FAILED:", line, file=sys.stderr)
        if errors:
            return 1
        print("check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
