"""游戏时钟与交易时段。时间单位：当日分钟数 minute_of_day ∈ [0, 1440)。

legacy 对应：game.js 1778-1795（推进）、1855-1862（交易时段）、1855-1925（跳过）、
1819-1829（时段窗口文案）。

时钟规则版本（`clock_rules`，按存档分版本，见 docs/10.26-plan/07-时钟v2.md）：
- v1（默认，`CLOCK_RULES_V1 = 1`）：每 20 个交易 tick 为一个交易日，本文件的旧函数即 v1 语义；
  所有窗口/相位函数的 `rules` 参数默认 1，因此旧调用点行为不变。
- v2（`CLOCK_RULES_V2 = 2`）：每 242 个交易 tick（9:30–11:30、13:00–15:00 的每一分钟）为一个交易日，
  换日在次日 9:30；撮合窗口为半开区间；午休/收盘后由调度纯函数快进。
规则差异集中在本文件的 `TimeBase` 与 `*_v2` / `rules` 分支，其它模块不写 `if clock_rules == 2`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .rng import rand_below

MINUTES_PER_DAY = 1440
CLOCK_RULES_V1 = 1
CLOCK_RULES_V2 = 2
TICKS_PER_TRADING_DAY = 20  # v1：每 20 个交易 tick 为一个交易日（legacy game.js 2019）
DEFAULT_MINUTES_PER_TICK = 1

# 交易时段（含端点，legacy game.js 1858-1859）
MORNING_OPEN = 9 * 60 + 30  # 570
MORNING_CLOSE = 11 * 60 + 30  # 690
AFTERNOON_OPEN = 13 * 60  # 780
AFTERNOON_CLOSE = 15 * 60  # 900

# 时段窗口（成就与状态文案）
EARLY_BIRD_START = 9 * 60 + 30  # 570，9:30-9:35（legacy 1819）
EARLY_BIRD_END = 9 * 60 + 35  # 575
NIGHT_OWL_START = 11 * 60 + 35  # 695，11:35-11:40（legacy 1822），v1 专用（在午休里，不可达）
NIGHT_OWL_END = 11 * 60 + 40  # 700
AFTERNOON_OPEN_WINDOW_END = 13 * 60 + 5  # 785，13:00-13:05（legacy 1825）

# v2 夜猫窗口：收盘前 5 分钟（与 legacy 文案“在收盘前5分钟完成交易”一致）
V2_NIGHT_OWL_START = 14 * 60 + 55  # 895
V2_NIGHT_OWL_END = 14 * 60 + 59  # 899

# 随机开局时间：9:30-11:30 之间均匀分布（legacy 1868-1880），仅 v1 使用
RANDOM_START_MINUTES = MORNING_CLOSE - MORNING_OPEN + 1  # 121
START_TIME_SENTINEL_TICK = -2  # rng 的保留 tick，仅用于 v1 开局时间

# “跳过”的目标分钟（legacy 1914-1925）：各时段结束前 1 分钟，或下一时段开盘前 1 分钟（v1）
SKIP_MORNING_END = 11 * 60 + 29  # 689，11:29
SKIP_NIGHT_OWL_END = 11 * 60 + 39  # 699，11:39
SKIP_AFTERNOON_END = 14 * 60 + 59  # 899，14:59
SKIP_BEFORE_MORNING = 9 * 60 + 29  # 569，9:29（次日开盘前同值）
SKIP_BEFORE_NIGHT_OWL = 11 * 60 + 34  # 694，11:34
SKIP_BEFORE_AFTERNOON = 12 * 60 + 59  # 779，12:59

# ---- v2 常量 ----
V2_TRADING_TICKS_PER_DAY = 242  # 9:30-11:30 (121 分钟) + 13:00-15:00 (121 分钟)
V2_START_MINUTE = MORNING_OPEN  # 开局固定 9:30（tt = 0）
V2_LUNCH_MINUTE = MORNING_CLOSE  # 690，上午收盘 tick（停留）
V2_REOPEN_MINUTE = AFTERNOON_OPEN  # 780
V2_CLOSE_MINUTE = AFTERNOON_CLOSE  # 900，收盘 tick（停留）
V2_PREOPEN_MINUTE = SKIP_BEFORE_MORNING  # 569，9:29，快进的落点
V2_LUNCH_JUMP_TARGET = 12 * 60 + 59  # 779，12:59
V2_LUNCH_DWELL_MS = 5_000  # 午休停留默认值（服务层从 Settings 读取后传入）
V2_CLOSE_DWELL_MS = 15_000  # 收盘小结停留默认值（服务层从 Settings 读取后传入）
V2_WS_PAUSED_POLL_MS = 2_000  # 暂停时 WS 轮询间隔
SPEED_MS_PER_MINUTE = {"fast": 2500, "normal": 5000, "slow": 7500}  # 用户节奏档 → ms/游戏分钟
DEFAULT_CLOCK_SPEED = "normal"

PhaseName = Literal["pre_open", "morning", "lunch", "afternoon", "closed"]
NextEventKind = Literal["open", "lunch", "reopen", "close"]
SessionLabel = Literal["early_bird", "night_owl", "afternoon_open", "trading", "closed"]


@dataclass(frozen=True)
class TimeBase:
    """交易日时间基：每个交易日的交易 tick 数。事件、行情、分时都通过它换算，不硬编码 20。"""

    ticks_per_day: int

    def day_of(self, trading_tick: int) -> int:
        return trading_tick // self.ticks_per_day

    def first_tt(self, day: int) -> int:
        """第 day 日的第一个 tick 编号（第 0 日为 0，与 v1 相同）。"""
        return self.ticks_per_day * day

    def offset_of(self, trading_tick: int) -> int:
        return trading_tick % self.ticks_per_day

    def rolls_at(self, trading_tick: int) -> bool:
        """该 tick 是否为换日 tick（先换日再走价）。第 0 个 tick 不换日。"""
        return trading_tick > 0 and trading_tick % self.ticks_per_day == 0


def _check_rules(clock_rules: int) -> None:
    if clock_rules not in (CLOCK_RULES_V1, CLOCK_RULES_V2):
        raise ValueError(f"unknown clock_rules: {clock_rules}")


def timebase(clock_rules: int) -> TimeBase:
    _check_rules(clock_rules)
    if clock_rules == CLOCK_RULES_V2:
        return TimeBase(V2_TRADING_TICKS_PER_DAY)
    return TimeBase(TICKS_PER_TRADING_DAY)


def v2_minute_of_offset(offset: int) -> int:
    """v2 日内交易 tick 偏移 0..241 → 游戏分钟。"""
    if not 0 <= offset < V2_TRADING_TICKS_PER_DAY:
        raise ValueError(f"offset out of range: {offset}")
    if offset <= 120:
        return MORNING_OPEN + offset
    return AFTERNOON_OPEN + (offset - 121)


def v2_tick_of(day: int, offset: int) -> int:
    """v2 全局 tick（自开局起的分钟数，与 save.tick 同口径）的闭式。"""
    return MINUTES_PER_DAY * day + (v2_minute_of_offset(offset) - MORNING_OPEN)


def v2_expected_offset(minute_of_day: int) -> int:
    """v2 存档在游戏分钟 m 时应有的 tt % 242（对齐不变量）。"""
    m = minute_of_day
    if MORNING_OPEN <= m <= MORNING_CLOSE:
        return m - MORNING_OPEN
    if MORNING_CLOSE < m < AFTERNOON_OPEN:
        return 120
    if AFTERNOON_OPEN <= m <= AFTERNOON_CLOSE:
        return m - (AFTERNOON_OPEN - 121)
    return V2_TRADING_TICKS_PER_DAY - 1


def is_trading_time(minute_of_day: int) -> bool:
    """上午 9:30-11:30 或下午 13:00-15:00（含端点）。两版行情的价格 tick 都在此集合内。"""
    return (MORNING_OPEN <= minute_of_day <= MORNING_CLOSE) or (
        AFTERNOON_OPEN <= minute_of_day <= AFTERNOON_CLOSE
    )


def is_order_time(minute_of_day: int, clock_rules: int = CLOCK_RULES_V1) -> bool:
    """此刻能否下单（撮合窗口）。v1 = is_trading_time；v2 为半开区间，11:30 与 15:00 不接单。"""
    _check_rules(clock_rules)
    if clock_rules == CLOCK_RULES_V1:
        return is_trading_time(minute_of_day)
    m = minute_of_day
    return (MORNING_OPEN <= m < MORNING_CLOSE) or (AFTERNOON_OPEN <= m < AFTERNOON_CLOSE)


def phase_of(minute_of_day: int, clock_rules: int = CLOCK_RULES_V1) -> PhaseName:
    """时段相位（状态栏用）。v1 的上午盘含 11:30 端点，v2 为半开区间。"""
    _check_rules(clock_rules)
    m = minute_of_day
    if clock_rules == CLOCK_RULES_V1:
        if m < MORNING_OPEN:
            return "pre_open"
        if m <= MORNING_CLOSE:
            return "morning"
        if m < AFTERNOON_OPEN:
            return "lunch"
        if m <= AFTERNOON_CLOSE:
            return "afternoon"
        return "closed"
    if m < MORNING_OPEN:
        return "pre_open"
    if m < MORNING_CLOSE:
        return "morning"
    if m < AFTERNOON_OPEN:
        return "lunch"
    if m < AFTERNOON_CLOSE:
        return "afternoon"
    return "closed"


_NEXT_EVENT: dict[str, tuple[NextEventKind, int]] = {
    "pre_open": ("open", MORNING_OPEN),
    "morning": ("lunch", MORNING_CLOSE),
    "lunch": ("reopen", AFTERNOON_OPEN),
    "afternoon": ("close", AFTERNOON_CLOSE),
    "closed": ("open", MORNING_OPEN),
}


def next_event_of(
    minute_of_day: int, clock_rules: int = CLOCK_RULES_V1
) -> tuple[NextEventKind, int]:
    """下一个时段变化：(kind, 分钟)。kind=close 时分钟为 900；closed 相位的 open 指次日开盘。"""
    return _NEXT_EVENT[phase_of(minute_of_day, clock_rules)]


def session_label(minute_of_day: int) -> SessionLabel:
    """v1 行情状态文案的分类（不含“暂停”，暂停由调用方判断）。优先级同 legacy。"""
    if EARLY_BIRD_START <= minute_of_day <= EARLY_BIRD_END:
        return "early_bird"
    if NIGHT_OWL_START <= minute_of_day <= NIGHT_OWL_END:
        return "night_owl"
    if AFTERNOON_OPEN <= minute_of_day <= AFTERNOON_OPEN_WINDOW_END:
        return "afternoon_open"
    if is_trading_time(minute_of_day):
        return "trading"
    return "closed"


def session_label_v2(minute_of_day: int) -> SessionLabel:
    """v2 行情状态文案：早盘窗口、午后开盘窗口、收盘前夜猫窗口优先，其余可下单分钟为 trading。"""
    m = minute_of_day
    if EARLY_BIRD_START <= m <= EARLY_BIRD_END:
        return "early_bird"
    if AFTERNOON_OPEN <= m <= AFTERNOON_OPEN_WINDOW_END:
        return "afternoon_open"
    if V2_NIGHT_OWL_START <= m <= V2_NIGHT_OWL_END:
        return "night_owl"
    if is_order_time(m, CLOCK_RULES_V2):
        return "trading"
    return "closed"


def is_early_bird_window(minute_of_day: int, clock_rules: int = CLOCK_RULES_V1) -> bool:
    _check_rules(clock_rules)
    return EARLY_BIRD_START <= minute_of_day <= EARLY_BIRD_END


def is_night_owl_window(minute_of_day: int, clock_rules: int = CLOCK_RULES_V1) -> bool:
    _check_rules(clock_rules)
    if clock_rules == CLOCK_RULES_V2:
        return V2_NIGHT_OWL_START <= minute_of_day <= V2_NIGHT_OWL_END
    return NIGHT_OWL_START <= minute_of_day <= NIGHT_OWL_END


def advance_minute(minute_of_day: int, minutes_per_tick: int = DEFAULT_MINUTES_PER_TICK) -> int:
    """推进一个 tick 的游戏分钟，跨日回绕（legacy 1778-1795）。"""
    if minutes_per_tick <= 0:
        raise ValueError("minutes_per_tick must be positive")
    return (minute_of_day + minutes_per_tick) % MINUTES_PER_DAY


def random_start_minute(seed: int) -> int:
    """v1 确定性的开局分钟（9:30-11:30 之间）。v2 固定从 9:30 开局，不调用本函数。"""
    return MORNING_OPEN + rand_below(seed, START_TIME_SENTINEL_TICK, 0, 0, RANDOM_START_MINUTES)


def skip_target_minutes(minute_of_day: int) -> int | None:
    """v1 “跳过”的目标分钟，返回 None 表示无需跳过（legacy 1914-1925 同规则）。"""
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


def skip_target_v2(minute_of_day: int) -> int:
    """v2 “跳过”的目标分钟：每次至少推进 1 分钟，跳到下一个关键时点（07 §6.5）。"""
    m = minute_of_day
    if MORNING_OPEN <= m <= 688:
        return 689
    if m == 689:
        return MORNING_CLOSE
    if MORNING_CLOSE <= m <= 778:
        return V2_LUNCH_JUMP_TARGET
    if m == V2_LUNCH_JUMP_TARGET:
        return AFTERNOON_OPEN
    if AFTERNOON_OPEN <= m <= 898:
        return 899
    if m == 899:
        return AFTERNOON_CLOSE
    if m == V2_PREOPEN_MINUTE:
        return MORNING_OPEN
    return V2_PREOPEN_MINUTE  # ≥ 900 或 < 569 → 次日 9:29


def skip_ticks(minute_of_day: int, target_minute: int) -> int:
    """从当前分钟跳到目标分钟需要的分钟数（跨日）。"""
    return (target_minute - minute_of_day + MINUTES_PER_DAY) % MINUTES_PER_DAY


# ---------- v2 墙钟调度（纯函数，毫秒整数，不读系统时钟） ----------


@dataclass(frozen=True)
class Step:
    """一步调度：kind=tick 推进一个交易分钟；kind=jump 为非交易推进（不走价）。
    due_ms 为该步到期的墙钟毫秒（anchor 的新值）；minutes 为推进的游戏分钟数。"""

    kind: Literal["tick", "jump"]
    due_ms: int
    minutes: int


def _is_tick_source(m: int) -> bool:
    """下一分钟是交易分钟，且当前分钟不是停留点：9:29–11:29、12:59–14:59。"""
    return (V2_PREOPEN_MINUTE <= m <= 689) or (V2_LUNCH_JUMP_TARGET <= m <= 899)


def next_step_v2(
    minute_of_day: int,
    anchor_ms: int,
    *,
    ms_per_minute: int,
    lunch_dwell_ms: int = V2_LUNCH_DWELL_MS,
    close_dwell_ms: int = V2_CLOSE_DWELL_MS,
) -> Step:
    """时钟在分钟 m 时（到达时刻 anchor_ms）的下一步（07 §5.2 状态表）。

    11:30 停留 lunch_dwell_ms 后跳到 12:59；15:00 停留 close_dwell_ms 后跳到次日 9:29；
    交易时段每 ms_per_minute 推进一分钟；其它非交易分钟立即跳到下一个 9:29 或 12:59
    （仅 debug/手工改库可达）。
    """
    m = minute_of_day
    if m == V2_LUNCH_MINUTE:
        return Step("jump", anchor_ms + lunch_dwell_ms, V2_LUNCH_JUMP_TARGET - m)
    if m == V2_CLOSE_MINUTE:
        return Step("jump", anchor_ms + close_dwell_ms, (V2_PREOPEN_MINUTE - m) % MINUTES_PER_DAY)
    if _is_tick_source(m):
        return Step("tick", anchor_ms + ms_per_minute, 1)
    if V2_LUNCH_MINUTE < m < V2_LUNCH_JUMP_TARGET:  # 午休中的非停留分钟
        return Step("jump", anchor_ms, V2_LUNCH_JUMP_TARGET - m)
    return Step("jump", anchor_ms, (V2_PREOPEN_MINUTE - m) % MINUTES_PER_DAY)


@dataclass(frozen=True)
class CatchupPlan:
    minutes: int  # 总推进的游戏分钟数（含跳转）
    trading_ticks: int  # 其中交易 tick 数（计入上限）
    anchor_ms: int  # 计划结束时的锚点（丢弃时间时为 now_ms）
    truncated: bool  # 因交易 tick 上限而丢弃了剩余墙钟时间


def plan_catchup_v2(
    minute_of_day: int,
    anchor_ms: int,
    now_ms: int,
    *,
    ms_per_minute: int,
    lunch_dwell_ms: int = V2_LUNCH_DWELL_MS,
    close_dwell_ms: int = V2_CLOSE_DWELL_MS,
    max_trading_ticks: int,
) -> CatchupPlan:
    """从 (分钟, 锚点) 出发反复取 next_step_v2，直到到期点晚于 now_ms。

    交易 tick 达到 max_trading_ticks 且仍有到期步骤时截断：锚点置为 now_ms（丢弃剩余墙钟时间）。
    jump 步不计入上限。
    """
    m, anchor = minute_of_day, anchor_ms
    minutes = 0
    trading = 0
    truncated = False
    while True:
        step = next_step_v2(
            m,
            anchor,
            ms_per_minute=ms_per_minute,
            lunch_dwell_ms=lunch_dwell_ms,
            close_dwell_ms=close_dwell_ms,
        )
        if step.due_ms > now_ms:
            break
        if step.kind == "tick" and trading >= max_trading_ticks:
            truncated = True
            anchor = now_ms
            break
        m = (m + step.minutes) % MINUTES_PER_DAY
        minutes += step.minutes
        anchor = step.due_ms
        if step.kind == "tick":
            trading += 1
    return CatchupPlan(
        minutes=minutes, trading_ticks=trading, anchor_ms=anchor, truncated=truncated
    )


def ms_until_minute_v2(
    minute_of_day: int,
    anchor_ms: int,
    target_minute: int,
    *,
    ms_per_minute: int,
    lunch_dwell_ms: int = V2_LUNCH_DWELL_MS,
    close_dwell_ms: int = V2_CLOSE_DWELL_MS,
) -> int | None:
    """按调度表推演，返回到达 target_minute 的墙钟毫秒（next_event.at 用）；一天内未到达则 None。"""
    m, anchor = minute_of_day, anchor_ms
    for _ in range(4 * MINUTES_PER_DAY):
        step = next_step_v2(
            m,
            anchor,
            ms_per_minute=ms_per_minute,
            lunch_dwell_ms=lunch_dwell_ms,
            close_dwell_ms=close_dwell_ms,
        )
        m = (m + step.minutes) % MINUTES_PER_DAY
        anchor = step.due_ms
        if m == target_minute:
            return anchor
    return None


__all__ = [
    "CLOCK_RULES_V1",
    "CLOCK_RULES_V2",
    "DEFAULT_CLOCK_SPEED",
    "MINUTES_PER_DAY",
    "SPEED_MS_PER_MINUTE",
    "TICKS_PER_TRADING_DAY",
    "V2_TRADING_TICKS_PER_DAY",
    "CatchupPlan",
    "Step",
    "TimeBase",
    "advance_minute",
    "is_early_bird_window",
    "is_night_owl_window",
    "is_order_time",
    "is_trading_time",
    "ms_until_minute_v2",
    "next_event_of",
    "next_step_v2",
    "phase_of",
    "plan_catchup_v2",
    "random_start_minute",
    "session_label",
    "session_label_v2",
    "skip_target_minutes",
    "skip_target_v2",
    "skip_ticks",
    "timebase",
    "v2_expected_offset",
    "v2_minute_of_offset",
    "v2_tick_of",
]
