"""公共时间线（03 §1.2、§4.2）：真实时间 ↔ 公共交易 tick 的纯函数映射。

约定：时间一律 epoch 毫秒整数。
- hold_tts 为 hold_1..hold_N（hold_0 = 0 隐含）；resume_ms 为 resume_1..resume_{N+1}，
  resume_{N+1} 是最终段开始。第 k 段快放 = [resume_k, hold_at_k)，停顿 = [hold_at_k, resume_{k+1})。
- 不含服务层的 now()；调用方传入 now_ms。
- minutes_to_tt 只在交易分钟前进 tt，午休与隔夜通过分钟数“瞬间跨过”（v2 全局 tick = 分钟数）。
"""

from __future__ import annotations

import bisect
import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..clock import MINUTES_PER_DAY, is_trading_time

PhaseName = Literal["before", "burst", "hold", "final", "ended"]


@dataclass(frozen=True)
class Timeline:
    hold_tts: tuple[int, ...]  # hold_1..hold_N
    end_tt: int  # 最后一题判定 tick（服务端保密）
    resume_ms: tuple[int, ...]  # resume_1..resume_{N+1}
    hold_at_ms: tuple[int, ...]  # 第 k 回合（下标 k-1）停顿开始
    closes_ms: tuple[int, ...]  # 第 k 回合作答截止 = resume_{k+1} - close_lead
    ends_ms: int  # 最终段结束（服务端保密）
    tick_ms: int
    close_lead_ms: int

    @property
    def rounds(self) -> int:
        return len(self.hold_tts)


@dataclass(frozen=True)
class PhaseInfo:
    """phase 取值见 PhaseName；round_index 为 1 起的回合序号：before 为 None，
    burst/hold 为所在回合，final/ended 为 N（最后一个回合）。
    next_change_ms 为下一次阶段变化时刻。"""

    phase: PhaseName
    round_index: int | None
    next_change_ms: int | None


def build_timeline(
    *,
    hold_tts: Sequence[int],
    end_tt: int,
    resume_ms: Sequence[int],
    tick_ms: int,
    close_lead_ms: int,
    min_window_ms: int,
) -> Timeline:
    """校验并组装时间线。时段必须递增；每段快放结束早于截止，且作答窗口 ≥ min_window_ms。"""
    n = len(hold_tts)
    if n < 1:
        raise ValueError("at least one round is required")
    if len(resume_ms) != n + 1:
        raise ValueError("resume_ms must have N+1 entries")
    if tick_ms <= 0 or close_lead_ms < 0 or min_window_ms < 0:
        raise ValueError("invalid timing parameters")
    prev_tt = 0
    for h in hold_tts:
        if h <= prev_tt:
            raise ValueError("hold_tts must be strictly increasing and > 0")
        prev_tt = h
    if end_tt <= prev_tt:
        raise ValueError("end_tt must be after the last hold")
    for a, b in itertools.pairwise(resume_ms):
        if b <= a:
            raise ValueError("resume_ms must be strictly increasing")

    hold_at: list[int] = []
    closes: list[int] = []
    prev = 0
    for k in range(n):
        h_at = resume_ms[k] + (hold_tts[k] - prev) * tick_ms
        close = resume_ms[k + 1] - close_lead_ms
        if close - h_at < min_window_ms:
            raise ValueError(f"round {k + 1} answer window too short")
        hold_at.append(h_at)
        closes.append(close)
        prev = hold_tts[k]
    ends = resume_ms[n] + (end_tt - prev) * tick_ms
    return Timeline(
        hold_tts=tuple(hold_tts),
        end_tt=end_tt,
        resume_ms=tuple(resume_ms),
        hold_at_ms=tuple(hold_at),
        closes_ms=tuple(closes),
        ends_ms=ends,
        tick_ms=tick_ms,
        close_lead_ms=close_lead_ms,
    )


def target_tt(tl: Timeline, now_ms: int) -> int:
    """公共交易 tick tt(now)。单调不减；now ≥ ends_ms 时为 end_tt。"""
    if now_ms < tl.resume_ms[0]:
        return 0
    if now_ms >= tl.ends_ms:
        return tl.end_tt
    n = tl.rounds
    i = bisect.bisect_right(tl.resume_ms, now_ms) - 1  # 0..n
    prev = tl.hold_tts[i - 1] if i > 0 else 0
    if i == n:  # 最终段
        return prev + (now_ms - tl.resume_ms[n]) // tl.tick_ms
    if now_ms < tl.hold_at_ms[i]:  # 快放段
        return prev + (now_ms - tl.resume_ms[i]) // tl.tick_ms
    return tl.hold_tts[i]  # 停顿段


def reached_ms(tl: Timeline, tt: int) -> int:
    """公共 tt 首次到达的时刻（epoch ms）。tt ≤ 0 返回 resume_1；tt > end_tt 抛 ValueError。"""
    if tt <= 0:
        return tl.resume_ms[0]
    if tt > tl.end_tt:
        raise ValueError("tt beyond end_tt")
    bounds = (*tl.hold_tts, tl.end_tt)
    k = bisect.bisect_left(bounds, tt)  # 第一个 bounds[k] ≥ tt
    prev = bounds[k - 1] if k > 0 else 0
    return tl.resume_ms[k] + (tt - prev) * tl.tick_ms


def phase_at(tl: Timeline, now_ms: int) -> PhaseInfo:
    n = tl.rounds
    if now_ms < tl.resume_ms[0]:
        return PhaseInfo("before", None, tl.resume_ms[0])
    if now_ms >= tl.ends_ms:
        return PhaseInfo("ended", n, None)
    i = bisect.bisect_right(tl.resume_ms, now_ms) - 1
    if i == n:
        return PhaseInfo("final", n, tl.ends_ms)
    if now_ms < tl.hold_at_ms[i]:
        return PhaseInfo("burst", i + 1, tl.hold_at_ms[i])
    return PhaseInfo("hold", i + 1, tl.resume_ms[i + 1])


def minutes_to_tt(cur_minute: int, cur_tt: int, target: int) -> int:
    """从（游戏分钟 cur_minute，公共 tt cur_tt）逐分钟前进，直到交易 tick 恰好等于 target。

    返回要推进的全局 tick 数（= 分钟数）。交易分钟（`is_trading_time`）才使 tt 加一；
    午休与隔夜的非交易分钟计入返回值但不调用行情推进。cur_minute 必须与 cur_tt 对齐（v2 不变量）。
    """
    if target < cur_tt:
        raise ValueError("target must not be behind current tt")
    if not 0 <= cur_minute < MINUTES_PER_DAY:
        raise ValueError("cur_minute out of range")
    if target == cur_tt:
        return 0
    minute, tt, steps = cur_minute, cur_tt, 0
    limit = MINUTES_PER_DAY * (target - cur_tt + 2)
    while tt < target:
        minute = (minute + 1) % MINUTES_PER_DAY
        steps += 1
        if is_trading_time(minute):
            tt += 1
        if steps > limit:  # 不可达（分钟不对齐）
            raise ValueError("target unreachable from cur_minute")
    return steps
