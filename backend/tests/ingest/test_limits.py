from __future__ import annotations

import pytest

from stocksim.replay_ingest import limits
from stocksim.replay_ingest.limits import (
    FLAG_CLOSE_DOWN,
    FLAG_CLOSE_UP,
    FLAG_EX_RIGHTS,
    FLAG_OPEN_DOWN,
    FLAG_OPEN_UP,
    FLAG_SUSPENDED,
    compute_flags,
    limit_pct_bp,
)


def test_gem_limit_changes_on_2020_08_24() -> None:
    assert limit_pct_bp("300001", "2020-08-21") == 1000
    assert limit_pct_bp("300001", "2020-08-23") == 1000
    assert limit_pct_bp("300001", "2020-08-24") == 2000
    assert limit_pct_bp("301001", "2023-01-03") == 2000


@pytest.mark.parametrize(
    ("code", "expected"),
    [("600001", 1000), ("000001", 1000), ("002001", 1000), ("688001", 2000), ("689009", 2000)],
)
def test_board_limits(code: str, expected: int) -> None:
    assert limit_pct_bp(code, "2023-07-04") == expected


def test_bse_limits_and_cutoff() -> None:
    assert limit_pct_bp("830001", "2022-01-04") == 3000
    assert limit_pct_bp("430001", "2022-01-04") == 3000
    assert limit_pct_bp("920001", "2025-01-02") == 3000
    with pytest.raises(ValueError, match="北交所"):
        limit_pct_bp("830001", "2021-11-14")


def test_st_main_board_is_5pct() -> None:
    assert limit_pct_bp("600001", "2023-07-04", is_st=True) == 500
    assert limit_pct_bp("688001", "2023-07-04", is_st=True) == 2000


def test_limit_prices_round_half_up() -> None:
    assert limits.limit_up_cents(2000, 1000) == 2200
    assert limits.limit_down_cents(2000, 1000) == 1800
    assert limits.limit_up_cents(1005, 1000) == 1106  # 1105.5 -> 1106
    assert limits.limit_down_cents(1005, 1000) == 905  # 904.5 -> 905
    assert limits.round_half_up_div(-5, 2) == -3  # half away from zero
    with pytest.raises(ValueError, match="positive"):
        limits.round_half_up_div(1, 0)


def test_flags_one_word_limit_up_and_tolerance() -> None:
    f = compute_flags(open_cents=2200, close_cents=2200, ref_prev_cents=2000, lim_bp=1000)
    assert f == FLAG_OPEN_UP | FLAG_CLOSE_UP
    # 容差 ±1 分
    assert compute_flags(open_cents=2199, close_cents=2201, ref_prev_cents=2000, lim_bp=1000) == f
    assert compute_flags(open_cents=2198, close_cents=2202, ref_prev_cents=2000, lim_bp=1000) == 0


def test_flags_close_limit_down_only_and_ex_rights() -> None:
    f = compute_flags(
        open_cents=1940, close_cents=1800, ref_prev_cents=2000, lim_bp=1000, ex_rights=True
    )
    assert f == FLAG_CLOSE_DOWN | FLAG_EX_RIGHTS
    f = compute_flags(open_cents=1800, close_cents=2000, ref_prev_cents=2000, lim_bp=1000)
    assert f == FLAG_OPEN_DOWN


def test_flags_suspended_and_first_day_without_reference() -> None:
    assert (
        compute_flags(open_cents=0, close_cents=0, ref_prev_cents=2000, lim_bp=1000, suspended=True)
        == FLAG_SUSPENDED
    )
    assert compute_flags(open_cents=2200, close_cents=2200, ref_prev_cents=None, lim_bp=1000) == 0
