"""真实复盘的纯函数（05 §5.4、§8.2）：阶段位置、事件可见性、缩放夹紧、阶段报价与标志位、收益率。"""

import pytest

from stocksim.domain.replay import (
    FLAG_CLOSE_DOWN,
    FLAG_CLOSE_UP,
    FLAG_OPEN_DOWN,
    FLAG_OPEN_UP,
    FLAG_SUSPENDED,
    PHASE_MINUTE,
    SCALE_ONE,
    display_bar,
    event_visible,
    first_visible_phase,
    next_position,
    phase_flags,
    phase_of_minute,
    phase_tick,
    return_bp,
    scale_price,
    visible_quote,
)
from stocksim.domain.rules import limit_down_cents, limit_up_cents

PHASES = ("pre_open", "open", "close", "post_close")
PREV = 10_000  # 复权前收 100.00 元
BAR = [10_200, 10_900, 10_100, 10_800, 5_000_000, 1000, 0]  # 开 +2%，高 +9%，低 +1%，收 +8%


def test_phase_minutes_and_tick():
    assert PHASE_MINUTE == {"pre_open": 540, "open": 570, "close": 900, "post_close": 960}
    assert [phase_of_minute(m) for m in (540, 570, 900, 960)] == list(PHASES)
    with pytest.raises(ValueError):
        phase_of_minute(600)
    assert phase_tick(0, "pre_open") == 0
    assert phase_tick(0, "post_close") == 3
    assert phase_tick(-2, "close") == -6  # 回看期为负


def test_next_position_walks_all_days_then_none():
    play = 2
    seq = []
    pos = (0, "pre_open")
    while pos is not None:
        seq.append(pos)
        pos = next_position(pos[0], pos[1], play)
    assert seq == [
        (0, "pre_open"),
        (0, "open"),
        (0, "close"),
        (0, "post_close"),
        (1, "pre_open"),
        (1, "open"),
        (1, "close"),
        (1, "post_close"),
    ]


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ("pre_open", {"pre_open": True, "open": True, "close": True, "post_close": True}),
        ("intraday", {"pre_open": False, "open": False, "close": True, "post_close": True}),
        ("post_close", {"pre_open": False, "open": False, "close": False, "post_close": True}),
    ],
)
def test_event_visibility_truth_table(slot, expected):
    """3 种 slot × 4 个阶段的真值表（事件在当日 d 发生）。"""
    for phase in PHASES:
        assert event_visible(3, slot, 3, phase) is expected[phase], (slot, phase)


def test_event_visibility_crosses_days():
    # 前一日盘后的事件，次日盘前即可见；次日盘中的事件次日收盘前不可见
    assert event_visible(2, "post_close", 3, "pre_open")
    assert not event_visible(3, "intraday", 3, "open")
    assert event_visible(3, "intraday", 3, "close")
    assert not event_visible(4, "pre_open", 3, "post_close")


def test_first_visible_phase():
    assert first_visible_phase("pre_open") == "pre_open"
    assert first_visible_phase("intraday") == "close"
    assert first_visible_phase("post_close") == "post_close"


def test_scale_price_identity_and_rounding():
    assert scale_price(12_345, SCALE_ONE) == 12_345
    assert scale_price(10_000, 500_000) == 5_000
    assert scale_price(3, 500_000) == 2  # 1.5 分 -> 2（半远离零）


def test_display_bar_identity_for_real_mode():
    d = display_bar(BAR, PREV, SCALE_ONE)
    assert (d.prev_close, d.open, d.high, d.low, d.close, d.volume) == (
        PREV,
        10_200,
        10_900,
        10_100,
        10_800,
        5_000_000,
    )


def test_display_bar_scales_and_clamps_within_limits():
    # 缩放 2 倍的价格：前收 20000，涨跌停 ±10%；原始的 +9% 高价缩放后仍落在区间内
    d = display_bar(BAR, PREV, 2 * SCALE_ONE)
    assert d.prev_close == 20_000
    lo, hi = limit_down_cents(20_000, 1000), limit_up_cents(20_000, 1000)
    for price in (d.open, d.high, d.low, d.close):
        assert lo <= price <= hi
    # 量按反比缩放
    assert d.volume == 2_500_000


def test_display_bar_clamps_twenty_percent_board():
    # 创业板 +15% 收盘：lim=2000 时不被夹紧，lim=1000 时被夹紧到 +10%
    bar_up = [11_000, 11_500, 11_000, 11_500, 1000, 2000, 0]
    assert display_bar(bar_up, PREV, SCALE_ONE).close == 11_500
    bar_capped = [11_000, 11_500, 11_000, 11_500, 1000, 1000, 0]
    assert display_bar(bar_capped, PREV, SCALE_ONE).close == 11_000


def test_visible_quote_per_phase():
    pre = visible_quote(BAR, PREV, SCALE_ONE, "pre_open")
    assert (pre.price, pre.open, pre.high, pre.low, pre.volume) == (PREV, PREV, PREV, PREV, 0)

    opn = visible_quote(BAR, PREV, SCALE_ONE, "open")
    assert (opn.price, opn.open, opn.high, opn.low, opn.volume) == (
        10_200,
        10_200,
        10_200,
        10_200,
        0,
    )

    close = visible_quote(BAR, PREV, SCALE_ONE, "close")
    assert (close.price, close.open, close.high, close.low) == (10_800, 10_200, 10_900, 10_100)
    assert close.volume == 5_000_000

    post = visible_quote(BAR, PREV, SCALE_ONE, "post_close")
    assert post == close


def test_visible_quote_rejects_unknown_phase():
    with pytest.raises(ValueError):
        visible_quote(BAR, PREV, SCALE_ONE, "lunch")


def test_phase_flags_by_stage():
    assert phase_flags(FLAG_SUSPENDED, "pre_open")["suspended"] is True
    assert phase_flags(FLAG_OPEN_UP, "open")["locked_up"] is True
    assert phase_flags(FLAG_OPEN_UP, "close")["locked_up"] is False
    assert phase_flags(FLAG_OPEN_DOWN, "open")["locked_down"] is True
    assert phase_flags(FLAG_CLOSE_UP, "close")["locked_up"] is True
    assert phase_flags(FLAG_CLOSE_DOWN, "close")["locked_down"] is True
    assert phase_flags(FLAG_CLOSE_DOWN, "open")["locked_down"] is False
    assert phase_flags(FLAG_CLOSE_UP, "pre_open") == {
        "suspended": False,
        "locked_up": False,
        "locked_down": False,
    }


def test_return_bp_rounds_half_away_from_zero():
    assert return_bp(10_000, 10_500) == 500
    assert return_bp(10_000, 9_000) == -1000
    assert return_bp(3, 4) == 3333  # 33.333… % -> 3333 bp
    with pytest.raises(ValueError):
        return_bp(0, 1)
