"""金额工具：全部使用整数分（int cents）。费率用 Decimal。

舍入规则：四舍五入（half up，绝对值方向，即 half away from zero）。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

BP_DENOMINATOR = 10_000  # 基点（basis point）分母：1 bp = 0.01%
PPM_DENOMINATOR = 1_000_000  # 百万分之一，用于行情随机游走


def round_half_up_div(numerator: int, denominator: int) -> int:
    """整数除法并四舍五入（half away from zero）。denominator 必须 > 0。"""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * -numerator + denominator) // (2 * denominator))


def scale_bp(amount_cents: int, bp: int) -> int:
    """amount * bp / 10000，四舍五入到分。"""
    return round_half_up_div(amount_cents * bp, BP_DENOMINATOR)


def scale_ppm(amount_cents: int, ppm: int) -> int:
    """amount * ppm / 1000000，四舍五入到分。"""
    return round_half_up_div(amount_cents * ppm, PPM_DENOMINATOR)


def fee_cents(amount_cents: int, rate: Decimal) -> int:
    """手续费：金额 * 费率，单独四舍五入到分（half up）。

    rate 必须是 Decimal（例如 Decimal("0.0003")），禁止传入 float。
    """
    if not isinstance(rate, Decimal):
        raise TypeError("fee rate must be Decimal")
    if rate < 0:
        raise ValueError("fee rate must be non-negative")
    exact = Decimal(amount_cents) * rate
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def yuan_to_cents(value: str | int | Decimal) -> int:
    """元 -> 分。字符串/Decimal 精确解析，超出两位小数按 half up 舍入。"""
    if isinstance(value, bool | float):
        raise TypeError("money must not be float or bool")
    dec = Decimal(value) if not isinstance(value, Decimal) else value
    return int((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_yuan_str(cents: int) -> str:
    """分 -> 元字符串，固定两位小数，例如 1234 -> '12.34'。"""
    sign = "-" if cents < 0 else ""
    a = abs(cents)
    return f"{sign}{a // 100}.{a % 100:02d}"


def is_palindrome(value: int) -> bool:
    text = str(abs(value))
    return text == text[::-1]
