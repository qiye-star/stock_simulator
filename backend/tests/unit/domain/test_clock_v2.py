"""时钟 v2 纯函数：相位、撮合窗、跳过表、对齐不变量、墙钟调度（07 §1、§4.1、§5.2、§6.5）。"""

import pytest

from stocksim.domain import clock as c


@pytest.mark.parametrize(
    ("minute", "phase", "order"),
    [
        (0, "pre_open", False),
        (569, "pre_open", False),
        (570, "morning", True),
        (689, "morning", True),
        (690, "lunch", False),
        (691, "lunch", False),
        (779, "lunch", False),
        (780, "afternoon", True),
        (899, "afternoon", True),
        (900, "closed", False),
        (901, "closed", False),
        (1439, "closed", False),
    ],
)
def test_v2_phase_and_order_window(minute, phase, order):
    assert c.phase_of(minute, c.CLOCK_RULES_V2) == phase
    assert c.is_order_time(minute, c.CLOCK_RULES_V2) is order


def test_v1_phase_keeps_closed_endpoints():
    # v1 与旧行为一致：11:30 与 15:00 仍可下单
    assert c.phase_of(690, c.CLOCK_RULES_V1) == "morning"
    assert c.phase_of(900, c.CLOCK_RULES_V1) == "afternoon"
    assert c.is_order_time(690, c.CLOCK_RULES_V1) is True
    assert c.is_order_time(900) is True
    assert c.phase_of(901, c.CLOCK_RULES_V1) == "closed"


@pytest.mark.parametrize(
    ("minute", "kind", "target"),
    [
        (0, "open", 570),
        (569, "open", 570),
        (600, "lunch", 690),
        (690, "reopen", 780),
        (700, "reopen", 780),
        (800, "close", 900),
        (900, "open", 570),
    ],
)
def test_next_event_v2(minute, kind, target):
    assert c.next_event_of(minute, c.CLOCK_RULES_V2) == (kind, target)


@pytest.mark.parametrize(
    ("minute", "label"),
    [
        (570, "early_bird"),
        (575, "early_bird"),
        (576, "trading"),
        (690, "closed"),
        (780, "afternoon_open"),
        (785, "afternoon_open"),
        (786, "trading"),
        (895, "night_owl"),
        (899, "night_owl"),
        (900, "closed"),
        (700, "closed"),
    ],
)
def test_session_label_v2(minute, label):
    assert c.session_label_v2(minute) == label


def test_night_owl_window_by_rules():
    assert c.is_night_owl_window(899, c.CLOCK_RULES_V2)
    assert c.is_night_owl_window(895, c.CLOCK_RULES_V2)
    assert not c.is_night_owl_window(894, c.CLOCK_RULES_V2)
    assert not c.is_night_owl_window(695, c.CLOCK_RULES_V2)
    assert c.is_night_owl_window(695)  # v1 默认
    assert not c.is_night_owl_window(899)  # v1 默认


def test_skip_target_v2_full_table():
    table = {
        570: 689,
        600: 689,
        688: 689,
        689: 690,
        690: 779,
        778: 779,
        779: 780,
        780: 899,
        898: 899,
        899: 900,
        900: 569,
        1000: 569,
        0: 569,
        568: 569,
        569: 570,
    }
    for minute, target in table.items():
        assert c.skip_target_v2(minute) == target, minute
        assert c.skip_ticks(minute, c.skip_target_v2(minute)) >= 1


def test_eight_skips_complete_one_trading_day():
    m = c.V2_START_MINUTE
    trading_minutes = 0
    skips = 0
    while True:
        target = c.skip_target_v2(m)
        steps = c.skip_ticks(m, target)
        # 统计本次跳过经过的交易分钟（不含起点，含终点）
        cur = m
        for _ in range(steps):
            cur = c.advance_minute(cur)
            trading_minutes += c.is_trading_time(cur)
        m = target
        skips += 1
        if m == c.V2_START_MINUTE:
            break
    assert skips == 8
    assert trading_minutes == c.V2_TRADING_TICKS_PER_DAY


def test_expected_offset_matches_minute_walk():
    """逐分钟走两天：交易分钟 tt+1，任何分钟 tt%242 都等于 v2_expected_offset(m)（对齐不变量）。"""
    tb = c.timebase(c.CLOCK_RULES_V2)
    m = c.V2_START_MINUTE
    tt = 0
    assert tb.offset_of(tt) == c.v2_expected_offset(m)
    for _ in range(2 * 1440):
        m = c.advance_minute(m)
        if c.is_trading_time(m):
            tt += 1
        assert tb.offset_of(tt) == c.v2_expected_offset(m), (m, tt)
    assert tb.day_of(tt) == 2


def test_offset_and_global_tick_closed_form():
    assert [c.v2_minute_of_offset(o) for o in (0, 120, 121, 241)] == [570, 690, 780, 900]
    assert c.v2_tick_of(0, 0) == 0
    assert c.v2_tick_of(0, 120) == 120
    assert c.v2_tick_of(0, 121) == 210  # 780 - 570 = 210
    assert c.v2_tick_of(1, 0) == 1440
    with pytest.raises(ValueError):
        c.v2_minute_of_offset(242)


def test_timebase_v1_matches_formula():
    tb = c.timebase(c.CLOCK_RULES_V1)
    assert tb.ticks_per_day == 20
    for tt in range(0, 100):
        assert tb.day_of(tt) == tt // 20
        assert tb.offset_of(tt) == tt % 20
        assert tb.rolls_at(tt) == (tt > 0 and tt % 20 == 0)
    assert tb.first_tt(3) == 60
    assert c.timebase(c.CLOCK_RULES_V2).ticks_per_day == 242


def test_unknown_rules_rejected():
    with pytest.raises(ValueError):
        c.timebase(3)
    with pytest.raises(ValueError):
        c.is_order_time(600, 3)


def test_next_step_v2_table():
    kw = {"ms_per_minute": 5000, "lunch_dwell_ms": 5000, "close_dwell_ms": 15000}
    assert c.next_step_v2(569, 0, **kw) == c.Step("tick", 5000, 1)
    assert c.next_step_v2(689, 0, **kw) == c.Step("tick", 5000, 1)
    assert c.next_step_v2(690, 0, **kw) == c.Step("jump", 5000, 89)
    assert c.next_step_v2(779, 0, **kw) == c.Step("tick", 5000, 1)
    assert c.next_step_v2(899, 0, **kw) == c.Step("tick", 5000, 1)
    assert c.next_step_v2(900, 0, **kw) == c.Step("jump", 15000, 1109)
    assert c.next_step_v2(0, 7, **kw) == c.Step("jump", 7, 569)
    assert c.next_step_v2(700, 7, **kw) == c.Step("jump", 7, 79)
    assert c.next_step_v2(1000, 7, **kw) == c.Step("jump", 7, 1009)


def test_plan_catchup_exact_boundary():
    kw = {"ms_per_minute": 5000, "max_trading_ticks": 300}
    # 恰好到期：anchor + 5000 == now，推进 1 分钟
    plan = c.plan_catchup_v2(569, 0, 5000, **kw)
    assert (plan.minutes, plan.trading_ticks, plan.anchor_ms, plan.truncated) == (1, 1, 5000, False)
    # 差 1 ms 不推进
    plan = c.plan_catchup_v2(569, 0, 4999, **kw)
    assert (plan.minutes, plan.anchor_ms) == (0, 0)


def test_plan_catchup_crosses_lunch_and_dwells():
    kw = {
        "ms_per_minute": 5000,
        "lunch_dwell_ms": 5000,
        "close_dwell_ms": 15000,
        "max_trading_ticks": 300,
    }
    # 11:29 锚点于 0；到 11:30 (5s)，停 5s 后 12:59 (+89)，到 13:00 再 +5s
    plan = c.plan_catchup_v2(689, 0, 10_000, **kw)
    assert plan.minutes == 90 and plan.trading_ticks == 1 and plan.anchor_ms == 10_000
    # 停留中（now 未到停留终点）：停在 11:30
    plan = c.plan_catchup_v2(690, 0, 4_000, **kw)
    assert (plan.minutes, plan.anchor_ms) == (0, 0)
    # 停留刚好结束
    plan = c.plan_catchup_v2(690, 0, 5_000, **kw)
    assert (plan.minutes, plan.anchor_ms) == (89, 5_000)


def test_plan_catchup_overnight_and_zero_dwell():
    kw = {
        "ms_per_minute": 1000,
        "lunch_dwell_ms": 0,
        "close_dwell_ms": 0,
        "max_trading_ticks": 10_000,
    }
    # 15:00 收盘，停留为 0：立即跳到次日 9:29，再 1 秒到 9:30
    plan = c.plan_catchup_v2(900, 0, 1_500, **kw)
    assert plan.minutes == 1109 + 1
    assert plan.trading_ticks == 1
    assert plan.anchor_ms == 1_000 * 1  # 9:29 立即（anchor 0），9:30 在 1000ms
    # 午休 0 停留：11:30 → 12:59 立即
    plan = c.plan_catchup_v2(690, 0, 0, **kw)
    assert plan.minutes == 89


def test_plan_catchup_one_full_day_exact():
    """零停留、每分钟 2500 ms：242 个交易 tick 恰好走完一个交易日，共 1440 个游戏分钟。"""
    kw = {
        "ms_per_minute": 2500,
        "lunch_dwell_ms": 0,
        "close_dwell_ms": 0,
        "max_trading_ticks": 10_000,
    }
    plan = c.plan_catchup_v2(570, 0, 242 * 2500, **kw)
    got = (plan.trading_ticks, plan.minutes, plan.anchor_ms, plan.truncated)
    assert got == (242, 1440, 605_000, False)
    plan = c.plan_catchup_v2(570, 0, 242 * 2500 - 1, **kw)
    assert (plan.trading_ticks, plan.minutes, plan.anchor_ms) == (241, 1439, 602_500)


def test_plan_catchup_multi_day_cap_truncates():
    kw = {"ms_per_minute": 2500, "lunch_dwell_ms": 5000, "close_dwell_ms": 15000}
    plan = c.plan_catchup_v2(570, 0, 10_000_000, max_trading_ticks=300, **kw)
    assert plan.trading_ticks == 300
    assert plan.truncated is True
    assert plan.anchor_ms == 10_000_000


def test_plan_catchup_no_truncation_when_exactly_at_cap():
    kw = {"ms_per_minute": 1000, "lunch_dwell_ms": 0, "close_dwell_ms": 0}
    # 从 9:30 起恰好 3 个交易 tick 到期，上限 3：不截断
    plan = c.plan_catchup_v2(570, 0, 3_000, max_trading_ticks=3, **kw)
    assert plan.trading_ticks == 3 and plan.truncated is False and plan.anchor_ms == 3_000


def test_ms_until_minute_v2():
    kw = {"ms_per_minute": 5000, "lunch_dwell_ms": 5000, "close_dwell_ms": 15000}
    assert c.ms_until_minute_v2(600, 0, 690, **kw) == 90 * 5000
    assert c.ms_until_minute_v2(690, 0, 780, **kw) == 5000 + 5000
    assert c.ms_until_minute_v2(900, 0, 570, **kw) == 15000 + 5000
    assert c.ms_until_minute_v2(569, 0, 570, **kw) == 5000


def test_v1_skip_table_unchanged():
    assert c.skip_target_minutes(600) == 689
    assert c.skip_target_minutes(690) is None  # v1 的 11:30 不再跳过
