#!/usr/bin/env python3
"""预测卡仿真报告（02 §13.4）：只 import `stocksim.domain`，纯标准库 + 读取仓库内的 data/*.json。

流程：build_ruleset → 逐交易 tick 用 domain.advance（drift 来自 build_day_plan）推演行情 →
每日收盘价 →
对每个重大事件按 domain.build_questions 出题，按与 services 相同的真值口径（窗口收盘 →
收盘）结算，统计：
  - 方向题各档出现率；
  - 非传闻的源行业/个股重大事件，“档位方向与 sentiment 一致”的比例（非中性档）；
  - 排序题出题率（industry/stock 重大事件）；
  - 均匀答案平均分、“只看标题”策略（sentiment 决定方向、把握 50）、理想答案（知道真值）的平均分。

用法：python3 scripts/prediction_sim_report.py --seeds 2 --days 40 --clock-rules 2
时间基：v2 每交易日 242 tick（推演时 tick 即交易 tick 序号，RNG 只需唯一即可）；v1 每交易日 20
tick。
不达标只调 domain/predictions/constants.py（本脚本不改任何领域常量）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
DATA = ROOT / "backend" / "src" / "stocksim" / "data"

from stocksim.domain.clock import v2_minute_of_offset  # noqa: E402
from stocksim.domain.events import (  # noqa: E402
    build_day_plan,
    build_ruleset,
    generate_day,
    plan_window,
    save_params,
)
from stocksim.domain.market_engine import advance, init_market  # noqa: E402
from stocksim.domain.money import round_half_up_div  # noqa: E402
from stocksim.domain.predictions import (  # noqa: E402
    BucketQ,
    QuestionContext,
    RankQ,
    Structure,
    build_questions,
)
from stocksim.domain.scoring import (  # noqa: E402
    bucket_of,
    probs_from_pick,
    rps_score,
    uniform_rps_score,
)

AS_OF = date(2026, 10, 26)


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _structure(rs) -> Structure:
    industries = rs.industries
    adj: dict[str, set[str]] = {name: set() for name in industries}
    for e in rs.edges:
        a, b = industries[e.from_idx], industries[e.to_idx]
        adj[a].add(b)
        adj[b].add(a)
    return Structure(
        industries=tuple(industries),
        stock_count={name: rs.stock_counts[i] for i, name in enumerate(industries)},
        neighbors={k: frozenset(v) for k, v in adj.items()},
        stock_total=len(rs.stocks),
        stock_names={s.code: s.name for s in rs.stocks},
    )


def simulate(seed: int, days: int, clock_rules: int, rs, stocks, ranges):
    """返回 (closes: {day: [price per stock]}, events_by_day: {day: tuple(GameEvent)})。"""
    params = save_params(seed, rs)
    state = init_market(seed, stocks, AS_OF, ranges)
    closes: dict[int, list[int]] = {-1: [s["history"][-2]["close"] for s in state["stocks"]]}
    events_cache: dict[int, tuple] = {}

    def events_of(day: int):
        if day not in events_cache:
            events_cache[day] = generate_day(seed, day, rs, params)
        return events_cache[day]

    plan_cache: dict[int, object] = {}

    def plan_of(day: int):
        if day not in plan_cache:
            window = [e for d in plan_window(day) for e in events_of(d)]
            plan_cache[day] = build_day_plan(day, window, rs, params)
        return plan_cache[day]

    offsets = range(0, 242) if clock_rules == 2 else range(0, 20)
    tick = 0
    for day in range(days):
        for offset in offsets:
            if day == 0 and offset == 0:
                continue  # 开盘 tick 0 不推进（与 _run_ticks 一致）
            tick += 1
            minute = v2_minute_of_offset(offset) if clock_rules == 2 else 570 + offset
            drift = plan_of(day)[offset]
            state = advance(state, seed, tick, minute, drift=drift, rules=clock_rules)
        closes[day] = [int(s["price"]) for s in state["stocks"]]
    return closes, events_of, params


def _change_bp(closes, members: list[int], from_day: int, to_day: int) -> int | None:
    changes = []
    for i in members:
        base = closes[from_day - 1][i]
        last = closes[to_day][i]
        if base > 0:
            changes.append(round_half_up_div((last - base) * 10_000, base))
    if not changes:
        return None
    return round_half_up_div(sum(changes), len(changes))


def report(seeds: int, days: int, clock_rules: int) -> dict:
    rs = build_ruleset(
        supply_chain=_load("supply_chain.json"),
        exposure=_load("stock_exposure.json"),
        templates=_load("news_templates.json"),
        industries=_load("industries.json"),
        stock_pool=_load("stock_pool.json"),
        version=1,
        clock_rules=clock_rules,
    )
    st = _structure(rs)
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
    buckets: Counter[int] = Counter()
    consistent = inconsistent = 0
    rank_eligible = rank_issued = 0
    uniform_sum = strat_sum = ideal_sum = n_dir = 0
    for seed in range(1, seeds + 1):
        closes, events_of, _params = simulate(seed, days, clock_rules, rs, stocks, ranges)
        for day in range(days):
            for ev in events_of(day):
                if not ev.major or not ev.news:
                    continue
                trigger = min(n.trading_tick for n in ev.news)
                d0 = trigger // (242 if clock_rules == 2 else 20)  # 与 timebase(clock_rules) 一致
                if ev.scope in ("industry", "stock"):
                    rank_eligible += 1
                if d0 + 2 >= days:
                    continue
                qs = build_questions(
                    ev,
                    QuestionContext(
                        seed=seed,
                        trigger_trading_tick=trigger,
                        structure=st,
                        clock_rules=clock_rules,
                    ),
                )
                if any(isinstance(q, RankQ) for q in qs):
                    rank_issued += 1
                dir_q = next(q for q in qs if isinstance(q, BucketQ))
                if dir_q.target_kind == "industry":
                    node = rs.industry_index[dir_q.target]
                    # 与服务层 industry_stocks 同口径（不含 extra 暴露成员）
                    members = list(rs.industry_stocks[node])
                elif dir_q.target_kind == "stock":
                    members = [rs.stock_index[dir_q.target]]
                else:
                    members = list(range(len(stocks)))
                change = _change_bp(closes, members, dir_q.from_day, dir_q.to_day)
                if change is None:
                    continue
                edges = dir_q.edges_bp
                outcome = bucket_of(change, edges)
                buckets[outcome] += 1
                n_dir += 1
                uniform_sum += uniform_rps_score(5, outcome)
                sign = 1 if ev.sentiment > 0 else -1
                if ev.kind != "rumor" and ev.scope != "market" and outcome != 2:
                    ok = (outcome >= 3 and sign > 0) or (outcome <= 1 and sign < 0)
                    consistent += ok
                    inconsistent += not ok
                title_pick = 3 if sign > 0 else 1
                strat_sum += rps_score(list(probs_from_pick(title_pick, 50, 5)), outcome)
                ideal_sum += rps_score(list(probs_from_pick(outcome, 80, 5)), outcome)
    total = max(1, n_dir)
    share = {str(b): round(100 * buckets[b] / total, 1) for b in range(5)}
    return {
        "clock_rules": clock_rules,
        "seeds": seeds,
        "days": days,
        "dir_questions": n_dir,
        "bucket_share_pct": share,
        "sentiment_consistency_pct": round(100 * consistent / max(1, consistent + inconsistent), 1),
        "rank_issue_rate_pct": round(100 * rank_issued / max(1, rank_eligible), 1),
        "avg_score_uniform": round(uniform_sum / total, 1),
        "avg_score_title_only": round(strat_sum / total, 1),
        "avg_score_ideal_pick80": round(ideal_sum / total, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--clock-rules", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    print(json.dumps(report(args.seeds, args.days, args.clock_rules), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
