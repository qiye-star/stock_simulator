"""tick 常量已按 ticks_per_day 参数化：20 恒等；242（时钟 v2 预研）下事件仍自洽。"""

from stocksim.domain.events import (
    build_day_plan,
    day_slots,
    generate_day,
    major_days,
    max_step,
    save_params,
)
from stocksim.domain.events import constants as c
from stocksim.domain.events.timing import major_period_days, scale_bounds, scale_ticks

V2 = 242


def test_scaling_is_identity_at_reference_clock():
    assert scale_ticks(37, 20) == 37 and scale_bounds((16, 40), 20) == (16, 40)
    assert major_period_days(20) == 12


def test_scaling_is_proportional_at_v2_clock():
    assert scale_ticks(20, V2) == V2  # 一个参考交易日 = 一个 v2 交易日
    assert scale_ticks(3, V2) == 36
    assert scale_bounds((0, 17), V2) == (0, 206)
    assert major_period_days(V2) == 1  # 重大事件周期约一个时钟日


def test_v2_events_are_well_formed(event_ruleset_v2):
    rs = event_ruleset_v2
    assert rs.ticks_per_day == V2
    params = save_params(2024, rs)
    majors_per_day = []
    for day in range(0, 80):
        events = generate_day(2024, day, rs, params)
        majors_per_day.append(sum(1 for e in events if e.major))
        for e in events:
            assert V2 * day <= e.publish_trading_tick < V2 * (day + 1)
            assert abs(e.magnitude_ppm) * max_step(e.knots) <= c.IMPULSE_CAP_PPM * 1_000_000
            assert e.knots[-1][0] <= scale_ticks(c.MAX_EVENT_SPAN_TICKS, V2)
            assert e.first_seen_trading_tick >= (1 if day == 0 else 0)
        majors = [e for e in events if e.major]
        assert len({e.publish_trading_tick for e in majors}) == len(majors) or len(majors) < 2
    assert set(majors_per_day) <= {1, 2} and 2 in majors_per_day  # 每个时钟日 1-2 条
    assert [m for _, m in day_slots(2024, 0, V2)].count(True) == majors_per_day[0]
    assert all(len(major_days(2024, p, V2)) in (1, 2) for p in range(50))


def test_v2_plan_has_one_entry_per_tick_and_respects_caps(event_ruleset_v2):
    rs = event_ruleset_v2
    params = save_params(2024, rs)
    day = 5
    window = [e for d in range(0, day + 3) for e in generate_day(2024, d, rs, params)]
    plan = build_day_plan(day, window, rs, params)
    assert len(plan) == V2
    assert any(plan)
    for tick_drift in plan:
        for idx, value in tick_drift.items():
            cap = (
                c.BULL_BIAS_DRIFT_CAP_PPM[rs.clock_rules]
                if rs.stocks[idx].profile == "bull_bias"
                else c.DRIFT_CAP_PPM
            )
            assert abs(value) <= cap


def test_reference_clock_generation_unchanged_by_parameterization(event_ruleset, event_params):
    """tpd=20 与显式传入参考值等价（不引入隐式差异）。"""
    from stocksim.domain.events.generate import day_slots as ds

    assert ds(2024, 9) == day_slots(2024, 9, 20)
    assert generate_day(2024, 9, event_ruleset, event_params)


def test_v1_publish_offsets_are_the_reference_range():
    """v1 合法集与原写法 lo + rand_below(hi-lo+1) 的取值范围一致（第 0 日下限为 1）。"""
    from stocksim.domain.events.timing import publish_offsets

    assert publish_offsets(1, 20, True, 5) == tuple(range(0, 18))
    assert publish_offsets(1, 20, False, 5) == tuple(range(0, 20))
    assert publish_offsets(1, 20, True, 0) == tuple(range(1, 18))


def test_v2_publish_offsets_exclude_auction_ticks():
    from stocksim.domain.events.timing import publish_offsets

    major = publish_offsets(2, 242, True, 3)
    minor = publish_offsets(2, 242, False, 3)
    assert 120 not in major and 241 not in major and 120 not in minor and 241 not in minor
    assert len(major) == 230 and major[0] == 0 and major[-1] == 230  # [0,119] ∪ [121,230]
    assert len(minor) == 239 and minor[-1] == 239
