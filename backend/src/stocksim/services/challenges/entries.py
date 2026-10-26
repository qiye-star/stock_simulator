"""报名（03 §7.4）：每人每挑战一份玩家挑战存档。不计入 MAX_SAVES_PER_USER，不建行情。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.constants import (
    CHALLENGE_BUY_FEE_RATE,
    CHALLENGE_CLOCK_RULES,
    CHALLENGE_INITIAL_FUND_CENTS,
    CHALLENGE_SELL_FEE_RATE,
    CHALLENGE_TRADE_UNIT,
)
from stocksim.models import Challenge, ChallengeEntry, Save, SaveStats, User
from stocksim.models.save import SAVE_MODE_CHALLENGE
from stocksim.services import market as market_service
from stocksim.services.challenges import clock, registry, sync
from stocksim.services.challenges.config import current_settings


def join(db: Session, ch: Challenge, user: User, now: datetime) -> tuple[ChallengeEntry, bool]:
    """报名。返回 (报名行, 是否新建)。已报名则直接返回已有行（幂等，HTTP 200）。

    条件：status=='running' 且 now < entry_closes_at；否则 NOT_STARTED（未开始）或 ENTRY_CLOSED。
    """
    existing = registry.entry_for(db, ch, user.id)
    if existing is not None:
        return existing, False
    registry.promote_if_due(db, ch, now)
    if ch.status == "scheduled":
        raise AppError(ErrorCode.CHALLENGE_NOT_STARTED, {"starts_at": _iso(ch.starts_at)})
    if ch.status == "settled" or (
        ch.status == "running" and clock.phase_at(db, ch, now).phase == "ended"
    ):
        raise AppError(ErrorCode.CHALLENGE_ENDED, {"challenge_id": str(ch.id)})
    if ch.status != "running" or now >= _aware(ch.entry_closes_at):
        raise AppError(
            ErrorCode.CHALLENGE_ENTRY_CLOSED, {"entry_closes_at": _iso(ch.entry_closes_at)}
        )
    sync.advance_master(db, ch, now)  # 迟到者从当时的行情开始：先把 master 推到 tt(now)
    master = registry.market_save_for(db, ch)
    phase = clock.phase_at(db, ch, now).phase
    settings = current_settings()
    eligible = _aware(user.created_at) <= _aware(ch.starts_at) - timedelta(
        hours=settings.CHALLENGE_MIN_ACCOUNT_AGE_HOURS
    )
    save = Save(
        id=uuid.uuid4(),
        user_id=user.id,
        name=f"每日挑战 {ch.challenge_date.strftime('%m-%d')}",
        mode=SAVE_MODE_CHALLENGE,
        market_source_id=master.id,
        initial_fund_cents=CHALLENGE_INITIAL_FUND_CENTS,
        cash_cents=CHALLENGE_INITIAL_FUND_CENTS,
        buy_fee_rate=CHALLENGE_BUY_FEE_RATE,
        sell_fee_rate=CHALLENGE_SELL_FEE_RATE,
        t0_mode=False,
        trade_unit=CHALLENGE_TRADE_UNIT,
        market_seed=master.market_seed,
        tick=master.tick,
        trade_seq=0,
        trading_day=master.trading_day,
        clock_minute=master.clock_minute,
        clock_rules=CHALLENGE_CLOCK_RULES,
        paused=phase not in sync.RUNNING_PHASES,
        last_tick_at=None,
        events_enabled=True,
        events_ruleset=ch.events_ruleset,
        auto_enabled=False,
        auto_paused=False,
        auto_max_total_trades=100,
        created_at=now,
        updated_at=now,
    )
    entry = ChallengeEntry(
        id=uuid.uuid4(),
        challenge_id=ch.id,
        user_id=user.id,
        save_id=save.id,
        eligible=eligible,
        joined_at=now,
        joined_tt=market_service.current_trading_tick(db, master),
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(save)
        db.flush()
        db.add(SaveStats(save_id=save.id))
        db.add(entry)
        db.commit()
    except IntegrityError:
        # 同一用户并发报名（唯一键 challenge_id+user_id）：回滚后返回先到的那份
        db.rollback()
        winner = registry.entry_for(db, ch, user.id)
        if winner is None:
            raise
        return winner, False
    return entry, True


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return _aware(value).astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = ["join"]
