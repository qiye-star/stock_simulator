"""每日挑战公共时间线（03 §1.2、§4.2）：tt(now) 边界、反函数、相位与 minutes_to_tt 对齐。"""

import pytest

from stocksim.domain.challenge.script import holdable_v2
from stocksim.domain.challenge.timeline import (
    build_timeline,
    minutes_to_tt,
    phase_at,
    reached_ms,
    target_tt,
)
from stocksim.domain.clock import (
    MINUTES_PER_DAY,
    V2_TRADING_TICKS_PER_DAY,
    v2_minute_of_offset,
    v2_tick_of,
)

T0 = 1_700_000_000_000
HOUR = 3_600_000
TICK = 750
LEAD = 5000
HOLDS = (100, 400, 800, 1200)
END = 1500


def _tl(**over):
    resume = [T0 + k * HOUR for k in range(len(HOLDS) + 1)]
    kw = dict(
        hold_tts=HOLDS,
        end_tt=END,
        resume_ms=resume,
        tick_ms=TICK,
        close_lead_ms=LEAD,
        min_window_ms=60_000,
    )
    kw.update(over)
    return build_timeline(**kw)


def test_build_rejects_bad_input():
    with pytest.raises(ValueError):
        _tl(hold_tts=(100, 100, 800, 1200))  # 不严格递增
    with pytest.raises(ValueError):
        _tl(hold_tts=(0, 400, 800, 1200))  # hold_1 必须 > 0
    with pytest.raises(ValueError):
        _tl(end_tt=1200)  # end 不晚于最后一个停顿
    with pytest.raises(ValueError):
        _tl(resume_ms=[T0, T0 + HOUR])  # 段数不对
    with pytest.raises(ValueError):
        _tl(resume_ms=[T0, T0 + HOUR, T0 + HOUR, T0 + 3 * HOUR, T0 + 4 * HOUR])
    with pytest.raises(ValueError):
        _tl(min_window_ms=HOUR)  # 作答窗口过短
    with pytest.raises(ValueError):
        _tl(hold_tts=())


def test_target_tt_boundaries():
    tl = _tl()
    r = tl.resume_ms
    assert target_tt(tl, r[0] - 1) == 0
    assert target_tt(tl, r[0]) == 0
    assert target_tt(tl, r[0] + TICK - 1) == 0
    assert target_tt(tl, r[0] + TICK) == 1
    hold_at_1 = tl.hold_at_ms[0]
    assert hold_at_1 == r[0] + HOLDS[0] * TICK
    assert target_tt(tl, hold_at_1 - 1) == HOLDS[0] - 1
    assert target_tt(tl, hold_at_1) == HOLDS[0]  # 停顿开始
    assert target_tt(tl, r[1] - 1) == HOLDS[0]  # 停顿中
    assert target_tt(tl, r[1]) == HOLDS[0]  # 第 2 段快放从 hold_1 起
    assert target_tt(tl, r[1] + TICK) == HOLDS[0] + 1
    assert target_tt(tl, tl.ends_ms - 1) == END - 1
    assert target_tt(tl, tl.ends_ms) == END
    assert target_tt(tl, tl.ends_ms + 10 * HOUR) == END


def test_closes_and_hold_points():
    tl = _tl()
    for k in range(len(HOLDS)):
        assert tl.closes_ms[k] == tl.resume_ms[k + 1] - LEAD
        assert tl.hold_at_ms[k] < tl.closes_ms[k]
        assert target_tt(tl, tl.hold_at_ms[k]) == HOLDS[k]
        assert target_tt(tl, tl.closes_ms[k]) == HOLDS[k]


def test_target_tt_monotone_and_inverse():
    tl = _tl()
    prev = -1
    for t in range(tl.resume_ms[0] - 2000, tl.ends_ms + 2000, 997):
        cur = target_tt(tl, t)
        assert cur >= prev
        prev = cur
    for tt in range(1, END + 1):
        assert target_tt(tl, reached_ms(tl, tt)) == tt
        assert reached_ms(tl, tt) <= tl.ends_ms
    for t in range(tl.resume_ms[0], tl.ends_ms + 1, 1234):
        assert reached_ms(tl, target_tt(tl, t)) <= t
    assert reached_ms(tl, 0) == tl.resume_ms[0]
    with pytest.raises(ValueError):
        reached_ms(tl, END + 1)


def test_phase_at():
    tl = _tl()
    r = tl.resume_ms
    p = phase_at(tl, r[0] - 1)
    assert (p.phase, p.round_index, p.next_change_ms) == ("before", None, r[0])
    p = phase_at(tl, r[0])
    assert (p.phase, p.round_index, p.next_change_ms) == ("burst", 1, tl.hold_at_ms[0])
    p = phase_at(tl, tl.hold_at_ms[0])
    assert (p.phase, p.round_index, p.next_change_ms) == ("hold", 1, r[1])
    p = phase_at(tl, r[1])
    assert (p.phase, p.round_index) == ("burst", 2)
    p = phase_at(tl, r[len(HOLDS)])
    assert (p.phase, p.round_index, p.next_change_ms) == ("final", len(HOLDS), tl.ends_ms)
    p = phase_at(tl, tl.ends_ms)
    assert (p.phase, p.round_index, p.next_change_ms) == ("ended", len(HOLDS), None)


def test_holdable_v2_excludes_order_blackout():
    assert holdable_v2(0)
    assert holdable_v2(119)
    assert holdable_v2(121)
    assert holdable_v2(240)
    assert not holdable_v2(120)  # 11:30
    assert not holdable_v2(241)  # 15:00
    assert not holdable_v2(V2_TRADING_TICKS_PER_DAY + 120)
    assert not holdable_v2(3 * V2_TRADING_TICKS_PER_DAY + 241)


def test_minutes_to_tt_matches_v2_closed_form_from_open():
    # 开局 (570, tt=0)：逐分钟模拟与 v2_tick_of 闭式逐一一致，覆盖午休、隔夜、多日
    for target in range(0, 4 * V2_TRADING_TICKS_PER_DAY + 1):
        day, off = divmod(target, V2_TRADING_TICKS_PER_DAY)
        assert minutes_to_tt(570, 0, target) == v2_tick_of(day, off), target


def test_minutes_to_tt_from_arbitrary_aligned_state():
    for cur in (0, 119, 120, 121, 200, 241, 242, 300, 483):
        cur_minute = v2_minute_of_offset(cur % V2_TRADING_TICKS_PER_DAY)
        for target in (cur, cur + 1, cur + 2, cur + 121, cur + 242, cur + 500):
            cd, co = divmod(cur, V2_TRADING_TICKS_PER_DAY)
            td, to = divmod(target, V2_TRADING_TICKS_PER_DAY)
            want = v2_tick_of(td, to) - v2_tick_of(cd, co)
            assert minutes_to_tt(cur_minute, cur, target) == want, (cur, target)


def test_minutes_to_tt_crosses_lunch_and_night():
    # 14:59 (tt 240) → 次日 9:30 (tt 242)：14:59→15:00 为 1，15:00→次日 9:30 为 1110
    assert minutes_to_tt(899, 240, 242) == 1 + 1110
    # 11:29 (tt 119) → 13:00 (tt 121)：11:30 为 1 步，午休 89 分钟，13:00 为 1 步
    assert minutes_to_tt(689, 119, 121) == 91
    assert minutes_to_tt(570, 0, 0) == 0
    with pytest.raises(ValueError):
        minutes_to_tt(570, 5, 4)
    assert MINUTES_PER_DAY == 1440
