"""金额：整数分、四舍五入、手续费单独舍入。"""

from decimal import Decimal

import pytest

from stocksim.domain.money import (
    cents_to_yuan_str,
    fee_cents,
    is_palindrome,
    round_half_up_div,
    scale_bp,
    scale_ppm,
    yuan_to_cents,
)


@pytest.mark.parametrize(
    "n,d,expected",
    [(5, 2, 3), (4, 2, 2), (-5, 2, -3), (-4, 2, -2), (0, 7, 0), (1, 3, 0), (2, 3, 1)],
)
def test_round_half_up_div(n, d, expected):
    assert round_half_up_div(n, d) == expected


def test_round_half_up_div_rejects_zero():
    with pytest.raises(ValueError):
        round_half_up_div(1, 0)


def test_fee_rounds_once_half_up():
    # 1666 * 0.0003 = 0.4998 -> 0；1667 * 0.0003 = 0.5001 -> 1
    assert fee_cents(1666, Decimal("0.0003")) == 0
    assert fee_cents(1667, Decimal("0.0003")) == 1
    # 精确 0.5 -> 1（half up）
    assert fee_cents(10, Decimal("0.05")) == 1
    # 100000 * 0.0013 = 130
    assert fee_cents(100_000, Decimal("0.0013")) == 130


def test_fee_requires_decimal_and_non_negative():
    with pytest.raises(TypeError):
        fee_cents(100, 0.0003)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        fee_cents(100, Decimal("-0.1"))


def test_scale_helpers():
    assert scale_bp(1000, 1000) == 100  # 10%
    assert scale_bp(1005, 1000) == 101  # 100.5 -> 101
    assert scale_ppm(1000, 1_020_000) == 1020


def test_yuan_parsing_is_exact():
    assert yuan_to_cents("1.005") == 101  # 不是 100（无浮点误差）
    assert yuan_to_cents("12") == 1200
    assert yuan_to_cents(Decimal("0.07")) == 7
    with pytest.raises(TypeError):
        yuan_to_cents(1.005)  # type: ignore[arg-type]


def test_cents_to_yuan_str():
    assert cents_to_yuan_str(1234) == "12.34"
    assert cents_to_yuan_str(-1205) == "-12.05"
    assert cents_to_yuan_str(7) == "0.07"


def test_palindrome():
    assert is_palindrome(1221)
    assert is_palindrome(7)
    assert not is_palindrome(1220)
