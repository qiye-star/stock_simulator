"""形状曲线：差分求和、归零、priced_in 反向、步长与寿命上限（01 §5.4）。"""

import pytest

from stocksim.domain.events import constants as c
from stocksim.domain.events import eval_path, generate_day, max_step
from stocksim.domain.events.path import priced_in_knots, rumor_knots, surprise_knots

SHAPES = {
    "surprise": lambda: surprise_knots(400_000, 24, 10, 60, 650_000),
    "surprise_no_hold": lambda: surprise_knots(500_000, 5, 0, 21, 300_000),
    "rumor_confirm": lambda: rumor_knots(400_000, 20, 8, 50, 550_000, 500_000, 35, True),
    "rumor_deny": lambda: rumor_knots(400_000, 20, 8, 50, 550_000, 500_000, 35, False),
    "priced_in": lambda: priced_in_knots(30, 60),
}


@pytest.mark.parametrize("name", SHAPES)
def test_step_differences_sum_to_final_value(name):
    knots = SHAPES[name]()
    first, last = knots[0][0], knots[-1][0]
    assert knots[0][1] == 0
    total = sum(eval_path(knots, t) - eval_path(knots, t - 1) for t in range(first - 3, last + 5))
    assert total == knots[-1][1] == eval_path(knots, last + 100)
    assert eval_path(knots, first) == 0 and eval_path(knots, first - 10) == 0


def test_knots_strictly_increasing():
    for make in SHAPES.values():
        taus = [t for t, _ in make()]
        assert taus == sorted(set(taus))


def test_deny_settles_to_zero_with_small_overshoot():
    knots = SHAPES["rumor_deny"]()
    assert knots[-1][1] == 0
    assert min(v for _, v in knots) < 0  # 轻微反向过冲


def test_priced_in_step_at_publish_is_opposite_to_sentiment():
    knots = SHAPES["priced_in"]()
    # 利好（正 sentiment）：满幅比例为正，发布时回落，τ=0 的步长为负
    assert eval_path(knots, 0) - eval_path(knots, -1) < 0
    assert eval_path(knots, -1) > eval_path(knots, 0) > 0
    assert knots[-1][1] == c.PRICED_IN_RETAIN_PPM


def test_surprise_reaches_full_then_retains():
    knots = SHAPES["surprise"]()
    assert max(v for _, v in knots) == 1_000_000
    assert knots[-1][1] == 650_000


def test_interpolation_rounds_half_up_and_clamps_ends():
    knots = ((-1, 0), (0, 300_000), (4, 1_000_000))
    assert eval_path(knots, 2) == 650_000
    assert eval_path(knots, 4) == eval_path(knots, 99) == 1_000_000
    assert eval_path(knots, -1) == 0


def test_generated_events_respect_step_cap_and_lifetime(event_ruleset, event_params):
    for day in range(0, 400):
        for ev in generate_day(2024, day, event_ruleset, event_params):
            assert abs(ev.magnitude_ppm) * max_step(ev.knots) <= c.IMPULSE_CAP_PPM * 1_000_000
            assert ev.knots[-1][0] <= c.MAX_EVENT_SPAN_TICKS
            for imp in ev.impacts:
                assert imp.delay_ticks + ev.knots[-1][0] <= c.MAX_EVENT_SPAN_TICKS or imp.hop == 0
