"""复权口径（05 §2.7）：以第 0 日前一交易日（T0）为锚的复权价。

``adj_x(t) = raw_x(t) · f(t) / f(T0)``，``f(t) = hfq_close(t) / raw_close(t)``。
全程 ``Fraction`` 精确计算，只在最后取整到分。只用标准库。

**实测教训（2026-10-26，akshare 1.19.3）**：东财后复权价的逐日因子 ``f(t)`` 带噪声：同一股票
相邻两天的 ``f(t)/f(t-1)-1`` 中位数达 10–20bp，P99 约 50–140bp，个别日 300bp，同一天开盘与
收盘的隐含因子也不相等（与 2 位小数的舍入无关）。逐日使用 ``f(t)`` 会让复权后的日收益带噪声，
并误报除权日。
因此本模块把因子当作**分段常数**：只有检测到真正的除权跳变（``detect_ex_days``）时才换段，
每段取因子的中位数。小于阈值的分红（约 1% 以下）会漏检，复权价在该日留下不超过阈值的台阶，
由 ``build`` 的警告提示作者人工核对。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import pairwise
from typing import Any

from .limits import round_half_up_div


def to_fraction(value: Any) -> Fraction:
    """字符串/整数/浮点 -> Fraction。浮点先经 ``repr`` 取最短十进制表示，避免二进制误差。"""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    try:
        return Fraction(Decimal(repr(value) if isinstance(value, float) else str(value).strip()))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def round_half_up(value: Fraction) -> int:
    """Fraction 四舍五入取整（half away from zero）。"""
    return round_half_up_div(value.numerator, value.denominator)


def yuan_to_cents(value: Any) -> int:
    return round_half_up(to_fraction(value) * 100)


def factor(hfq_close: Any, raw_close: Any) -> Fraction:
    """``f(t) = hfq_close / raw_close``。"""
    raw = to_fraction(raw_close)
    if raw <= 0:
        raise ValueError(f"raw close must be positive: {raw_close!r}")
    return to_fraction(hfq_close) / raw


def adjusted_cents(raw_price: Any, f_t: Fraction, f_anchor: Fraction) -> int:
    """原始价（元）-> 以锚日为基准的复权价（分）。"""
    return round_half_up(to_fraction(raw_price) * 100 * f_t / f_anchor)


# ---------- 除权跳变检测与分段常数因子 ----------

EX_STEP_BP = 120  # 单日因子变化至少这么大才算候选
EX_LEVEL_BP = 100  # 且前后各 5 个交易日的因子中位数之差至少这么大
EX_NEIGHBORHOOD = 5
EX_MERGE_DAYS = 3  # 相邻候选在这么多天内只保留跳变最大的一个


def median(values: Sequence[Fraction]) -> Fraction:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def detect_ex_days(f: Sequence[Fraction]) -> list[int]:
    """在逐日因子序列里找除权跳变所在的下标（该日是除权后的第一个交易日）。只认上跳。"""
    step_limit = Fraction(EX_STEP_BP, 10_000)
    level_limit = Fraction(EX_LEVEL_BP, 10_000)
    picked: list[tuple[int, Fraction]] = []
    for i in range(1, len(f)):
        step = f[i] / f[i - 1] - 1
        if step < step_limit:  # 只看上跳：分红/送转/配股都让 hfq/raw 变大，下跳只能是噪声
            continue
        before = median(f[max(0, i - EX_NEIGHBORHOOD) : i])
        after = median(f[i : i + EX_NEIGHBORHOOD])
        if after / before - 1 < level_limit:
            continue
        if picked and i - picked[-1][0] <= EX_MERGE_DAYS:
            if step > picked[-1][1]:
                picked[-1] = (i, step)
        else:
            picked.append((i, step))
    return [i for i, _ in picked]


def segment_factors(f: Sequence[Fraction], ex_days: Sequence[int]) -> list[Fraction]:
    """每个下标对应其所在分段的因子中位数（分段以 ``ex_days`` 为起点）。"""
    bounds = [0, *ex_days, len(f)]
    out: list[Fraction] = []
    for lo, hi in pairwise(bounds):
        seg = median(f[lo:hi])
        out.extend([seg] * (hi - lo))
    return out
