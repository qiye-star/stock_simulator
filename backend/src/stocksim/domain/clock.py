"""游戏时钟与交易时段。时间单位：当日分钟数 minute_of_day ∈ [0, 1440)。

legacy 对应：game.js 1778-1795（推进）、1855-1862（交易时段）、1855-1925（跳过）、
1819-1829（时段窗口文案）。
"""

from __future__ import annotations

from typing import Literal

from .rng import rand_below

MINUTES_PER_DAY = 1440
TICKS_PER_TRADING_DAY = 20  # 每 20 个交易 tick 为一个交易日（legacy game.js 2019）
DEFAULT_MINUTES_PER_TICK = 1

# 交易时段（含端点，legacy game.js 1858-1859）
MORNING_OPEN = 9 * 60 + 30  # 570
MORNING_CLOSE = 11 * 60 + 30  # 690
AFTERNOON_OPEN = 13 * 60  # 780
AFTERNOON_CLOSE = 15 * 60  # 900

# 时段窗口（成就与状态文案）
EARLY_BIRD_START = 9 * 60 + 30  # 570，9:30-9:35（legacy 1819）
EARLY_BIRD_END = 9 * 60 + 35  # 575
NIGHT_OWL_START = 11 * 60 + 35  # 695，11:35-11:40（legacy 1822）
NIGHT_OWL_END = 11 * 60 + 40  # 700
AFTERNOON_OPEN_WINDOW_END = 13 * 60 + 5  # 785，13:00-13:05（legacy 1825）

# 随机开局时间：9:30-11:30 之间均匀分布（legacy 1868-1880）
RANDOM_START_MINUTES = MORNING_CLOSE - MORNING_OPEN + 1  # 121
START_TIME_SENTINEL_TICK = -2  # rng 的保留 tick，仅用于开局时间

# “跳过”的目标分钟（legacy 1914-1925）：各时段结束前 1 分钟，或下一时段开盘前 1 分钟
SKIP_MORNING_END = 11 * 60 + 29  # 689，11:29
SKIP_NIGHT_OWL_END = 11 * 60 + 39  # 699，11:39
SKIP_AFTERNOON_END = 14 * 60 + 59  # 899，14:59
SKIP_BEFORE_MORNING = 9 * 60 + 29  # 569，9:29（次日开盘前同值）
SKIP_BEFORE_NIGHT_OWL = 11 * 60 + 34  # 694，11:34
SKIP_BEFORE_AFTERNOON = 12 * 60 + 59  # 779，12:59

SessionLabel = Literal["early_bird", "night_owl", "afternoon_open", "trading", "closed"]


def is_trading_time(minute_of_day: int) -> bool:
    """上午 9:30-11:30 或下午 13:00-15:00（含端点）。"""
    return (MORNING_OPEN <= minute_of_day <= MORNING_CLOSE) or (
        AFTERNOON_OPEN <= minute_of_day <= AFTERNOON_CLOSE
    )


def session_label(minute_of_day: int) -> SessionLabel:
    """行情状态文案的分类（不含“暂停”，暂停由调用方判断）。优先级同 legacy。"""
    if EARLY_BIRD_START <= minute_of_day <= EARLY_BIRD_END:
        return "early_bird"
    if NIGHT_OWL_START <= minute_of_day <= NIGHT_OWL_END:
        return "night_owl"
    if AFTERNOON_OPEN <= minute_of_day <= AFTERNOON_OPEN_WINDOW_END:
        return "afternoon_open"
    if is_trading_time(minute_of_day):
        return "trading"
    return "closed"


def is_early_bird_window(minute_of_day: int) -> bool:
    return EARLY_BIRD_START <= minute_of_day <= EARLY_BIRD_END


def is_night_owl_window(minute_of_day: int) -> bool:
    return NIGHT_OWL_START <= minute_of_day <= NIGHT_OWL_END


def advance_minute(minute_of_day: int, minutes_per_tick: int = DEFAULT_MINUTES_PER_TICK) -> int:
    """推进一个 tick 的游戏分钟，跨日回绕（legacy 1778-1795）。"""
    if minutes_per_tick <= 0:
        raise ValueError("minutes_per_tick must be positive")
    return (minute_of_day + minutes_per_tick) % MINUTES_PER_DAY


def random_start_minute(seed: int) -> int:
    """确定性的开局分钟（9:30-11:30 之间）。"""
    return MORNING_OPEN + rand_below(seed, START_TIME_SENTINEL_TICK, 0, 0, RANDOM_START_MINUTES)


def skip_target_minutes(minute_of_day: int) -> int | None:
    """“跳过”的目标分钟，返回 None 表示无需跳过（legacy 1914-1925 同规则）。"""
    cur = minute_of_day
    if MORNING_OPEN <= cur <= MORNING_CLOSE:  # 上午盘 → 11:29
        return SKIP_MORNING_END if cur < SKIP_MORNING_END else None
    if NIGHT_OWL_START <= cur <= NIGHT_OWL_END:  # 夜猫 → 11:39
        return SKIP_NIGHT_OWL_END if cur < SKIP_NIGHT_OWL_END else None
    if AFTERNOON_OPEN <= cur <= AFTERNOON_CLOSE:  # 下午盘 → 14:59
        return SKIP_AFTERNOON_END if cur < SKIP_AFTERNOON_END else None
    if cur < MORNING_OPEN:
        return SKIP_BEFORE_MORNING  # → 9:29
    if cur < NIGHT_OWL_START:
        return SKIP_BEFORE_NIGHT_OWL  # → 11:34
    if cur < AFTERNOON_OPEN:
        return SKIP_BEFORE_AFTERNOON  # → 12:59
    return SKIP_BEFORE_MORNING  # → 次日 9:29


def skip_ticks(minute_of_day: int, target_minute: int) -> int:
    """从当前分钟跳到目标分钟需要的分钟数（跨日）。"""
    return (target_minute - minute_of_day + MINUTES_PER_DAY) % MINUTES_PER_DAY
