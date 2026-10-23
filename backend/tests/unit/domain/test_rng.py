"""RNG：金定值（golden）+ 范围 + 确定性。金定值由 CONTRACT 规范一次性计算后硬编码。"""

import pytest

from stocksim.domain.rng import _raw, rand01, rand_below

# (seed, tick, stock_idx, k) -> 原始 64 位输出（规范实现的金定值）
GOLDEN_RAW = [
    ((0, 0, 0, 0), 0),
    ((42, 0, 0, 0), 12058926934050108962),
    ((42, 1, 2, 3), 15752930560071793341),
    ((-1, -1, 5, 7), 11298378685832977841),
    ((2**63 + 5, 20, 384, 99), 15201497200680917396),
    ((123456789, 1000, 10, 0), 2530783009422393237),
]

GOLDEN_RAND01 = [
    ((42, 0, 0, 0), 0.6537157389870545),
    ((42, 1, 2, 3), 0.8539680768121566),
    ((-1, -1, 5, 7), 0.6124863358372016),
    ((2**63 + 5, 20, 384, 99), 0.8240748145005282),
    ((123456789, 1000, 10, 0), 0.13719402184525797),
]

GOLDEN_BELOW_100 = [
    ((42, 0, 0, 0), 65),
    ((42, 1, 2, 3), 85),
    ((-1, -1, 5, 7), 61),
    ((2**63 + 5, 20, 384, 99), 82),
    ((123456789, 1000, 10, 0), 13),
]


@pytest.mark.parametrize("args,expected", GOLDEN_RAW)
def test_raw_matches_golden(args, expected):
    assert _raw(*args) == expected


@pytest.mark.parametrize("args,expected", GOLDEN_RAND01)
def test_rand01_matches_golden(args, expected):
    assert rand01(*args) == expected


@pytest.mark.parametrize("args,expected", GOLDEN_BELOW_100)
def test_rand_below_matches_golden(args, expected):
    assert rand_below(*args, 100) == expected


def test_rand01_range_and_determinism():
    for k in range(500):
        v = rand01(7, 3, 11, k)
        assert 0.0 <= v < 1.0
        assert v == rand01(7, 3, 11, k)


def test_rand_below_range():
    values = {rand_below(9, t, 1, 0, 6) for t in range(2000)}
    assert values == set(range(6))


def test_distinct_dimensions_give_distinct_streams():
    base = rand01(1, 5, 2, 0)
    assert rand01(2, 5, 2, 0) != base
    assert rand01(1, 6, 2, 0) != base
    assert rand01(1, 5, 3, 0) != base
    assert rand01(1, 5, 2, 1) != base


def test_rand_below_rejects_non_positive():
    with pytest.raises(ValueError):
        rand_below(1, 1, 1, 1, 0)
