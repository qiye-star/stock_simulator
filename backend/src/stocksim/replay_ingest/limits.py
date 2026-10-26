"""涨跌幅规则（按板块与日期分段）与每日标志位。规则集中于此，带日期分段（05 §2.8）。

只用标准库；``round_half_up_div`` 与 ``domain/money.py`` 同口径（half away from zero），
这里自己实现一份，保持本包零依赖运行时代码。
"""

from __future__ import annotations

FLAG_SUSPENDED = 1
FLAG_OPEN_UP = 2
FLAG_OPEN_DOWN = 4
FLAG_CLOSE_UP = 8
FLAG_CLOSE_DOWN = 16
FLAG_EX_RIGHTS = 32

GEM_20PCT_FROM = "2020-08-24"  # 创业板注册制涨跌幅 10% -> 20%
BSE_FROM = "2021-11-15"  # 北交所开市；更早日期没有规则
ST_MAIN_BP = 500

TOLERANCE_CENTS = 1  # 用原始价判定封板的容差（±1 分）


def round_half_up_div(numerator: int, denominator: int) -> int:
    """整数除法并四舍五入（half away from zero）。denominator 必须 > 0。"""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * -numerator + denominator) // (2 * denominator))


def board_of(code: str) -> str:
    """``star``(688/689) | ``gem``(300/301) | ``bse``(4/8/920) | ``main``。"""
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301")):
        return "gem"
    if code.startswith("920") or code[:1] in ("4", "8"):
        return "bse"
    return "main"


def limit_pct_bp(code: str, trade_date: str, is_st: bool = False) -> int:
    """当日涨跌幅（基点）。``trade_date`` 为 ISO 日期字符串（可直接比较大小）。

    ST 主板为 500；本规则未核对最新风险警示规则，MVP 不收 ST 股（05 Q8），规格校验会拒绝 ``is_st``。
    """
    board = board_of(code)
    if board == "star":
        return 2000
    if board == "gem":
        if trade_date >= GEM_20PCT_FROM:
            return 2000
        return ST_MAIN_BP if is_st else 1000
    if board == "bse":
        if trade_date < BSE_FROM:
            raise ValueError(f"北交所规则仅支持 {BSE_FROM} 以后: {code} {trade_date}")
        return 3000
    return ST_MAIN_BP if is_st else 1000


def limit_up_cents(ref_prev_cents: int, lim_bp: int) -> int:
    return round_half_up_div(ref_prev_cents * (10_000 + lim_bp), 10_000)


def limit_down_cents(ref_prev_cents: int, lim_bp: int) -> int:
    return round_half_up_div(ref_prev_cents * (10_000 - lim_bp), 10_000)


def compute_flags(
    *,
    open_cents: int,
    close_cents: int,
    ref_prev_cents: int | None,
    lim_bp: int,
    suspended: bool = False,
    ex_rights: bool = False,
    tolerance_cents: int = TOLERANCE_CENTS,
) -> int:
    """用**原始价**（分）判定标志位。``ref_prev_cents`` 为除权参考价；缺失则不判封板。

    ``tolerance_cents`` 默认 ±1 分；除权日的参考价由因子估计、不精确，调用方会放宽。
    """
    flags = 0
    if suspended:
        flags |= FLAG_SUSPENDED
    if ex_rights:
        flags |= FLAG_EX_RIGHTS
    if suspended or ref_prev_cents is None:
        return flags
    up = limit_up_cents(ref_prev_cents, lim_bp)
    down = limit_down_cents(ref_prev_cents, lim_bp)
    if abs(open_cents - up) <= tolerance_cents:
        flags |= FLAG_OPEN_UP
    if abs(open_cents - down) <= tolerance_cents:
        flags |= FLAG_OPEN_DOWN
    if abs(close_cents - up) <= tolerance_cents:
        flags |= FLAG_CLOSE_UP
    if abs(close_cents - down) <= tolerance_cents:
        flags |= FLAG_CLOSE_DOWN
    return flags
