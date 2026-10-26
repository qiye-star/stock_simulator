"""v2 行情引擎行为（07 §9.1）：换日结构、价格约束、成交量单调、档位纯函数、单股重放一致。"""

import copy
import json
from datetime import date

from stocksim.domain import clock as c
from stocksim.domain import market_engine as me
from stocksim.domain.rules import is_within_limits

AS_OF = date(2026, 10, 23)
RANGES = {"default": [5, 100]}


def _pool(n: int = 6, bull_idx: int | None = 0) -> list[dict]:
    return [
        {
            "code": f"{600000 + i:06d}",
            "name": f"S{i}",
            "industry": "x",
            "profile": "bull_bias" if i == bull_idx else "normal",
        }
        for i in range(n)
    ]


def _steps(state, seed, max_day):
    """从 9:30 逐分钟推进（只对交易分钟调用 advance），直到换到 max_day 日为止。"""
    m, tick = c.V2_START_MINUTE, 0
    while state["trading_day"] < max_day:
        tick += 1
        m = c.advance_minute(m)
        if not c.is_trading_time(m):
            continue
        before = state
        state = me.advance(before, seed, tick, m, rules=c.CLOCK_RULES_V2)
        yield tick, m, before, state


def test_same_seed_same_result_and_inputs_not_mutated():
    stocks = _pool()
    a = me.init_market(7, stocks, AS_OF, RANGES)
    snapshot = copy.deepcopy(a)
    b = me.advance(a, 7, 1, 571, rules=2)
    assert a == snapshot  # 入参未修改
    assert me.advance(a, 7, 1, 571, rules=2) == b
    assert me.advance(a, 8, 1, 571, rules=2) != b


def test_day_structure_rolls_only_at_next_open():
    stocks = _pool()
    state = me.init_market(11, stocks, AS_OF, RANGES)
    steps = list(_steps(state, 11, 3))
    assert len(steps) == 3 * 242  # tt 1..726
    rolls = [
        (tick, m, after["trading_day"])
        for tick, m, before, after in steps
        if after["trading_day"] != before["trading_day"]
    ]
    assert [m for _, m, _ in rolls] == [c.MORNING_OPEN, c.MORNING_OPEN, c.MORNING_OPEN]
    assert [d for _, _, d in rolls] == [1, 2, 3]
    assert [
        after["trading_tick"]
        for _, _, before, after in steps
        if after["trading_day"] != before["trading_day"]
    ] == [242, 484, 726]
    # 15:00 收盘（tt 241）不换日
    close_step = next(s for s in steps if s[1] == c.AFTERNOON_CLOSE)
    assert close_step[2]["trading_day"] == close_step[3]["trading_day"] == 0


def test_prev_close_equals_previous_close_and_limits_hold():
    stocks = _pool()
    state = me.init_market(12, stocks, AS_OF, RANGES)
    for _tick, _m, before, after in _steps(state, 12, 2):
        assert after["breaker"] == {}
        for s in after["stocks"]:
            assert is_within_limits(int(s["price"]), int(s["prev_close"]))
        if after["trading_day"] != before["trading_day"]:
            for sb, sa in zip(before["stocks"], after["stocks"], strict=True):
                assert sa["prev_close"] == sb["price"]
                # 换日 tick 先滚动再累加：当日量从本 tick 的增量开始
                assert 1 <= sa["daily_volume"] <= sa["prev_daily_volume"] * 2
                assert sa["prev_daily_volume"] == sb["daily_volume"]


def test_daily_volume_monotone_within_day_and_positive_increment():
    stocks = _pool()
    state = me.init_market(13, stocks, AS_OF, RANGES)
    for _tick, _m, before, after in _steps(state, 13, 1):
        if after["trading_day"] != before["trading_day"]:
            continue
        for sb, sa in zip(before["stocks"], after["stocks"], strict=True):
            assert sa["daily_volume"] - sb["daily_volume"] >= 1
            assert sa["volume"] == sa["daily_volume"]


def test_regime_is_pure_function_of_seed_day_idx():
    for idx in range(20):
        vol, trend = me._day_regime(99, 3, idx)
        assert (vol, trend) == me._day_regime(99, 3, idx)
        assert vol in {750_000, 1_000_000, 1_500_000, 2_500_000}
        assert trend == 0 or 400 <= abs(trend) <= 700


def test_single_stock_replay_matches_full_market():
    """分时重放（intraday）的前提：单只股票的状态推进与全市场逐 tick 相同（含日切换）。"""
    stocks = _pool()
    full = me.init_market(21, stocks, AS_OF, RANGES)
    solo = {
        "trading_tick": 0,
        "trading_day": 0,
        "breaker": {},
        "stocks": [copy.deepcopy(full["stocks"][3])],
    }
    for tick, m, _before, after in _steps(full, 21, 2):
        solo = me.advance(solo, 21, tick, m, rules=c.CLOCK_RULES_V2)
        assert solo["stocks"][0]["price"] == after["stocks"][3]["price"]
        assert solo["stocks"][0]["daily_volume"] == after["stocks"][3]["daily_volume"]


def test_drift_none_and_empty_are_identical_and_drift_moves_price():
    stocks = _pool()
    state = me.init_market(31, stocks, AS_OF, RANGES)
    a = me.advance(state, 31, 1, 571, rules=2)
    assert me.advance(state, 31, 1, 571, drift=None, rules=2) == a
    assert me.advance(state, 31, 1, 571, drift={}, rules=2) == a
    up = me.advance(state, 31, 1, 571, drift={1: 50_000}, rules=2)
    assert up["stocks"][1]["price"] >= a["stocks"][1]["price"]


def test_non_trading_minutes_are_noop():
    stocks = _pool()
    state = me.init_market(41, stocks, AS_OF, RANGES)
    for minute in (569, 691, 778, 1000):  # 900 是收盘 tick，属于交易分钟
        out = me.advance(state, 41, 1, minute, rules=2)
        assert out == state


def test_bull_bias_is_mostly_up_over_30_days():
    stocks = _pool(bull_idx=0)
    state = me.init_market(51, stocks, AS_OF, RANGES)
    ups = total = 0
    for _tick, _m, before, after in _steps(state, 51, 30):
        if after["trading_day"] != before["trading_day"]:
            sb = before["stocks"][0]  # 换日前的状态即已收盘的一日
            total += 1
            ups += int(sb["price"]) > int(sb["prev_close"])
    assert total == 30
    assert ups / total >= 0.7


def test_daily_volume_on_average_tracks_previous_day():
    """成交量口径：整日成交量期望约等于前一日（07 §4.5）。"""
    stocks = _pool(n=20, bull_idx=None)
    state = me.init_market(61, stocks, AS_OF, RANGES)
    ratios = []
    for _tick, _m, before, after in _steps(state, 61, 3):
        if after["trading_day"] != before["trading_day"]:
            for sb in before["stocks"]:
                if sb["prev_daily_volume"] > 0:
                    ratios.append(sb["daily_volume"] / sb["prev_daily_volume"])
    ratios.sort()
    median = ratios[len(ratios) // 2]
    assert 0.5 <= median <= 2.0


def test_state_is_json_serialisable_and_has_no_regime_leak_into_payload():
    stocks = _pool()
    state = me.init_market(71, stocks, AS_OF, RANGES)
    out = me.advance(state, 71, 1, 571, rules=2)
    assert "regime" in out  # 进程内缓存
    json.dumps(out["stocks"])
    assert "regime" not in me.init_market(71, stocks, AS_OF, RANGES)
