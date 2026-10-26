"""事件行情仿真调参报告（01 §12.3）。纯标准库，只 import stocksim.domain，自己读 data/*.json。

用法：
    v1（默认）：python3 scripts/event_sim_report.py --seeds 20 --days 300
    v2：        python3 scripts/event_sim_report.py --clock-rules 2 --seeds 20 --days 120

    --clock-rules {1,2}：时钟规则版本，默认 1。v1 每交易日 20 tick，v2 每交易日 242 tick（domain.clock.timebase）。
    --days 按交易日计；v2 单日 242 tick，耗时约为 v1 的 12 倍，可减少 --seeds / --days，报告会写明实际参数。

每个 seed 用真实 ``domain.advance`` 推进 days 个交易日（开启事件漂移），统计验收指标；两版都必须达标；
不达标时退出码 1。不达标只调 backend/src/stocksim/domain/events/constants.py 后重跑。

指标口径（均只统计重大事件，排除 priced_in 与最终辟谣的传闻，其曲线按设计会反向或归零）：
- 源行业一致率：industry 范围事件，发布前一 tick 到发布后 1 个交易日（v1 20 tick、v2 242 tick）的源行业等权收益，
  扣除全市场均值，符号与事件 sentiment 一致的比例。
- 一跳一致率：传导 hop=1 的节点，从其延迟到达前一 tick 起 1 个交易日的超额收益，符号与预期一致的比例，
  按所经边的强度档位分别统计。
- 触板率：industry 范围事件发布当日（事件日），源行业龙头 / 普通成分股当日是否触及涨停或跌停价。
  非事件日（无上述事件的交易日）按同口径另报对照（含随机噪声自带的触板）。
- 日均漂移：每个交易日全市场等权平均的累计漂移（ppm）的平均值。
- 熔断：逐 tick 检查 state["breaker"]。
- 频率：每个重大事件周期的重大事件条数（周期：v1 12 个交易日，v2 1 个交易日）；按真实刷新速率折算平均间隔
  （v1 默认 3 s/tick；v2 按 normal 档 5 s/游戏分钟）。
- 计划构建耗时：单交易日 ``build_day_plan``（事件窗口已生成）p95；冷启动（连同窗口事件生成）另报告。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
from array import array
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from stocksim.domain import market_engine as me  # noqa: E402
from stocksim.domain.clock import (  # noqa: E402
    CLOCK_RULES_V1,
    CLOCK_RULES_V2,
    SPEED_MS_PER_MINUTE,
    timebase,
    v2_minute_of_offset,
    v2_tick_of,
)
from stocksim.domain.events import (  # noqa: E402
    build_day_plan,
    build_ruleset,
    generate_day,
    major_days,
    plan_window,
    save_params,
)
from stocksim.domain.events import constants as c  # noqa: E402
from stocksim.domain.events.timing import major_period_days  # noqa: E402
from stocksim.domain.rules import limit_down_cents, limit_up_cents  # noqa: E402

DATA = ROOT / "backend" / "src" / "stocksim" / "data"
AS_OF = dt.date(2026, 10, 23)
TRADING_MINUTE = 600  # v1 推进使用的游戏分钟（v1 的 tick 即交易 tick）
TAIL_TICKS_IN_DAYS = 2  # 事件须离仿真末尾至少 2 个交易日（原 v1 的 40 tick = 2 × 20）
REFRESH_SECONDS = {  # 每 tick 的真实刷新秒数：v1 默认前端 3 s；v2 按 normal 档 5 s/游戏分钟
    CLOCK_RULES_V1: 3,
    CLOCK_RULES_V2: SPEED_MS_PER_MINUTE["normal"] / 1000,
}

# 验收阈值（01 §12.3，两版共用；计划构建 p95 按版本区分）
SOURCE_CONSISTENT_MIN = 0.85
HOP1_S3_MIN = 0.75
HOP1_S1_RANGE = (0.55, 0.70)
LEADER_LIMIT_MAX = 0.30
NORMAL_LIMIT_MAX = 0.15
MEAN_DRIFT_MAX_PPM = 500  # ±0.05%
TWO_EVENT_SHARE = (0.30, 0.50)
INTERVAL_MINUTES = (6.0, 15.0)
PLAN_P95_MS = {CLOCK_RULES_V1: 30.0, CLOCK_RULES_V2: 400.0}


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def load_ruleset(clock_rules: int):
    return build_ruleset(
        supply_chain=_load("supply_chain.json"),
        exposure=_load("stock_exposure.json"),
        templates=_load("news_templates.json"),
        industries=_load("industries.json"),
        stock_pool=_load("stock_pool.json"),
        clock_rules=clock_rules,
    )


def clock_point(clock_rules: int, tt: int) -> tuple[int, int]:
    """交易 tick tt -> (推进用的全局 tick, 游戏分钟)。

    v1：tick 即 tt，分钟固定为 TRADING_MINUTE（与改动前一致）。
    v2：与服务层 save.tick / clock_minute 同口径（9:30 为 0，9:31 为 1，换日后同样自 9:30 计）。
    """
    if clock_rules == CLOCK_RULES_V1:
        return tt, TRADING_MINUTE
    day, offset = divmod(tt, timebase(clock_rules).ticks_per_day)
    return v2_tick_of(day, offset), v2_minute_of_offset(offset)


def _eligible(ev) -> bool:
    """排除 priced_in 与最终辟谣的传闻。"""
    if ev.expectation == "priced_in":
        return False
    return not (ev.rumor is not None and not ev.rumor.truth)


def _excess(prices, members, start, end, market):
    """等权收益（members 的均值）扣除全市场均值；返回浮点。"""
    p0, p1 = prices[start], prices[end]
    ind = sum(p1[i] / p0[i] - 1 for i in members) / len(members)
    return ind - market


def simulate_seed(args: tuple[int, int, int]) -> dict:
    seed, days, clock_rules = args
    tpd = timebase(clock_rules).ticks_per_day  # 每交易日的 tick 数
    window = tpd  # 发布后观察窗口：1 个交易日
    tail = TAIL_TICKS_IN_DAYS * tpd
    rs = load_ruleset(clock_rules)
    params = save_params(seed, rs)
    pool = _load("stock_pool.json")
    ranges = {i["name"]: i["base_price_range_yuan"] for i in _load("industries.json")}
    state = me.init_market(seed, pool, AS_OF, ranges)
    for s in state["stocks"]:
        s["history"] = s["history"][-1:]  # 只保留最后一根 K 线，加快推进

    events_by_day: dict[int, tuple] = {}

    def events(day: int):
        if day not in events_by_day:
            events_by_day[day] = generate_day(seed, day, rs, params)
        return events_by_day[day]

    total_ticks = days * tpd
    # 价格序列按行存为 int64 数组：v2 单 seed 约 2.9 万行 × 385 只，用 list 会占用数百 MB
    prices = [array("q", (s["price"] for s in state["stocks"]))]
    breaker_ticks = 0
    drift_day_sum = []  # 每日全市场等权平均的累计漂移（ppm）
    for day in range(days):
        plan = build_day_plan(day, [e for d in plan_window(day) for e in events(d)], rs, params)
        day_total = 0
        for offset in range(tpd):
            tt = day * tpd + offset
            if tt == 0:
                continue  # 第 0 日的 offset 0 不会被推进到
            drift = plan[offset]
            day_total += sum(drift.values())
            tick, minute = clock_point(clock_rules, tt)
            state = me.advance(state, seed, tick, minute, drift=drift, rules=clock_rules)
            prices.append(array("q", (s["price"] for s in state["stocks"])))
            if state["breaker"]:
                breaker_ticks += 1
        drift_day_sum.append(day_total / len(pool))
    assert len(prices) == total_ticks

    result = {
        "seed": seed,
        "breaker_ticks": breaker_ticks,
        "drift_day_mean_ppm": drift_day_sum,
        "source": [0, 0],
        "hop1": {1: [0, 0], 2: [0, 0], 3: [0, 0]},
        "limit_leader": [0, 0],
        "limit_normal": [0, 0],
        "limit_baseline": [0, 0],
        "limit_base_leader": [0, 0],
        "limit_base_normal": [0, 0],
        "event_counts": {"major": 0, "minor": 0},
    }
    n_stocks = len(pool)
    market_cache: dict[tuple[int, int], float] = {}

    def market_ret(a: int, b: int) -> float:
        key = (a, b)
        if key not in market_cache:
            market_cache[key] = (
                sum(prices[b][i] / prices[a][i] - 1 for i in range(n_stocks)) / n_stocks
            )
        return market_cache[key]

    def touched(day: int, idx: int) -> bool:
        prev = prices[tpd * day - 1][idx] if day >= 1 else prices[0][idx]
        up, down = limit_up_cents(prev), limit_down_cents(prev)
        lo = max(tpd * day, 1)
        return any(
            prices[t][idx] in (up, down) for t in range(lo, min(tpd * day + tpd, total_ticks))
        )

    all_events = [e for d in range(days) for e in events(d)]
    major_event_days = set()
    for ev in all_events:
        result["event_counts"]["major" if ev.major else "minor"] += 1
        p = ev.publish_trading_tick
        if not ev.major or ev.scope != "industry" or not _eligible(ev):
            continue
        if ev.trading_day < 1 or p + window + tail >= total_ticks:
            continue
        major_event_days.add(ev.trading_day)
        src = rs.industry_index[ev.source_industry]
        members = rs.industry_stocks[src]
        excess = _excess(prices, members, p - 1, p + window, market_ret(p - 1, p + window))
        result["source"][0] += 1
        result["source"][1] += int(excess * ev.sentiment > 0)
        for imp in ev.impacts:
            if imp.hop != 1:
                continue
            node = rs.industry_index[imp.industry]
            via = rs.industry_index[imp.via_industry]
            strength = next(e.strength for e in rs.out_edges[via] if e.dst == node)
            start = p + imp.delay_ticks - 1
            end = start + window + 1
            if end >= total_ticks:
                continue
            ex = _excess(prices, rs.industry_stocks[node], start, end, market_ret(start, end))
            expected = 1 if imp.scale_ppm * ev.sentiment > 0 else -1
            result["hop1"][strength][0] += 1
            result["hop1"][strength][1] += int(ex * expected > 0)
        for idx in members:
            key = "limit_leader" if rs.stocks[idx].leader else "limit_normal"
            result[key][0] += 1
            result[key][1] += int(touched(ev.trading_day, idx))
    # 无重大事件的交易日里，随机游走自带的触板率（基线，分龙头 / 普通统计）
    for day in range(2, days - 1):
        if day in major_event_days:
            continue
        for idx in range(0, n_stocks, 7):
            hit = int(touched(day, idx))
            split = "limit_base_leader" if rs.stocks[idx].leader else "limit_base_normal"
            result[split][0] += 1
            result[split][1] += hit
            result["limit_baseline"][0] += 1
            result["limit_baseline"][1] += hit
    return result


def measure_plan_timing(seed: int, days: int, clock_rules: int) -> tuple[list[float], list[float]]:
    rs = load_ruleset(clock_rules)
    params = save_params(seed, rs)
    warm: list[float] = []
    cold: list[float] = []
    cache: dict[int, tuple] = {}
    for day in range(c.LOOKBACK_DAYS, days):
        window = plan_window(day)
        for d in window:
            if d not in cache:
                cache[d] = generate_day(seed, d, rs, params)
        events = [e for d in window for e in cache[d]]
        t0 = time.perf_counter()
        build_day_plan(day, events, rs, params)
        warm.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        fresh = [e for d in window for e in generate_day(seed, d, rs, params)]
        build_day_plan(day, fresh, rs, params)
        cold.append((time.perf_counter() - t0) * 1000)
    return warm, cold


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _ratio(pair: list[int]) -> float:
    return pair[1] / pair[0] if pair[0] else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--days", type=int, default=300, help="交易日数")
    parser.add_argument(
        "--clock-rules",
        type=int,
        choices=(CLOCK_RULES_V1, CLOCK_RULES_V2),
        default=CLOCK_RULES_V1,
        help="时钟规则版本：1 = v1（每交易日 20 tick，默认）；2 = v2（每交易日 242 tick）",
    )
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--seed-base", type=int, default=1000, help="第 i 个 seed = seed-base + i")
    parser.add_argument("--json", action="store_true", help="另输出机器可读的指标 JSON")
    args = parser.parse_args()

    rules = args.clock_rules
    tpd = timebase(rules).ticks_per_day
    period_days = major_period_days(tpd)  # 重大事件周期（交易日数）：v1 12，v2 1
    refresh = REFRESH_SECONDS[rules]
    plan_target = PLAN_P95_MS[rules]

    seeds = [args.seed_base + i for i in range(args.seeds)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(simulate_seed, [(s, args.days, rules) for s in seeds]))
    elapsed = time.time() - t0

    def total(key: str) -> list[int]:
        return [sum(r[key][0] for r in results), sum(r[key][1] for r in results)]

    hop1 = {
        s: [sum(r["hop1"][s][0] for r in results), sum(r["hop1"][s][1] for r in results)]
        for s in (1, 2, 3)
    }
    source, leader, normal, baseline = (
        total("source"),
        total("limit_leader"),
        total("limit_normal"),
        total("limit_baseline"),
    )
    base_leader, base_normal = total("limit_base_leader"), total("limit_base_normal")
    day_means = [x for r in results for x in r["drift_day_mean_ppm"]]
    mean_drift = statistics.fmean(day_means)
    breakers = sum(r["breaker_ticks"] for r in results)

    # 频率：纯由 (seed, 周期) 决定，不需要推进行情
    periods = args.days // period_days
    counts = [len(major_days(s, p, tpd)) for s in seeds for p in range(periods)]
    two_share = counts.count(2) / len(counts)
    mean_count = statistics.fmean(counts)
    period_ticks = period_days * tpd  # v1 240，v2 242
    interval_min = period_ticks * refresh / 60 / mean_count

    warm, cold = measure_plan_timing(seeds[0], min(args.days, 120), rules)

    rows = [
        (
            "源行业一致率",
            _ratio(source),
            f">= {SOURCE_CONSISTENT_MIN:.0%}",
            _ratio(source) >= SOURCE_CONSISTENT_MIN,
            f"n={source[0]}",
        ),
        (
            "一跳 强度3 一致率",
            _ratio(hop1[3]),
            f">= {HOP1_S3_MIN:.0%}",
            _ratio(hop1[3]) >= HOP1_S3_MIN,
            f"n={hop1[3][0]}",
        ),
        ("一跳 强度2 一致率", _ratio(hop1[2]), "(参考)", True, f"n={hop1[2][0]}"),
        (
            "一跳 强度1 一致率",
            _ratio(hop1[1]),
            f"{HOP1_S1_RANGE[0]:.0%}-{HOP1_S1_RANGE[1]:.0%}",
            HOP1_S1_RANGE[0] <= _ratio(hop1[1]) <= HOP1_S1_RANGE[1],
            f"n={hop1[1][0]}",
        ),
        (
            "龙头事件当日触板率",
            _ratio(leader),
            f"<= {LEADER_LIMIT_MAX:.0%}",
            _ratio(leader) <= LEADER_LIMIT_MAX,
            f"n={leader[0]}",
        ),
        (
            "普通成分股触板率",
            _ratio(normal),
            f"<= {NORMAL_LIMIT_MAX:.0%}",
            _ratio(normal) <= NORMAL_LIMIT_MAX,
            f"n={normal[0]}",
        ),
        ("(基线)无重大事件日触板率", _ratio(baseline), "(参考)", True, f"n={baseline[0]}"),
        ("(非事件日)龙头触板率", _ratio(base_leader), "(参考)", True, f"n={base_leader[0]}"),
        ("(非事件日)普通成分股触板率", _ratio(base_normal), "(参考)", True, f"n={base_normal[0]}"),
        (
            "全市场日均漂移(ppm)",
            mean_drift,
            f"|x| <= {MEAN_DRIFT_MAX_PPM}",
            abs(mean_drift) <= MEAN_DRIFT_MAX_PPM,
            f"days={len(day_means)}",
        ),
        ("熔断触发 tick 数", breakers, "== 0", breakers == 0, ""),
        (
            "两条重大事件的周期占比",
            two_share,
            f"{TWO_EVENT_SHARE[0]:.0%}-{TWO_EVENT_SHARE[1]:.0%}",
            TWO_EVENT_SHARE[0] <= two_share <= TWO_EVENT_SHARE[1],
            f"periods={len(counts)}",
        ),
        (
            "每周期重大事件条数",
            f"{min(counts)}-{max(counts)}",
            "1-2",
            min(counts) >= 1 and max(counts) <= 2,
            f"mean={mean_count:.2f}",
        ),
        (
            "重大事件平均间隔(分钟)",
            interval_min,
            f"{INTERVAL_MINUTES[0]:g}-{INTERVAL_MINUTES[1]:g}",
            INTERVAL_MINUTES[0] <= interval_min <= INTERVAL_MINUTES[1],
            f"刷新 {refresh:g}s/tick",
        ),
        (
            "单日计划构建 p95(ms)",
            p95(warm),
            f"< {plan_target:g}",
            p95(warm) < plan_target,
            f"冷启动 p95={p95(cold):.1f}ms",
        ),
    ]
    minor = sum(r["event_counts"]["minor"] for r in results)
    major = sum(r["event_counts"]["major"] for r in results)
    print(
        f"事件行情仿真：时钟 v{rules}（每交易日 {tpd} tick，周期 {period_days} 日）；"
        f"{args.seeds} 个 seed × {args.days} 个交易日，用时 {elapsed:.0f}s；"
        f"重大 {major} / 小快讯 {minor} 条"
    )
    width = max(len(r[0]) for r in rows)
    ok_all = True
    for name, value, target, ok, note in rows:
        shown = f"{value:.3f}" if isinstance(value, float) else str(value)
        ok_all &= ok
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {shown:>9}  目标 {target:<10} {note}"
        )
    if args.json:
        print(json.dumps({r[0]: r[1] for r in rows}, ensure_ascii=False, default=str))
    print("ALL PASS" if ok_all else "有指标未达标：只调 domain/events/constants.py 后重跑")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
