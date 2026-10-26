"""挑战查询与关联（03 §7.1）：挑战行、master、报名、回合的读取，以及 D 用的 ChallengeInfo。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.constants import CHALLENGE_CLOCK_RULES
from stocksim.domain.challenge.timeline import Timeline, reached_ms, target_tt
from stocksim.domain.clock import timebase
from stocksim.domain.events.types import GameEvent
from stocksim.models import Challenge, ChallengeEntry, ChallengeRound, Save
from stocksim.models.save import SAVE_MODE_CHALLENGE, SAVE_MODE_CHALLENGE_MARKET
from stocksim.services import events as events_service
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import clock, timeutil
from stocksim.services.challenges.timeutil import from_ms, local_date, to_ms


@dataclass(frozen=True)
class ChallengeInfo:
    """D 与钩子用的挑战摘要（03 §1.7）。last_tt 为服务端专用，不外发。"""

    id: uuid.UUID
    events_ruleset: int
    first_tt: int
    last_tt: int
    status: Literal["upcoming", "live", "finished", "revoked"]
    clock_rules: int = CHALLENGE_CLOCK_RULES
    # 服务端专用（同 last_tt）：公共时间线，供 public_trading_tick / real_time_of 换算。
    # void 挑战没有回合，为 None。由 get_challenge / live_challenges / 生成钩子带入。
    timeline: Timeline | None = field(default=None, compare=False, repr=False)


_STATUS_MAP = {
    "scheduled": "upcoming",
    "running": "live",
    "settled": "finished",
    "void": "revoked",
}


def info_of(ch: Challenge, timeline: Timeline | None = None) -> ChallengeInfo:
    return ChallengeInfo(
        id=ch.id,
        events_ruleset=ch.events_ruleset,
        first_tt=1,
        last_tt=ch.end_tt,
        status=_STATUS_MAP[ch.status],  # type: ignore[arg-type]
        clock_rules=ch.clock_rules,
        timeline=timeline,
    )


def get_challenge_row(db: Session, challenge_id: uuid.UUID) -> Challenge | None:
    return db.get(Challenge, challenge_id)


def challenge_for_date(db: Session, day: date) -> Challenge | None:
    return db.scalar(select(Challenge).where(Challenge.challenge_date == day))


def current_challenge(db: Session, now: datetime) -> Challenge | None:
    """running 优先；其次今天的挑战；其次最近的 scheduled（03 §7.1）。"""
    running = db.scalar(
        select(Challenge)
        .where(Challenge.status == "running")
        .order_by(Challenge.challenge_date.desc())
        .limit(1)
    )
    if running is not None:
        return running
    today = challenge_for_date(db, local_date(now))
    if today is not None:
        return today
    return db.scalar(
        select(Challenge)
        .where(Challenge.status == "scheduled")
        .order_by(Challenge.challenge_date.desc())
        .limit(1)
    )


def promote_if_due(db: Session, ch: Challenge, now: datetime) -> bool:
    """scheduled 且 now ≥ starts_at 时条件更新为 running（懒迁移，03 §1.1）。不 commit。"""
    if ch.status != "scheduled" or now < _aware(ch.starts_at):
        return False
    result = db.execute(
        update(Challenge)
        .where(Challenge.id == ch.id, Challenge.status == "scheduled")
        .values(status="running", version=Challenge.version + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.refresh(ch)
    return (result.rowcount or 0) == 1


def market_save_for(db: Session, ch: Challenge) -> Save:
    """挑战的 master 存档（mode=challenge_market，无主人）。"""
    master = db.get(Save, ch.master_save_id) if ch.master_save_id is not None else None
    if master is None or master.mode != SAVE_MODE_CHALLENGE_MARKET:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(ch.id)})
    return master


def challenge_of_save(db: Session, save: Save) -> Challenge:
    """挑战玩家存档 → 所属挑战（经 market_source_id 指向的 master）。"""
    if save.mode != SAVE_MODE_CHALLENGE or save.market_source_id is None:
        raise RuntimeError(f"save {save.id} is not a challenge entry save")
    ch = db.scalar(select(Challenge).where(Challenge.master_save_id == save.market_source_id))
    if ch is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"save_id": str(save.id)})
    return ch


def entry_for(db: Session, ch: Challenge, user_id: uuid.UUID) -> ChallengeEntry | None:
    return db.scalar(
        select(ChallengeEntry).where(
            ChallengeEntry.challenge_id == ch.id, ChallengeEntry.user_id == user_id
        )
    )


def rounds_of(db: Session, ch: Challenge) -> list[ChallengeRound]:
    return list(
        db.scalars(
            select(ChallengeRound)
            .where(ChallengeRound.challenge_id == ch.id)
            .order_by(ChallengeRound.round_index)
        )
    )


def round_by_index(db: Session, ch: Challenge, round_index: int) -> ChallengeRound | None:
    return db.scalar(
        select(ChallengeRound).where(
            ChallengeRound.challenge_id == ch.id, ChallengeRound.round_index == round_index
        )
    )


def visible_rounds(db: Session, ch: Challenge, now: datetime) -> list[ChallengeRound]:
    """已到停顿时刻（hold_at ≤ now）的回合；未到的回合对玩家不存在（03 §5 #8）。"""
    return [r for r in rounds_of(db, ch) if _aware(r.hold_at) <= now]


# ---------------------------------------------------------------- 03 §1.7：给 D（04）的契约函数


def _row(db: Session, ch: Challenge | ChallengeInfo) -> Challenge:
    row = db.get(Challenge, ch.id)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(ch.id)})
    return row


def _info_of_row(db: Session, row: Challenge) -> ChallengeInfo:
    timeline = None if row.status == "void" else clock.timeline_of(db, row)
    return info_of(row, timeline)


def _timeline(ch: ChallengeInfo) -> Timeline:
    if ch.timeline is None:
        raise ValueError("challenge has no public timeline (revoked)")
    return ch.timeline


def _advance_master(db: Session, row: Challenge, now: datetime) -> None:
    """读取 master 行情前把它推到 tt(now)（03 §7.3）。会 commit（与懒推进一致）。"""
    if row.status == "void":
        return
    from stocksim.services.challenges import sync  # 延迟导入：sync 顶层导入本模块

    sync.advance_master(db, row, now)


def get_challenge(db: Session, challenge_id: uuid.UUID) -> ChallengeInfo | None:
    """挑战摘要（服务端专用字段含 last_tt / timeline）。scheduled 且已到点的懒迁移为 running。"""
    row = db.get(Challenge, challenge_id)
    if row is None:
        return None
    if promote_if_due(db, row, timeutil.now()):
        db.commit()
    return _info_of_row(db, row)


def live_challenges(db: Session, now: datetime) -> list[ChallengeInfo]:
    """running 与结算不足 24 h 的 settled 挑战（D 的 sweeper 用）。到点的 scheduled 先懒迁移。"""
    promoted = False
    for row in db.scalars(select(Challenge).where(Challenge.status == "scheduled")):
        promoted = promote_if_due(db, row, now) or promoted
    if promoted:
        db.commit()
    cutoff = now - timedelta(hours=24)
    rows = db.scalars(
        select(Challenge)
        .where(
            (Challenge.status == "running")
            | ((Challenge.status == "settled") & (Challenge.settled_at >= cutoff))
        )
        .order_by(Challenge.challenge_date)
    ).all()
    return [_info_of_row(db, row) for row in rows]


def round_event_ids(db: Session, ch: Challenge | ChallengeInfo) -> list[str]:
    """N 个回合事件的 event_id，按回合序。服务端专用：未到停顿前不得外发。"""
    return [r.event_id for r in rounds_of(db, _row(db, ch))]


def public_trading_tick(ch: ChallengeInfo, now: datetime) -> int:
    """公共交易 tick tt(now)（03 §1.2）。单调不减，值域 [0, last_tt]。只依赖 ch.timeline。"""
    return target_tt(_timeline(ch), to_ms(now))


def real_time_of(ch: ChallengeInfo, trading_tick: int) -> datetime:
    """公共 tt 首次到达的时刻；tt ≤ 0 返回 starts_at。tt 超过 end_tt 抛 ValueError。"""
    tl = _timeline(ch)
    if trading_tick <= 0:
        return from_ms(tl.resume_ms[0])
    return from_ms(reached_ms(tl, trading_tick))


def challenge_events(
    db: Session,
    ch: Challenge | ChallengeInfo,
    from_day: int,
    to_day: int,
    *,
    include_unpublished: bool = False,
) -> list[GameEvent]:
    """排期日 [from_day, to_day] 的服务端完整事件（经 master 调 A）。
    结果绝不能原样外发；默认只含 publish ≤ 当前公共 tt 的事件。"""
    row = _row(db, ch)
    _advance_master(db, row, timeutil.now())
    master = market_save_for(db, row)
    return list(
        events_service.events_for_days(
            db, master, from_day, to_day, include_unpublished=include_unpublished
        )
    )


def public_event(
    db: Session, ch: Challenge | ChallengeInfo, event_id: str, lang: str, at_tt: int
) -> dict[str, Any] | None:
    """事件的公开形态（A 的 EventOut，按 A §1.8 过滤）。at_tt 超过当前公共 tt 抛 ValueError。"""
    row = _row(db, ch)
    now = timeutil.now()
    info = _info_of_row(db, row)
    if at_tt < 0 or at_tt > public_trading_tick(info, now):
        raise ValueError("at_tt must be within [0, current public trading tick]")
    _advance_master(db, row, now)
    master = market_save_for(db, row)
    return events_service.event_out(db, master, event_id, lang, at_tt=at_tt)


def reference_change_bp(
    db: Session,
    ch: Challenge | ChallengeInfo,
    scope: Literal["industry", "stock", "market"],
    subject: str | None,
    from_day: int,
    upto_tt: int,
) -> int | None:
    """参考涨跌幅（03 §1.7 口径）：from_day−1 收盘 → 终点收盘。

    upto_tt 为换日 tick（rolls_at）时取 day_of(upto_tt)−1 的收盘；否则必须等于当前公共 tt，取现价。
    upto_tt 超过当前公共 tt，或中间 tick 不等于当前公共 tt，抛 ValueError。
    口径只调 B 的 change_bp_for。
    """
    row = _row(db, ch)
    now = timeutil.now()
    info = _info_of_row(db, row)
    cur = public_trading_tick(info, now)
    if upto_tt > cur:
        raise ValueError("upto_tt is beyond the current public trading tick")
    tb = timebase(row.clock_rules)
    if tb.rolls_at(upto_tt):
        to_day = tb.day_of(upto_tt) - 1
    elif upto_tt == cur:
        to_day = tb.day_of(upto_tt)
    else:
        raise ValueError("upto_tt must be a day-roll tick or the current public trading tick")
    _advance_master(db, row, now)
    master = market_save_for(db, row)
    return predictions_service.change_bp_for(
        db,
        master,
        target_kind=scope,
        target=subject,
        from_day=from_day,
        to_day=to_day,
    )


def knowledge_trading_tick(
    db: Session, user_id: uuid.UUID, ch: Challenge | ChallengeInfo
) -> int | None:
    """用户对该挑战的“已知 tick”：有报名返回当前公共 tt，否则 None。永不超前。"""
    row = _row(db, ch)
    if entry_for(db, row, user_id) is None:
        return None
    return public_trading_tick(_info_of_row(db, row), timeutil.now())


def expected_participants(db: Session, ch: Challenge | ChallengeInfo) -> int:
    """预计人数 = max(本场报名数, 上一场报名数)。上一场指日期更早的最近一场（不含作废）。"""
    row = _row(db, ch)
    own = _entry_count(db, row.id)
    prev_id = db.scalar(
        select(Challenge.id)
        .where(Challenge.challenge_date < row.challenge_date, Challenge.status != "void")
        .order_by(Challenge.challenge_date.desc())
        .limit(1)
    )
    prev = _entry_count(db, prev_id) if prev_id is not None else 0
    return max(own, prev)


def _entry_count(db: Session, challenge_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(ChallengeEntry.id)).where(ChallengeEntry.challenge_id == challenge_id)
        )
        or 0
    )


def _aware(value: datetime) -> datetime:
    """SQLite 读回的 datetime 可能无时区；统一按 UTC 解释。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "ChallengeInfo",
    "challenge_events",
    "challenge_for_date",
    "challenge_of_save",
    "current_challenge",
    "entry_for",
    "expected_participants",
    "get_challenge",
    "get_challenge_row",
    "info_of",
    "knowledge_trading_tick",
    "live_challenges",
    "market_save_for",
    "promote_if_due",
    "public_event",
    "public_trading_tick",
    "real_time_of",
    "reference_change_bp",
    "round_by_index",
    "round_event_ids",
    "rounds_of",
    "visible_rounds",
]
