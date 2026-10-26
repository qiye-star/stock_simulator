"""真实复盘（模式 E，05 §5.4）的纯函数：阶段与位置、事件可见性、价格缩放与显示口径、标志位、收益率。

零 I/O、无墙上时钟。依赖 money.round_half_up_div 与 rules 的涨跌停函数。
约定：价格为整数分；`bar` 为关卡包的一行 `[o, h, l, c, vol_shares, lim_bp, flags]`，
价格是以 T0 为锚的复权价；`scale_ppm` 为匿名模式的价格缩放（实名为 1_000_000）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .money import BP_DENOMINATOR, round_half_up_div
from .rules import clamp_to_limits

PHASES: tuple[str, ...] = ("pre_open", "open", "close", "post_close")
PHASES_PER_DAY = len(PHASES)
PHASE_MINUTE: dict[str, int] = {"pre_open": 540, "open": 570, "close": 900, "post_close": 960}
MINUTE_PHASE: dict[int, str] = {minute: phase for phase, minute in PHASE_MINUTE.items()}
# 事件 slot -> 最早可见的阶段序号（0 pre_open / 1 open / 2 close / 3 post_close）
SLOT_VISIBLE_FROM: dict[str, int] = {"pre_open": 0, "intraday": 2, "post_close": 3}
SLOTS: tuple[str, ...] = tuple(SLOT_VISIBLE_FROM)
SCALE_ONE = 1_000_000  # 实名模式的缩放（ppm）

FLAG_SUSPENDED = 1  # 停牌（当日无行，构建器补齐）
FLAG_OPEN_UP = 2  # 开盘封涨停
FLAG_OPEN_DOWN = 4  # 开盘封跌停
FLAG_CLOSE_UP = 8  # 收盘封涨停
FLAG_CLOSE_DOWN = 16  # 收盘封跌停
FLAG_EX_RIGHTS = 32  # 除权除息日


def phase_of_minute(minute: int) -> str:
    """游戏时钟分钟 -> 阶段名。复盘只使用 540/570/900/960 四个分钟。"""
    try:
        return MINUTE_PHASE[minute]
    except KeyError:
        raise ValueError(f"not a replay clock minute: {minute}") from None


def phase_index(phase: str) -> int:
    return PHASES.index(phase)


def phase_tick(day_idx: int, phase: str) -> int:
    """(日, 阶段) -> 单调递增的 tick：day * 4 + 阶段序号。回看期的日为负数。"""
    return day_idx * PHASES_PER_DAY + phase_index(phase)


def next_position(day_idx: int, phase: str, play_days: int) -> tuple[int, str] | None:
    """游戏期内的下一个位置；最后一日的 post_close 之后返回 None（应结算）。"""
    idx = phase_index(phase)
    if idx + 1 < PHASES_PER_DAY:
        return day_idx, PHASES[idx + 1]
    if day_idx + 1 < play_days:
        return day_idx + 1, PHASES[0]
    return None


def event_visible(ev_day: int, ev_slot: str, day_idx: int, phase: str) -> bool:
    """事件在位置 (day_idx, phase) 是否已可见（05 §1.3、§2.6）。"""
    first = ev_day * PHASES_PER_DAY + SLOT_VISIBLE_FROM[ev_slot]
    return first <= phase_tick(day_idx, phase)


def first_visible_phase(ev_slot: str) -> str:
    """事件 slot 首次可见的阶段名（intraday -> close，其余同名）。"""
    return PHASES[SLOT_VISIBLE_FROM[ev_slot]]


def scale_price(adj_cents: int, scale_ppm: int) -> int:
    """复权价按匿名缩放系数取整到分。"""
    return round_half_up_div(adj_cents * scale_ppm, SCALE_ONE)


@dataclass(frozen=True)
class DisplayBar:
    """显示口径的一日 K：价格已缩放并夹紧到涨跌停内，量已反比缩放。"""

    prev_close: int
    open: int
    high: int
    low: int
    close: int
    volume: int
    lim_bp: int
    flags: int


def display_bar(bar: Sequence[int], prev_close_adj: int, scale_ppm: int) -> DisplayBar:
    """复权 bar -> 显示 bar（05 §5.3「报价构造」）。

    先缩放，再以显示前收为基准按当日涨跌幅夹紧，保证缩放与取整之后限价校验与显示一致。
    """
    o, h, lo, c, vol, lim, flags = (int(x) for x in bar)
    prev = scale_price(prev_close_adj, scale_ppm)

    def fit(adj: int) -> int:
        return clamp_to_limits(scale_price(adj, scale_ppm), prev, lim)

    return DisplayBar(
        prev_close=prev,
        open=fit(o),
        high=fit(h),
        low=fit(lo),
        close=fit(c),
        volume=round_half_up_div(vol * SCALE_ONE, scale_ppm),
        lim_bp=lim,
        flags=flags,
    )


@dataclass(frozen=True)
class VisibleQuote:
    """某阶段玩家可见的报价（§1.3 表格）。"""

    price: int
    prev_close: int
    open: int
    high: int
    low: int
    volume: int


def visible_quote(
    bar: Sequence[int], prev_close_adj: int, scale_ppm: int, phase: str
) -> VisibleQuote:
    """按阶段给出可见价格：

    - pre_open：现价 = 前收，量 0；
    - open：现价 = 开盘价，最高 = 最低 = 开盘，量 0；
    - close / post_close：完整的当日 K（收盘价、最高、最低、量）。
    """
    d = display_bar(bar, prev_close_adj, scale_ppm)
    if phase == "pre_open":
        p = d.prev_close
        return VisibleQuote(price=p, prev_close=p, open=p, high=p, low=p, volume=0)
    if phase == "open":
        return VisibleQuote(
            price=d.open,
            prev_close=d.prev_close,
            open=d.open,
            high=d.open,
            low=d.open,
            volume=0,
        )
    if phase in ("close", "post_close"):
        return VisibleQuote(
            price=d.close,
            prev_close=d.prev_close,
            open=d.open,
            high=d.high,
            low=d.low,
            volume=d.volume,
        )
    raise ValueError(f"unknown phase: {phase}")


def phase_flags(flags: int, phase: str) -> dict[str, bool]:
    """当前阶段生效的交易标志：suspended（任何阶段）、locked_up / locked_down（开盘或收盘封板）。"""
    if phase == "open":
        up = bool(flags & FLAG_OPEN_UP)
        down = bool(flags & FLAG_OPEN_DOWN)
    elif phase in ("close", "post_close"):
        up = bool(flags & FLAG_CLOSE_UP)
        down = bool(flags & FLAG_CLOSE_DOWN)
    else:
        up = down = False
    return {
        "suspended": bool(flags & FLAG_SUSPENDED),
        "locked_up": up,
        "locked_down": down,
    }


def return_bp(base: int, end: int) -> int:
    """收益率（基点，四舍五入）：(end - base) / base。base 必须为正。"""
    if base <= 0:
        raise ValueError("base must be positive")
    return round_half_up_div((end - base) * BP_DENOMINATOR, base)


__all__ = [
    "FLAG_CLOSE_DOWN",
    "FLAG_CLOSE_UP",
    "FLAG_EX_RIGHTS",
    "FLAG_OPEN_DOWN",
    "FLAG_OPEN_UP",
    "FLAG_SUSPENDED",
    "MINUTE_PHASE",
    "PHASES",
    "PHASES_PER_DAY",
    "PHASE_MINUTE",
    "SCALE_ONE",
    "SLOTS",
    "SLOT_VISIBLE_FROM",
    "DisplayBar",
    "VisibleQuote",
    "display_bar",
    "event_visible",
    "first_visible_phase",
    "next_position",
    "phase_flags",
    "phase_index",
    "phase_of_minute",
    "phase_tick",
    "return_bp",
    "scale_price",
    "visible_quote",
]
