"""剧本：从重大事件中贪心挑 N 个回合（03 §4.2）。纯函数，无 I/O。

- `major_ref` 由 A 的 GameEvent 与 B 的题目派生判定点（trigger = 首条快讯 tick，
  resolve = 全部题目判定 tick 的最大值）。
- `plan_rounds` 只看 MajorRef；非回合重大事件允许存在（不出题、不开市、不停顿）。
- `holdable_v2` 排除 11:30 / 15:00 两个只出价不接单的偏移（停顿点必须可下单）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..clock import CLOCK_RULES_V2, is_order_time, timebase, v2_minute_of_offset
from ..events.types import GameEvent
from ..predictions.types import BinaryQ, BucketQ, QuestionSpec, RankQ


@dataclass(frozen=True)
class MajorRef:
    """重大事件的判定信息。resolve_tt 为该事件全部题目判定 tick 的最大值。"""

    event_id: str
    kind: str
    trigger_tt: int
    resolve_tt: int


@dataclass(frozen=True)
class RoundPlan:
    event_ids: tuple[str, ...]  # 回合序 1..N
    hold_tts: tuple[int, ...]
    resolve_tts: tuple[int, ...]  # 与回合一一对应（该回合事件的判定 tick）
    end_tt: int  # = max(resolve_tts)


def holdable_v2(tt: int) -> bool:
    """v2 下该交易 tick 能否作为停顿点：偏移不是 11:30（120）或 15:00（241）。"""
    tb = timebase(CLOCK_RULES_V2)
    return is_order_time(v2_minute_of_offset(tb.offset_of(tt)), CLOCK_RULES_V2)


def major_ref(
    ev: GameEvent, questions: Sequence[QuestionSpec], *, clock_rules: int = CLOCK_RULES_V2
) -> MajorRef:
    """由重大事件与其题目（build_questions 的结果）派生判定点。无题目的事件不能当回合。"""
    if not questions:
        raise ValueError("a round event needs at least one question")
    tb = timebase(clock_rules)
    resolves: list[int] = []
    for q in questions:
        if isinstance(q, BucketQ):
            resolves.append(tb.first_tt(q.to_day + 1))  # 窗口末日收盘写入后的首 tick（02 §3.4）
        elif isinstance(q, RankQ):
            resolves.append(tb.first_tt(q.at_day + 1))
        elif isinstance(q, BinaryQ):
            if ev.rumor is None:
                raise ValueError("binary question without rumor")
            resolves.append(ev.rumor.resolve_trading_tick)
    return MajorRef(
        event_id=ev.event_id,
        kind=ev.kind,
        trigger_tt=ev.first_seen_trading_tick,
        resolve_tt=max(resolves),
    )


def plan_rounds(
    majors: Sequence[MajorRef],
    *,
    rounds: int,
    warmup: int,
    min_gap: int,
    max_burst: int,
    max_tt: int,
    holdable: Callable[[int], bool],
) -> RoundPlan | None:
    """贪心挑回合（03 §4.2）。不可行返回 None。

    候选：trigger ≥ warmup、holdable(trigger)，且同一 tick 上没有另一条重大事件的首条快讯；
    按 (trigger, event_id) 升序，第一个为回合 1，之后取第一个与上一停顿相隔 ≥ min_gap 的候选；
    每段快放 ≤ max_burst；resolve > hold；end_tt = max(resolve)，
    且 end − hold_N ≤ max_burst、end ≤ max_tt。
    """
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    per_tick = Counter(m.trigger_tt for m in majors)
    cands = sorted(
        (
            m
            for m in majors
            if per_tick[m.trigger_tt] == 1 and m.trigger_tt >= warmup and holdable(m.trigger_tt)
        ),
        key=lambda m: (m.trigger_tt, m.event_id),
    )
    chosen: list[MajorRef] = []
    prev = 0
    for m in cands:
        if len(chosen) == rounds:
            break
        if chosen and m.trigger_tt - prev < min_gap:
            continue
        if m.trigger_tt - prev > max_burst:
            return None  # 后续候选只会更远
        chosen.append(m)
        prev = m.trigger_tt
    if len(chosen) < rounds:
        return None
    if any(m.resolve_tt <= m.trigger_tt for m in chosen):
        return None
    end_tt = max(m.resolve_tt for m in chosen)
    if end_tt - chosen[-1].trigger_tt > max_burst or end_tt > max_tt:
        return None
    return RoundPlan(
        event_ids=tuple(m.event_id for m in chosen),
        hold_tts=tuple(m.trigger_tt for m in chosen),
        resolve_tts=tuple(m.resolve_tt for m in chosen),
        end_tt=end_tt,
    )
