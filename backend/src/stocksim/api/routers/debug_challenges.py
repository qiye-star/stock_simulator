"""每日挑战的调试接口（03 §10.1、§5 #10）。ENABLE_DEBUG_API=false 时一律 403 DEBUG_DISABLED。

- POST /debug/challenges/ensure：按当前 CHALLENGE_SCHEDULE 生成或返回挑战。
- POST /debug/challenges/{id}/shift：把挑战时刻整体前移，再 run_due 推进
  （已结算/作废 409 CHALLENGE_ENDED）。只平移时间，不输出 seed；e2e 用它快进。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from stocksim.api.deps import CurrentUser, DbSession, SettingsDep
from stocksim.api.routers.challenges import require_challenges_enabled
from stocksim.core.errors import AppError, ErrorCode
from stocksim.schemas.challenges import ChallengeOut, DebugChallengeEnsureIn, DebugChallengeShiftIn
from stocksim.services.challenges import generate, registry, runner, timeutil
from stocksim.services.challenges import views as challenge_views
from stocksim.services.challenges.shift import shift_challenge
from stocksim.services.challenges.timeutil import local_date


def _require_debug_enabled(settings: SettingsDep) -> None:
    if not settings.ENABLE_DEBUG_API:
        raise AppError(ErrorCode.DEBUG_DISABLED)


router = APIRouter(
    prefix="/debug/challenges",
    tags=["debug"],
    dependencies=[Depends(_require_debug_enabled), Depends(require_challenges_enabled)],
)


@router.post("/ensure", response_model=ChallengeOut)
def ensure(
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    body: DebugChallengeEnsureIn | None = None,
) -> dict:
    now = timeutil.now()
    day = body.day if body is not None and body.day is not None else local_date(now)
    ch = generate.ensure_challenge(db, day, now=now, settings=settings)
    if registry.promote_if_due(db, ch, now):
        db.commit()
    return challenge_views.challenge_out(db, ch, viewer=user.id, now=now)


@router.post("/{challenge_id:uuid}/shift", response_model=ChallengeOut)
def shift(
    challenge_id: uuid.UUID,
    body: DebugChallengeShiftIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    ch = shift_challenge(db, challenge_id, body.seconds)
    now: datetime = timeutil.now()
    session_factory = request.app.state.session_factory
    runner.run_due(session_factory, now)
    db.refresh(ch)
    return challenge_views.challenge_out(db, ch, viewer=user.id, now=now)

