"""游戏时钟与交易时段（legacy 1778-1925 的分钟规则）。"""

import pytest

from stocksim.domain import clock as c


@pytest.mark.parametrize(
    "minute,trading",
    [
        (569, False),
        (570, True),
        (690, True),
        (691, False),
        (779, False),
        (780, True),
        (900, True),
        (901, False),
    ],
)
def test_trading_session_boundaries(minute, trading):
    assert c.is_trading_time(minute) is trading


@pytest.mark.parametrize(
    "minute,label",
    [
        (570, "early_bird"),
        (575, "early_bird"),
        (576, "trading"),
        (695, "night_owl"),
        (700, "night_owl"),
        (780, "afternoon_open"),
        (785, "afternoon_open"),
        (786, "trading"),
        (600, "trading"),
        (720, "closed"),
        (0, "closed"),
    ],
)
def test_session_label(minute, label):
    assert c.session_label(minute) == label


def test_advance_wraps_at_midnight():
    assert c.advance_minute(1439) == 0
    assert c.advance_minute(600, 5) == 605
    with pytest.raises(ValueError):
        c.advance_minute(600, 0)


def test_random_start_is_in_morning_session_and_deterministic():
    seen = set()
    for seed in range(300):
        m = c.random_start_minute(seed)
        assert c.MORNING_OPEN <= m <= c.MORNING_CLOSE
        assert m == c.random_start_minute(seed)
        seen.add(m)
    assert len(seen) > 50


@pytest.mark.parametrize(
    "minute,target",
    [
        (600, 689),  # 上午盘 -> 11:29
        (689, None),
        (696, 699),  # 夜猫 -> 11:39
        (699, None),
        (800, 899),  # 下午盘 -> 14:59
        (899, None),
        (100, 569),  # 开盘前 -> 9:29
        (691, 694),  # 午休 -> 11:34（legacy: cur < 695 -> 694）
        (694, 694),
        (730, 779),  # 午后未开盘 -> 12:59
        (1000, 569),  # 收盘后 -> 次日 9:29
    ],
)
def test_skip_targets(minute, target):
    assert c.skip_target_minutes(minute) == target


def test_skip_ticks_crosses_midnight():
    assert c.skip_ticks(1000, 569) == (569 - 1000 + 1440) % 1440
    assert c.skip_ticks(600, 689) == 89


def test_early_and_night_windows():
    assert c.is_early_bird_window(570) and c.is_early_bird_window(575)
    assert not c.is_early_bird_window(576)
    assert c.is_night_owl_window(695) and c.is_night_owl_window(700)
    assert not c.is_night_owl_window(701)
