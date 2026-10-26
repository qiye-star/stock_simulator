"""剧本可行性（03 §13.1、§4.2、C1）：真实 data/*.json + A（事件）、B（预测题）代码，v2 时间基。

30 个日期、固定测试密钥，每个都应在 64 次内筛出剧本；打印尝试次数与 end_tt 分布（pytest -s）。
"""

import datetime
import statistics

from stocksim.domain.challenge.commit import derive_seed
from stocksim.domain.challenge.constants import (
    CHALLENGE_CLOCK_RULES,
    CHALLENGE_CLOSE_LEAD_MS,
    CHALLENGE_MAX_BURST_TT,
    CHALLENGE_MAX_TT,
    CHALLENGE_MIN_ROUND_GAP_TT,
    CHALLENGE_ROUNDS,
    CHALLENGE_SCAN_DAYS,
    CHALLENGE_SEED_MAX_ATTEMPTS,
    CHALLENGE_TICK_MS,
    CHALLENGE_WARMUP_TT,
)
from stocksim.domain.challenge.script import MajorRef, holdable_v2, major_ref, plan_rounds
from stocksim.domain.challenge.timeline import build_timeline
from stocksim.domain.clock import is_order_time, v2_minute_of_offset
from stocksim.domain.events import EVENT_RULESET_VERSION
from stocksim.domain.events.generate import generate_day
from stocksim.domain.events.graph import save_params
from stocksim.domain.predictions.questions import QuestionContext, build_questions
from stocksim.services import events as events_service
from stocksim.services import predictions as predictions_service

TEST_KEY = b"stocksim-test-challenge-key"
DATES = [(datetime.date(2026, 11, 1) + datetime.timedelta(days=i)).isoformat() for i in range(30)]
T0_MS = 1_790_000_000_000
SLOT_MS = 3 * 3_600_000  # 回合之间相隔 3 小时（> 最长快放 726 × 750 ms）
MIN_WINDOW_MS = 30 * 60_000  # daily 模式的作答窗口下限


def _majors(seed, ruleset, structure) -> list[MajorRef]:
    params = save_params(seed, ruleset)
    out: list[MajorRef] = []
    for day in range(CHALLENGE_SCAN_DAYS):
        for ev in generate_day(seed, day, ruleset, params):
            if not ev.major:
                continue
            ctx = QuestionContext(
                seed=seed,
                trigger_trading_tick=ev.first_seen_trading_tick,
                structure=structure,
                clock_rules=CHALLENGE_CLOCK_RULES,
            )
            out.append(major_ref(ev, build_questions(ev, ctx), clock_rules=CHALLENGE_CLOCK_RULES))
    return out


def _screen(date_iso, ruleset, structure):
    for attempt in range(CHALLENGE_SEED_MAX_ATTEMPTS):
        seed = derive_seed(TEST_KEY, date_iso, attempt)
        plan = plan_rounds(
            _majors(seed, ruleset, structure),
            rounds=CHALLENGE_ROUNDS,
            warmup=CHALLENGE_WARMUP_TT,
            min_gap=CHALLENGE_MIN_ROUND_GAP_TT,
            max_burst=CHALLENGE_MAX_BURST_TT,
            max_tt=CHALLENGE_MAX_TT,
            holdable=holdable_v2,
        )
        if plan is not None:
            return attempt + 1, plan
    return None, None


def test_screening_finds_plan_for_every_date():
    ruleset = events_service.ruleset(EVENT_RULESET_VERSION, CHALLENGE_CLOCK_RULES)
    structure = predictions_service.structure_for(EVENT_RULESET_VERSION)
    attempts: list[int] = []
    ends: list[int] = []
    for date_iso in DATES:
        n, plan = _screen(date_iso, ruleset, structure)
        assert plan is not None, f"no plan in {CHALLENGE_SEED_MAX_ATTEMPTS} attempts: {date_iso}"
        attempts.append(n)
        ends.append(plan.end_tt)

        holds, resolves = plan.hold_tts, plan.resolve_tts
        assert len(holds) == CHALLENGE_ROUNDS == len(resolves)
        assert len(set(plan.event_ids)) == CHALLENGE_ROUNDS
        assert holds[0] >= CHALLENGE_WARMUP_TT
        assert all(holdable_v2(h) for h in holds)
        assert all(
            is_order_time(v2_minute_of_offset(h % 242), CHALLENGE_CLOCK_RULES) for h in holds
        )
        prev = 0
        for h in holds:
            assert h - prev <= CHALLENGE_MAX_BURST_TT
            if prev:
                assert h - prev >= CHALLENGE_MIN_ROUND_GAP_TT
            prev = h
        assert all(r > h for h, r in zip(holds, resolves, strict=True))
        assert plan.end_tt == max(resolves)
        assert plan.end_tt - holds[-1] <= CHALLENGE_MAX_BURST_TT
        assert plan.end_tt <= CHALLENGE_MAX_TT

        # 与时间线联动：真实毫秒参数下可以组装且停顿可下单
        resume = [T0_MS + k * SLOT_MS for k in range(CHALLENGE_ROUNDS + 1)]
        tl = build_timeline(
            hold_tts=holds,
            end_tt=plan.end_tt,
            resume_ms=resume,
            tick_ms=CHALLENGE_TICK_MS,
            close_lead_ms=CHALLENGE_CLOSE_LEAD_MS,
            min_window_ms=MIN_WINDOW_MS,
        )
        assert tl.ends_ms > resume[-1]

    ends.sort()
    print(
        f"\n[C1 screening] dates={len(DATES)} attempts(mean={statistics.mean(attempts):.3f}, "
        f"max={max(attempts)}, first-try={attempts.count(1)}/{len(attempts)}) "
        f"end_tt(min={ends[0]}, median={statistics.median(ends):.0f}, "
        f"p95={ends[int(len(ends) * 0.95) - 1]}, max={ends[-1]})"
    )
