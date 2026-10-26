"""LMSR 做市纯函数（04 §4）。零 I/O，只用 decimal。

数值环境 `LMSR_CTX`（prec=50，半偶舍入）：`Decimal.exp()`/`ln()` 在 libmpdec 中正确舍入，
结果与平台、libm、Python 小版本无关，所以同一成交序列得到同一整数结果（跨部署可复现）。
每个公开函数都在 `localcontext(LMSR_CTX)` 内运行，不依赖线程默认上下文。

记号（b 为份额单位，b = b_milli / 1000；q_i 含虚拟先验 q0_i）：
  Cs(q) = b·ln Σ exp(q_i / b)      份额单位的成本；积分成本 C(q) = 100·Cs(q)
  p_i   = exp(q_i/b) / Σ exp(q_j/b)
  买 Δ 份 i 花费 x = C(q+Δe_i) − C(q)，买入向上取整；
  卖 Δ 份 i 回款 y = C(q) − C(q−Δe_i)，卖出向下取整。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from ..errors import VALIDATION_ERROR, DomainError
from ..money import round_half_up_div
from .constants import (
    B_SHRINK_DIVISOR,
    B_SHRINK_MAX_ITERS,
    COST_SNAP_EXP,
    POINTS_PER_SHARE,
    PRICE_PPM_TOTAL,
    SUBSIDY_TIERS,
)
from .types import Quote, Side

LMSR_CTX = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emax=999_999,
    Emin=-999_999,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
_SNAP = Decimal(1).scaleb(COST_SNAP_EXP)  # 1e-12 积分
_PPM = Decimal(PRICE_PPM_TOTAL)


# ---------------------------------------------------------------- 内部工具


def _check_q(q: Sequence[int]) -> None:
    if len(q) < 2:
        raise ValueError("LMSR needs at least 2 outcomes")
    for v in q:
        if not isinstance(v, int) or isinstance(v, bool):
            raise TypeError("q must be ints")


def _beta(b_milli: int) -> Decimal:
    if not isinstance(b_milli, int) or isinstance(b_milli, bool) or b_milli <= 0:
        raise ValueError("b_milli must be a positive int")
    return Decimal(b_milli) / Decimal(1000)


def _cs(q: Sequence[int], b: Decimal) -> Decimal:
    """Cs(q) = m + b·ln Σ exp((q_i − m)/b)，m = max q，指数 ≤ 0 不溢出。须在 LMSR_CTX 内调用。"""
    m = max(q)
    total = Decimal(0)
    for qi in q:
        total += (Decimal(qi - m) / b).exp()
    return Decimal(m) + b * total.ln()


def _exps(q: Sequence[int], b: Decimal) -> list[Decimal]:
    m = max(q)
    return [(Decimal(qi - m) / b).exp() for qi in q]


def _delta_points(q: Sequence[int], b: Decimal, i: int, delta: int) -> Decimal:
    """C(q + delta·e_i) − C(q)，积分，未取整。delta 可为负。须在 LMSR_CTX 内调用。"""
    q2 = list(q)
    q2[i] += delta
    return POINTS_PER_SHARE * (_cs(q2, b) - _cs(q, b))


def _check_trade_args(q: Sequence[int], i: int, shares: int) -> None:
    _check_q(q)
    if not 0 <= i < len(q):
        raise ValueError("outcome index out of range")
    if not isinstance(shares, int) or isinstance(shares, bool) or shares < 1:
        raise ValueError("shares must be a positive int")


def _buy_points(q: Sequence[int], b: Decimal, i: int, shares: int) -> int:
    """买入花费：向上取整（先量化到 1e-12 消除尾差），至少 1 积分。"""
    x = _delta_points(q, b, i, shares).quantize(_SNAP, rounding=ROUND_HALF_EVEN)
    return max(1, int(x.to_integral_value(rounding=ROUND_CEILING)))


def _sell_points(q: Sequence[int], b: Decimal, i: int, shares: int) -> int:
    """卖出回款：向下取整（先量化到 1e-12 消除尾差），可为 0。"""
    y = (-_delta_points(q, b, i, -shares)).quantize(_SNAP, rounding=ROUND_HALF_EVEN)
    return int(y.to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------- 公共函数（04 §4.1）


def cost_points(q: Sequence[int], b_milli: int) -> Decimal:
    """100·Cs(q)，积分，未取整（用于测试与诊断；账本只用 buy_cost/sell_proceeds）。"""
    _check_q(q)
    with localcontext(LMSR_CTX):
        return POINTS_PER_SHARE * _cs(q, _beta(b_milli))


def prices_ppm(q: Sequence[int], b_milli: int) -> tuple[int, ...]:
    """各选项的隐含概率（ppm），和恰为 1_000_000。

    最大余数法：先下取整，剩余 ppm 按小数部分从大到小分配；小数部分相等时取较小下标。
    """
    _check_q(q)
    with localcontext(LMSR_CTX):
        b = _beta(b_milli)
        e = _exps(q, b)
        total = sum(e, Decimal(0))
        raw = [x * _PPM / total for x in e]
        floors = [int(r.to_integral_value(rounding=ROUND_FLOOR)) for r in raw]
        remain = PRICE_PPM_TOTAL - sum(floors)
        out = list(floors)
        order = sorted(range(len(q)), key=lambda k: (-(raw[k] - floors[k]), k))
        for k in order[:remain]:
            out[k] += 1
        return tuple(out)


def buy_cost(q: Sequence[int], b_milli: int, i: int, shares: int) -> int:
    """买入 shares 份选项 i 的花费（积分，向上取整，≥1）。"""
    _check_trade_args(q, i, shares)
    with localcontext(LMSR_CTX):
        return _buy_points(q, _beta(b_milli), i, shares)


def sell_proceeds(q: Sequence[int], b_milli: int, i: int, shares: int) -> int:
    """卖出 shares 份选项 i 的回款（积分，向下取整，可为 0；服务层拒绝 0）。"""
    _check_trade_args(q, i, shares)
    with localcontext(LMSR_CTX):
        return _sell_points(q, _beta(b_milli), i, shares)


def max_shares_for_budget(
    q: Sequence[int], b_milli: int, i: int, budget_points: int, cap: int
) -> int:
    """满足 buy_cost(q, i, n) ≤ budget_points 的最大整数 n，且 n ≤ cap（n ≥ 0）。

    先用闭式 Δ* = b·ln(1 + (E−1)/p_i)，E = exp(B/(100b)) 取初值，再用整数花费校正。
    校正以 buy_cost 为准，所以结果精确：buy_cost(n) ≤ B < buy_cost(n+1) 或 n == cap。
    """
    _check_q(q)
    if not 0 <= i < len(q):
        raise ValueError("outcome index out of range")
    if budget_points < 0 or cap < 0:
        raise ValueError("budget and cap must be non-negative")
    if budget_points == 0 or cap == 0:
        return 0
    with localcontext(LMSR_CTX):
        b = _beta(b_milli)
        e = _exps(q, b)
        p_i = e[i] / sum(e, Decimal(0))
        big_e = (Decimal(budget_points) / (POINTS_PER_SHARE * b)).exp()
        guess = b * ((big_e - 1) / p_i + 1).ln()
        n = min(cap, max(0, int(guess.to_integral_value(rounding=ROUND_FLOOR))))
        while n > 0 and _buy_points(q, b, i, n) > budget_points:
            n -= 1
        while n < cap and _buy_points(q, b, i, n + 1) <= budget_points:
            n += 1
        return n


def quote(q: Sequence[int], b_milli: int, side: Side, i: int, shares: int) -> Quote:
    """报价：花费/回款、均价与前后隐含概率。不修改入参。"""
    _check_trade_args(q, i, shares)
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    with localcontext(LMSR_CTX):
        b = _beta(b_milli)
        if side == "buy":
            points = _buy_points(q, b, i, shares)
            delta = shares
        else:
            points = _sell_points(q, b, i, shares)
            delta = -shares
    before = prices_ppm(q, b_milli)[i]
    q_after = list(q)
    q_after[i] += delta
    after = prices_ppm(q_after, b_milli)
    avg = round_half_up_div(points * 10_000, shares)  # 100 积分 = 1 份 = 1e6 ppm
    return Quote(
        side=side,
        outcome=i,
        shares=shares,
        points=points,
        avg_price_ppm=avg,
        price_before_ppm=before,
        prices_after_ppm=after,
    )


def max_loss_points(b_milli: int, q0: Sequence[int]) -> Decimal:
    """做市商最大亏损（补贴需求）：100·(Cs(q0) − min q0)，积分。"""
    _check_q(q0)
    with localcontext(LMSR_CTX):
        return POINTS_PER_SHARE * (_cs(q0, _beta(b_milli)) - Decimal(min(q0)))


def subsidy_for(expected_participants: int) -> int:
    """按预期参与人数取补贴 S（04 §4.4 的三档）。"""
    if expected_participants < 0:
        raise ValueError("expected_participants must be non-negative")
    s = SUBSIDY_TIERS[0][1]
    for lower, tier_s in SUBSIDY_TIERS:
        if expected_participants >= lower:
            s = tier_s
    return s


def _check_prior(prior_ppm: Sequence[int]) -> None:
    if len(prior_ppm) < 2:
        raise DomainError(VALIDATION_ERROR, {"field": "prior_ppm", "reason": "length"})
    if any(not isinstance(p, int) or p <= 0 for p in prior_ppm):
        raise DomainError(VALIDATION_ERROR, {"field": "prior_ppm", "reason": "positive_int"})
    if sum(prior_ppm) != PRICE_PPM_TOTAL:
        raise DomainError(VALIDATION_ERROR, {"field": "prior_ppm", "reason": "sum"})


def b_for_subsidy(subsidy_points: int, prior_ppm: Sequence[int]) -> tuple[int, tuple[int, ...]]:
    """由补贴上限与开盘先验反推 (b_milli, q0)（04 §4.4）。

    b_milli = floor(S·1000 / (100·ln(1e6/p_min)))；
    q0_i = round_half_even(b·ln(p_i/p_min))，min(q0)=0。
    若 max_loss_points > S，则 b -= max(1, b//200) 重算，最多 B_SHRINK_MAX_ITERS 次。
    """
    _check_prior(prior_ppm)
    if subsidy_points <= 0:
        raise ValueError("subsidy_points must be positive")
    p_min = min(prior_ppm)
    with localcontext(LMSR_CTX):
        log_inv = (_PPM / Decimal(p_min)).ln()  # ln(1/p_min)
        b_milli = int(
            (Decimal(subsidy_points * 1000) / (POINTS_PER_SHARE * log_inv)).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
    for _ in range(B_SHRINK_MAX_ITERS + 1):
        if b_milli < 1:
            break
        with localcontext(LMSR_CTX):
            b = _beta(b_milli)
            q0 = tuple(
                int(
                    (b * (Decimal(p) / Decimal(p_min)).ln()).to_integral_value(
                        rounding=ROUND_HALF_EVEN
                    )
                )
                for p in prior_ppm
            )
        if max_loss_points(b_milli, q0) <= subsidy_points:
            return b_milli, q0
        b_milli -= max(1, b_milli // B_SHRINK_DIVISOR)
    raise ValueError("cannot fit b under the subsidy cap")
