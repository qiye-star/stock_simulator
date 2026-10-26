"""日计划：漂移上限、单股重放一致、熔断/涨跌停安全、快讯区间（01 §5.5-§5.6、§12.1）。"""

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from stocksim.domain import market_engine as me
from stocksim.domain.events import (
    build_day_plan,
    generate_day,
    news_at,
    news_between,
    news_window,
    plan_window,
    save_params,
    stock_beta_ppm,
)
from stocksim.domain.events import constants as c
from stocksim.domain.events.path import eval_path
from stocksim.domain.money import round_half_up_div
from stocksim.domain.rules import is_within_limits

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"
POOL = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
RANGES = {
    i["name"]: i["base_price_range_yuan"]
    for i in json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
}
AS_OF = dt.date(2026, 10, 23)
MINUTE = 600  # 交易时段内（引擎只关心是否交易时段）


class _Plans:
    """测试内的简易缓存：按日缓存事件与计划。"""

    def __init__(self, seed, ruleset):
        self.seed, self.ruleset = seed, ruleset
        self.params = save_params(seed, ruleset)
        self._events, self._plans = {}, {}

    def events(self, day):
        if day not in self._events:
            self._events[day] = generate_day(self.seed, day, self.ruleset, self.params)
        return self._events[day]

    def window(self, day):
        return [e for d in plan_window(day) for e in self.events(d)]

    def plan(self, day):
        if day not in self._plans:
            self._plans[day] = build_day_plan(day, self.window(day), self.ruleset, self.params)
        return self._plans[day]

    def drift(self, tt):
        return self.plan(tt // 20)[tt % 20]


@pytest.fixture(scope="module")
def plans(event_ruleset):
    return _Plans(2024, event_ruleset)


def test_plan_shape_and_drift_cap(plans, event_ruleset):
    for day in range(0, 120):
        plan = plans.plan(day)
        assert len(plan) == 20
        for tick_drift in plan:
            for idx, value in tick_drift.items():
                cap = (
                    c.BULL_BIAS_DRIFT_CAP_PPM[event_ruleset.clock_rules]
                    if event_ruleset.stocks[idx].profile == "bull_bias"
                    else c.DRIFT_CAP_PPM
                )
                assert value != 0 and abs(value) <= cap


def test_plan_is_deterministic_and_event_order_independent(plans, event_ruleset):
    window = plans.window(40)
    a = build_day_plan(40, window, event_ruleset, plans.params)
    b = build_day_plan(40, list(reversed(window)), event_ruleset, plans.params)
    assert a == b == plans.plan(40)


def test_breaker_never_reachable_by_construction(plans, event_ruleset):
    """随机波动上界 + 漂移上界 < 5% 熔断阈值（普通股 ±2%，bull_bias 最高 +3%）。"""
    breaker_ppm = 50_000
    for day in range(0, 400):
        for tick_drift in plans.plan(day):
            for idx, value in tick_drift.items():
                noise = 30_000 if event_ruleset.stocks[idx].profile == "bull_bias" else 20_000
                assert abs(value) + noise < breaker_ppm


def test_unclamped_drift_sums_back_to_cumulative_value(event_ruleset, event_params):
    """每个“事件×股票”只舍入一次：逐 tick 差分求和等于累计值（未被截断时）。"""
    events = [
        e
        for d in range(0, 40)
        for e in generate_day(2024, d, event_ruleset, event_params)
        if e.scope == "industry" and not e.major
    ][:6]
    checked = 0
    for ev in events:
        total = {}
        for day in range(max(0, ev.trading_day - 3), ev.trading_day + 17):
            plan = build_day_plan(day, [ev], event_ruleset, event_params)
            for tick_drift in plan:
                for idx, value in tick_drift.items():
                    total[idx] = total.get(idx, 0) + value
        node = event_ruleset.industry_index[ev.source_industry]
        for stock, weight in event_ruleset.industry_members[node]:
            hits = [
                imp
                for imp in ev.impacts
                if any(
                    s == stock
                    for s, _ in event_ruleset.industry_members[
                        event_ruleset.industry_index[imp.industry]
                    ]
                )
            ]
            if stock not in total or len(hits) != 1:
                continue  # 多个节点叠加的股票各自舍入，不做精确比较
            beta = stock_beta_ppm(event_ruleset, event_params, stock)
            final = eval_path(ev.knots, 10_000)
            expected = round_half_up_div(
                ev.magnitude_ppm * beta * hits[0].scale_ppm * weight * final, 10**24
            )
            assert total[stock] == expected
            checked += 1
    assert checked > 5


def test_news_between_equals_per_tick_news_at(plans):
    day_lo, day_hi = 10, 14
    events = [e for d in news_window(day_hi) for e in plans.events(d)]
    events += [e for d in news_window(day_lo) for e in plans.events(d)]
    unique = {e.event_id: e for e in events}
    events = list(unique.values())
    lo, hi = 20 * day_lo, 20 * day_hi
    merged = news_between(events, lo, hi)
    stepped = tuple(pair for tt in range(lo + 1, hi + 1) for pair in news_at(events, tt))
    assert merged == stepped and len(merged) > 10
    ticks = [item.trading_tick for _, item in merged]
    assert ticks == sorted(ticks) and all(lo < t <= hi for t in ticks)


def _single_stock_sim(state, idx):
    stock = copy.deepcopy(state["stocks"][idx])
    return {
        "trading_tick": state["trading_tick"],
        "trading_day": state["trading_day"],
        "breaker": {},
        "stocks": [stock],
    }


def test_single_stock_replay_matches_full_market_advance(plans):
    """services.intraday 用单只股票的 sim 重放：带漂移时也必须逐 tick 一致。"""
    seed = 2024
    full = me.init_market(seed, POOL, AS_OF, RANGES)
    target = max(
        range(len(POOL)),
        key=lambda i: sum(abs(plans.drift(tt).get(i, 0)) for tt in range(1, 160)),
    )
    sim = _single_stock_sim(full, target)
    for tick in range(1, 161):
        tt = full["trading_tick"] + 1
        drift = plans.drift(tt)
        full = me.advance(full, seed, tick, MINUTE, drift=drift)
        sim = me.advance(sim, seed, tick, MINUTE, drift={target: drift.get(target, 0)})
        a, b = full["stocks"][target], sim["stocks"][0]
        assert (a["price"], a["daily_volume"]) == (b["price"], b["daily_volume"]), tick
    assert any(plans.drift(tt).get(target) for tt in range(1, 161))


def test_event_driven_market_stays_within_limits_without_breaker(event_ruleset):
    for seed in (2024, 7):
        p = _Plans(seed, event_ruleset)
        state = me.init_market(seed, POOL, AS_OF, RANGES)
        for stock in state["stocks"]:
            stock["history"] = stock["history"][-1:]
        for tick in range(1, 20 * 40 + 1):
            tt = state["trading_tick"] + 1
            state = me.advance(state, seed, tick, MINUTE, drift=p.drift(tt))
            assert not state["breaker"], (seed, tick)
            if tick % 20 == 0:
                for stock in state["stocks"]:
                    assert is_within_limits(stock["price"], stock["prev_close"])
        for stock in state["stocks"]:
            assert is_within_limits(stock["price"], stock["prev_close"])
