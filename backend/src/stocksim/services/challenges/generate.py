"""挑战生成（03 §4.3）：seed 派生、剧本筛选、时段、单事务建 master 与挑战行。

日志只记 challenge_date、seed_attempt、seed_commitment（03 §5 #11）：不含 seed、盐或承诺原文。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.commit import derive_seed, make_commitment
from stocksim.domain.challenge.constants import (
    CHALLENGE_BUY_FEE_RATE,
    CHALLENGE_CLOCK_RULES,
    CHALLENGE_CLOSE_LEAD_MS,
    CHALLENGE_FORMAT_VERSION,
    CHALLENGE_MAX_BURST_TT,
    CHALLENGE_MAX_TT,
    CHALLENGE_MIN_ROUND_GAP_TT,
    CHALLENGE_ROUNDS,
    CHALLENGE_SCAN_DAYS,
    CHALLENGE_SEED_MAX_ATTEMPTS,
    CHALLENGE_SELL_FEE_RATE,
    CHALLENGE_START_MINUTE,
    CHALLENGE_TRADE_UNIT,
    CHALLENGE_WARMUP_TT,
)
from stocksim.domain.challenge.script import (
    MajorRef,
    RoundPlan,
    holdable_v2,
    major_ref,
    plan_rounds,
)
from stocksim.domain.challenge.timeline import build_timeline
from stocksim.domain.events import EVENT_RULESET_VERSION
from stocksim.domain.events.types import GameEvent
from stocksim.domain.predictions.constants import DIRECTION_WINDOW_DAYS
from stocksim.domain.predictions.questions import QuestionContext, build_questions
from stocksim.domain.predictions.types import QuestionSpec
from stocksim.models import Challenge, ChallengeRound, Save, SaveStats
from stocksim.models.save import SAVE_MODE_CHALLENGE_MARKET
from stocksim.services import events as events_service
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import clock, hooks
from stocksim.services.challenges.clock import MIN_WINDOW_MS
from stocksim.services.challenges.config import current_settings
from stocksim.services.challenges.registry import challenge_for_date, info_of
from stocksim.services.challenges.rounds import resolve_tt_of
from stocksim.services.challenges.timeutil import (
    ceil_5s,
    from_ms,
    parse_slots,
    slot_to_utc,
    to_ms,
)
from stocksim.services.market import init_market_for_save

logger = logging.getLogger(__name__)
SEED_KEY_LABEL = b"stocksim/challenge-seed-key/v1"
SLOT_LEAD_MS = 5_000  # compact：首个回合的恢复时刻 = 对齐到 5 秒后再加 5 秒
SETTLE_GRACE_MS = 60_000  # settle_expected_at 在最终段上界之外留出的余量
MASTER_FIRST_TT_MINUTE = CHALLENGE_START_MINUTE


def seed_key(settings: Settings | None = None) -> bytes:
    """seed 派生密钥（03 §1.4）：优先 CHALLENGE_SEED_KEY（UTF-8），否则 HMAC(SECRET_KEY, 标签)。"""
    settings = settings or current_settings()
    if settings.CHALLENGE_SEED_KEY:
        return settings.CHALLENGE_SEED_KEY.encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), SEED_KEY_LABEL, hashlib.sha256).digest()


@dataclass(frozen=True)
class _Screened:
    seed: int
    attempt: int
    plan: RoundPlan
    events: dict[str, tuple[GameEvent, tuple[QuestionSpec, ...]]]


def _screen(seed: int) -> _Screened | None:
    """对 seed 扫描排期日 [0, CHALLENGE_SCAN_DAYS) 的重大事件，贪心挑回合（script.plan_rounds）。"""
    version = EVENT_RULESET_VERSION
    structure = predictions_service.structure_for(version)
    majors: list[MajorRef] = []
    events: dict[str, tuple[GameEvent, tuple[QuestionSpec, ...]]] = {}
    for day in range(CHALLENGE_SCAN_DAYS):
        for ev in events_service.day_events(seed, version, CHALLENGE_CLOCK_RULES, day):
            if not ev.major:
                continue
            specs = build_questions(
                ev,
                QuestionContext(
                    seed=seed,
                    trigger_trading_tick=ev.first_seen_trading_tick,
                    structure=structure,
                    window_days=DIRECTION_WINDOW_DAYS,
                    clock_rules=CHALLENGE_CLOCK_RULES,
                ),
            )
            if not specs:
                continue
            majors.append(major_ref(ev, specs, clock_rules=CHALLENGE_CLOCK_RULES))
            events[ev.event_id] = (ev, specs)
    plan = plan_rounds(
        majors,
        rounds=CHALLENGE_ROUNDS,
        warmup=CHALLENGE_WARMUP_TT,
        min_gap=CHALLENGE_MIN_ROUND_GAP_TT,
        max_burst=CHALLENGE_MAX_BURST_TT,
        max_tt=CHALLENGE_MAX_TT,
        holdable=holdable_v2,
    )
    if plan is None:
        return None
    return _Screened(seed=seed, attempt=-1, plan=plan, events=events)


def _schedule(
    now: datetime, day: date, schedule: str, settings: Settings, rounds: int
) -> tuple[list[int], int]:
    """恢复时刻 resume_1..resume_{N+1}（epoch 毫秒）与快放 tick_ms（03 §4.3 第 3 条）。"""
    if schedule == "daily":
        slots = parse_slots(settings.CHALLENGE_SLOTS)
        if len(slots) != rounds + 1:
            raise ValueError("CHALLENGE_SLOTS must have rounds + 1 entries")
        return [to_ms(slot_to_utc(day, s)) for s in slots], settings.CHALLENGE_TICK_MS
    base = to_ms(ceil_5s(now)) + SLOT_LEAD_MS
    slot_ms = settings.CHALLENGE_COMPACT_SLOT_SECONDS * 1000
    return [base + k * slot_ms for k in range(rounds + 1)], settings.CHALLENGE_COMPACT_TICK_MS


def _master(day: date, seed: int, now: datetime) -> Save:
    """master 存档字段（03 §6.1）：无主人、零资金、冻结 v2 时钟、暂停。"""
    return Save(
        id=uuid.uuid4(),
        user_id=None,
        name=f"master {day.isoformat()}",
        mode=SAVE_MODE_CHALLENGE_MARKET,
        initial_fund_cents=0,
        cash_cents=0,
        buy_fee_rate=CHALLENGE_BUY_FEE_RATE,
        sell_fee_rate=CHALLENGE_SELL_FEE_RATE,
        t0_mode=False,
        trade_unit=CHALLENGE_TRADE_UNIT,
        market_seed=seed,
        tick=0,
        trade_seq=0,
        trading_day=0,
        clock_minute=MASTER_FIRST_TT_MINUTE,
        clock_rules=CHALLENGE_CLOCK_RULES,
        paused=True,
        last_tick_at=None,
        events_enabled=True,
        events_ruleset=EVENT_RULESET_VERSION,
        auto_enabled=False,
        auto_paused=False,
        auto_max_total_trades=100,
        created_at=now,
        updated_at=now,
    )


def ensure_challenge(
    db: Session, day: date, *, now: datetime, settings: Settings | None = None
) -> Challenge:
    """返回 day 的挑战；不存在则生成（幂等）。成功生成或作废后 commit。"""
    existing = challenge_for_date(db, day)
    if existing is not None:
        return existing
    settings = settings or current_settings()
    key = seed_key(settings)
    date_iso = day.isoformat()
    found: _Screened | None = None
    for attempt in range(CHALLENGE_SEED_MAX_ATTEMPTS):
        seed = derive_seed(key, date_iso, attempt)
        screened = _screen(seed)
        if screened is not None:
            found = _Screened(seed, attempt, screened.plan, screened.events)
            break
    if found is None:
        logger.error(
            "challenge screening failed: date=%s attempts=%d",
            date_iso,
            CHALLENGE_SEED_MAX_ATTEMPTS,
        )
        return _void_challenge(db, day, now, settings, key, "screening_failed")
    return _create_challenge(db, day, now, settings, found)


def _create_challenge(
    db: Session, day: date, now: datetime, settings: Settings, found: _Screened
) -> Challenge:
    date_iso = day.isoformat()
    schedule = settings.CHALLENGE_SCHEDULE
    resume_ms, tick_ms = _schedule(now, day, schedule, settings, CHALLENGE_ROUNDS)
    plan = found.plan
    timeline = build_timeline(
        hold_tts=plan.hold_tts,
        end_tt=plan.end_tt,
        resume_ms=resume_ms,
        tick_ms=tick_ms,
        close_lead_ms=CHALLENGE_CLOSE_LEAD_MS,
        min_window_ms=MIN_WINDOW_MS[schedule],
    )
    salt = secrets.token_hex(16)
    commitment = make_commitment(
        date_iso=date_iso,
        events_ruleset=EVENT_RULESET_VERSION,
        clock_rules=CHALLENGE_CLOCK_RULES,
        seed=found.seed,
        salt_hex=salt,
    )
    master = _master(day, found.seed, now)
    ch = Challenge(
        id=uuid.uuid4(),
        challenge_date=day,
        status="scheduled",
        schedule_mode=schedule,
        format_version=CHALLENGE_FORMAT_VERSION,
        events_ruleset=EVENT_RULESET_VERSION,
        clock_rules=CHALLENGE_CLOCK_RULES,
        seed_attempt=found.attempt,
        market_seed=found.seed,
        seed_salt=salt,
        seed_commitment=commitment,
        master_save_id=master.id,
        start_minute=CHALLENGE_START_MINUTE,
        tick_ms=tick_ms,
        end_tt=plan.end_tt,
        starts_at=from_ms(timeline.resume_ms[0]),
        entry_closes_at=from_ms(timeline.closes_ms[-1]),
        final_resume_at=from_ms(timeline.resume_ms[-1]),
        ends_at=from_ms(timeline.ends_ms),
        settle_expected_at=from_ms(
            timeline.resume_ms[-1] + CHALLENGE_MAX_BURST_TT * tick_ms + SETTLE_GRACE_MS
        ),
        eligible_count=0,
        created_at=now,
        updated_at=now,
    )
    rows: list[ChallengeRound] = []
    for k in range(CHALLENGE_ROUNDS):
        event_id = plan.event_ids[k]
        ev, specs = found.events[event_id]
        rows.append(
            ChallengeRound(
                id=uuid.uuid4(),
                challenge_id=ch.id,
                round_index=k + 1,
                event_id=event_id,
                from_tt=plan.hold_tts[k - 1] if k > 0 else 0,
                hold_tt=plan.hold_tts[k],
                resume_at=from_ms(timeline.resume_ms[k]),
                hold_at=from_ms(timeline.hold_at_ms[k]),
                closes_at=from_ms(timeline.closes_ms[k]),
                resolve_tts={q.qid: resolve_tt_of(ev, q) for q in specs},
                questions=None,
                outcomes={},
                answer_count=0,
            )
        )
    try:
        db.add(master)
        db.flush()
        db.add(SaveStats(save_id=master.id))
        init_market_for_save(db, master, as_of=day)
        db.add(ch)
        db.add_all(rows)
        db.flush()
        hooks.run_created(db, info_of(ch, timeline))
        db.commit()
    except IntegrityError:
        # challenge_date 唯一键冲突：另一实例已生成，回滚后返回已有行
        db.rollback()
        existing = challenge_for_date(db, day)
        if existing is None:
            raise
        return existing
    logger.info(
        "challenge generated: date=%s seed_attempt=%d seed_commitment=%s",
        date_iso,
        found.attempt,
        commitment,
    )
    return ch


def _void_challenge(
    db: Session, day: date, now: datetime, settings: Settings, key: bytes, reason: str
) -> Challenge:
    """生成失败：建 status='void' 的挑战（不建 master、不出回合）。承诺照常公开 seed（03 §1.1）。"""
    date_iso = day.isoformat()
    attempt = CHALLENGE_SEED_MAX_ATTEMPTS - 1
    seed = derive_seed(key, date_iso, attempt)
    salt = secrets.token_hex(16)
    commitment = make_commitment(
        date_iso=date_iso,
        events_ruleset=EVENT_RULESET_VERSION,
        clock_rules=CHALLENGE_CLOCK_RULES,
        seed=seed,
        salt_hex=salt,
    )
    if settings.CHALLENGE_SCHEDULE == "daily":
        start = slot_to_utc(day, parse_slots(settings.CHALLENGE_SLOTS)[0])
    else:
        start = from_ms(to_ms(ceil_5s(now)) + SLOT_LEAD_MS)
    ch = Challenge(
        id=uuid.uuid4(),
        challenge_date=day,
        status="void",
        schedule_mode=settings.CHALLENGE_SCHEDULE,
        format_version=CHALLENGE_FORMAT_VERSION,
        events_ruleset=EVENT_RULESET_VERSION,
        clock_rules=CHALLENGE_CLOCK_RULES,
        seed_attempt=attempt,
        market_seed=seed,
        seed_salt=salt,
        seed_commitment=commitment,
        master_save_id=None,
        start_minute=CHALLENGE_START_MINUTE,
        tick_ms=settings.CHALLENGE_TICK_MS,
        end_tt=0,
        starts_at=start,
        entry_closes_at=start,
        final_resume_at=start,
        ends_at=start,
        settle_expected_at=start,
        eligible_count=0,
        void_reason=reason,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(ch)
        db.flush()
        hooks.run_revoked(db, info_of(ch), reason)  # void：无回合，无时间线
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = challenge_for_date(db, day)
        if existing is None:
            raise
        return existing
    return ch


def void_challenge(db: Session, ch: Challenge, reason: str) -> Challenge:
    """作废挑战（CLI / 运维）：status→void，触发 RevokedHook。已结算的不可作废。"""
    if ch.status in ("settled", "void"):
        raise AppError(ErrorCode.CHALLENGE_ENDED, {"challenge_id": str(ch.id)})
    ch.status = "void"
    ch.void_reason = reason[:32]
    hooks.run_revoked(db, info_of(ch, clock.timeline_of(db, ch)), ch.void_reason)
    db.commit()
    return ch
