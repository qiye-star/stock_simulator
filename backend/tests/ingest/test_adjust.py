from __future__ import annotations

import random
from fractions import Fraction

import pytest

from stocksim.replay_ingest.adjust import (
    adjusted_cents,
    detect_ex_days,
    factor,
    median,
    round_half_up,
    segment_factors,
    to_fraction,
    yuan_to_cents,
)


def _series(n: int, base: str = "3.9", *, noise_bp: int = 0, seed: int = 1) -> list[Fraction]:
    rng = random.Random(seed)
    b = Fraction(base)
    return [b * Fraction(10_000 + rng.randint(-noise_bp, noise_bp), 10_000) for _ in range(n)]


def test_to_fraction_and_cents() -> None:
    assert to_fraction("23.67") == Fraction(2367, 100)
    assert to_fraction(23.67) == Fraction(2367, 100)  # 浮点按最短 repr，不带二进制误差
    assert to_fraction(5) == 5
    assert yuan_to_cents("23.675") == 2368
    assert yuan_to_cents(0.1) == 10
    for bad in (None, True, "abc", ""):
        with pytest.raises(ValueError, match="not a number"):
            to_fraction(bad)


def test_round_half_up_is_away_from_zero() -> None:
    assert round_half_up(Fraction(5, 2)) == 3
    assert round_half_up(Fraction(-5, 2)) == -3
    assert round_half_up(Fraction(7, 3)) == 2


def test_factor_and_adjusted_cents() -> None:
    f = factor("93.36", "23.43")
    assert f == Fraction("93.36") / Fraction("23.43")
    assert adjusted_cents("23.43", f, f) == 2343  # 锚日：复权价 = 真实价
    assert adjusted_cents("11.715", f, f * 2) == 586  # 因子为锚的 2 倍时价格减半
    with pytest.raises(ValueError, match="positive"):
        factor("1", "0")


def test_median_even_and_odd() -> None:
    assert median([Fraction(3), Fraction(1), Fraction(2)]) == 2
    assert median([Fraction(1), Fraction(2), Fraction(3), Fraction(10)]) == Fraction(5, 2)


def test_constant_and_noisy_series_have_no_ex_days() -> None:
    assert detect_ex_days(_series(60, noise_bp=0)) == []
    for seed in range(20):  # 实测噪声量级：单日 ±50bp
        assert detect_ex_days(_series(120, noise_bp=50, seed=seed)) == []


def test_persistent_step_is_detected_once() -> None:
    f = _series(40, noise_bp=30, seed=3)
    f = f[:20] + [x * Fraction(1019, 1000) for x in f[20:]]  # +1.9%（如中信 2023-08-25）
    assert detect_ex_days(f) == [20]


def test_big_bonus_share_step() -> None:
    f = _series(30, "2.0", noise_bp=10)
    f = f[:12] + [x * Fraction(6, 5) for x in f[12:]]  # 10 送 2
    assert detect_ex_days(f) == [12]


def test_downward_step_is_never_an_ex_day() -> None:
    f = [Fraction(4)] * 20 + [Fraction(4) * Fraction(97, 100)] * 20  # 因子下跳不可能是分红送转
    assert detect_ex_days(f) == []


def test_transient_spike_is_not_an_ex_day() -> None:
    f = _series(40, noise_bp=10, seed=5)
    f[20] = f[20] * Fraction(103, 100)  # 单日 +3% 随即回落：数据噪声而非除权
    assert detect_ex_days(f) == []


def test_small_dividend_below_threshold_is_missed_by_design() -> None:
    f = [Fraction(39, 10)] * 20 + [Fraction(39, 10) * Fraction(1006, 1000)] * 20  # +0.6%
    assert detect_ex_days(f) == []


def test_two_nearby_candidates_merge_to_the_larger_step() -> None:
    def steps(first: str, second: str) -> list[Fraction]:
        return (
            [Fraction(4)] * 10
            + [Fraction(4) * Fraction(first)] * 2
            + [Fraction(4) * Fraction(second)] * 20
        )

    assert detect_ex_days(steps("1.02", "1.05")) == [12]  # 第二步更大（+2.9%）
    assert detect_ex_days(steps("1.03", "1.05")) == [10]  # 第一步更大（+3.0%）
    assert detect_ex_days([Fraction(4)] * 10 + [Fraction(5)] * 20 + [Fraction(6)] * 20) == [
        10,
        30,
    ]  # 相距远不合并


def test_step_at_second_row() -> None:
    f = [Fraction(4)] + [Fraction(5)] * 10
    assert detect_ex_days(f) == [1]


def test_segment_factors_use_segment_median() -> None:
    f = [Fraction(v) for v in (10, 11, 10, 20, 21, 20, 22)]
    seg = segment_factors(f, [3])
    assert seg[:3] == [Fraction(10)] * 3
    assert seg[3:] == [median([Fraction(v) for v in (20, 21, 20, 22)])] * 4
    assert segment_factors(f, []) == [median(f)] * len(f)
