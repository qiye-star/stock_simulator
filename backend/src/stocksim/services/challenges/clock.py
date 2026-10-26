"""挑战公共时间线（03 §1.2）的服务层包装。

时间线由 `challenge_rounds` 行与 `challenges` 行重建（build_timeline 校验），
进程内按 (challenge.id, challenge.version) 缓存。回合与时段生成后不变，缓存无需失效。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.domain.challenge.constants import CHALLENGE_CLOSE_LEAD_MS
from stocksim.domain.challenge.timeline import (
    PhaseInfo,
    Timeline,
    build_timeline,
    reached_ms,
    target_tt,
)
from stocksim.domain.challenge.timeline import phase_at as _domain_phase_at
from stocksim.models import Challenge, ChallengeRound
from stocksim.services.challenges.timeutil import from_ms, to_ms

# 作答窗口的最小长度（毫秒）：daily 30 分钟，compact 5 秒（03 §4.3 第 3 条）
MIN_WINDOW_MS = {"daily": 30 * 60_000, "compact": 5_000}
_CACHE_LIMIT = 256
_cache: dict[tuple[uuid.UUID, int], Timeline] = {}


def timeline_of(db: Session, ch: Challenge) -> Timeline:
    key = (ch.id, ch.version)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    rounds = list(
        db.scalars(
            select(ChallengeRound)
            .where(ChallengeRound.challenge_id == ch.id)
            .order_by(ChallengeRound.round_index)
        )
    )
    if not rounds:
        raise RuntimeError(f"challenge {ch.id} has no rounds")
    timeline = build_timeline(
        hold_tts=[r.hold_tt for r in rounds],
        end_tt=ch.end_tt,
        resume_ms=[to_ms(r.resume_at) for r in rounds] + [to_ms(ch.final_resume_at)],
        tick_ms=ch.tick_ms,
        close_lead_ms=CHALLENGE_CLOSE_LEAD_MS,
        min_window_ms=MIN_WINDOW_MS[ch.schedule_mode],
    )
    if len(_cache) >= _CACHE_LIMIT:
        _cache.clear()
    _cache[key] = timeline
    return timeline


def tt_at(db: Session, ch: Challenge, now: datetime) -> int:
    """公共交易 tick tt(now)（03 §1.2）。"""
    return target_tt(timeline_of(db, ch), to_ms(now))


def reached_at(db: Session, ch: Challenge, tt: int) -> datetime:
    """公共 tt 首次到达的时刻；tt ≤ 0 返回 starts_at。"""
    return from_ms(reached_ms(timeline_of(db, ch), tt))


def phase_at(db: Session, ch: Challenge, now: datetime) -> PhaseInfo:
    return _domain_phase_at(timeline_of(db, ch), to_ms(now))


def clear_cache() -> None:
    """仅测试用。"""
    _cache.clear()
