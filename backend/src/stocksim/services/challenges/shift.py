"""调试用时间平移（03 §10.1 `POST /debug/challenges/{id}/shift`，仅 ENABLE_DEBUG_API）。

把挑战的全部时刻整体提前 seconds 秒（开局、各回合恢复/停顿/截止、终局、截止报名、结算上界），
使“现在”相对挑战快进。平移是常数位移，所有相对关系（作答窗口、时间线约束）保持不变，
公共时间线 tt(now) 随之改变。调用方随后应执行 run_due 把 master 推到新的 tt。

时间线缓存按 (challenge.id, challenge.version) 缓存（clock.py）：Challenge 带 version_id_col，
flush 时 SQLAlchemy 自增 version，缓存自动失效，这里无需手动清理。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.models import Challenge
from stocksim.services.challenges import registry


def shift_challenge(db: Session, challenge_id: uuid.UUID, seconds: int) -> Challenge:
    """整体前移挑战时刻并提交。已结算或已作废的挑战不可平移（CHALLENGE_ENDED）。"""
    ch = db.get(Challenge, challenge_id)
    if ch is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(challenge_id)})
    if ch.status in ("settled", "void"):
        raise AppError(ErrorCode.CHALLENGE_ENDED, {"challenge_id": str(challenge_id)})
    delta = timedelta(seconds=seconds)
    ch.starts_at = ch.starts_at - delta
    ch.entry_closes_at = ch.entry_closes_at - delta
    ch.final_resume_at = ch.final_resume_at - delta
    ch.ends_at = ch.ends_at - delta
    ch.settle_expected_at = ch.settle_expected_at - delta
    for rnd in registry.rounds_of(db, ch):
        rnd.resume_at = rnd.resume_at - delta
        rnd.hold_at = rnd.hold_at - delta
        rnd.closes_at = rnd.closes_at - delta
    db.commit()
    return ch


__all__ = ["shift_challenge"]
