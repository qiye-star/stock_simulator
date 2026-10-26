"""复盘会话：建会话、推进、作答、结束与结算（05 §1.2–1.6、§5.5）。

推进与结算在同一事务内完成（services.tx.run_in_transaction，冲突时整体重算）。
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.clock import CLOCK_RULES_V1
from stocksim.domain.replay import PHASE_MINUTE, next_position, phase_tick
from stocksim.domain.replay import return_bp as bp_return
from stocksim.models import (
    ReplayLevel,
    ReplayLevelVersion,
    ReplayPrediction,
    ReplaySession,
    Save,
    SaveStats,
    User,
)
from stocksim.models.save import SAVE_MODE_REPLAY
from stocksim.services import equity as equity_service
from stocksim.services import saves as saves_service
from stocksim.services.replay import levels, predictions, views
from stocksim.services.replay.feed import feed_page, to_feed_item, visible_at
from stocksim.services.replay.pack import PackQuestion
from stocksim.services.replay.state import (
    Ctx,
    build_state,
    date_iso,
    date_label,
    load_ctx,
)
from stocksim.services.tx import run_in_transaction

INITIAL_FUND_CENTS = 100_000_000  # 100 万元（05 §1.2）
BUY_FEE_RATE = Decimal("0.0003")  # 与 SaveCreateIn 默认费率一致（05 §1.2 用默认值）
SELL_FEE_RATE = Decimal("0.0013")
TRADE_UNIT = 100


# ---------- 归属与会话视图 ----------


def load_session_save(db: Session, user: User, save_id: uuid.UUID) -> Save:
    """归属校验 + 必须是复盘存档（否则 SAVE_NOT_FOUND，05 §8.2 第 10 点）。"""
    save = saves_service.load_owned_save(db, user, save_id)
    if save.mode != SAVE_MODE_REPLAY:
        raise AppError(ErrorCode.SAVE_NOT_FOUND, {"save_id": str(save_id)})
    return save


def _level_and_version(
    db: Session, session: ReplaySession
) -> tuple[ReplayLevel, ReplayLevelVersion]:
    version = db.get(ReplayLevelVersion, session.level_version_id)
    level = db.get(ReplayLevel, version.level_id)
    return level, version


def _settled_out(session: ReplaySession) -> dict[str, Any] | None:
    if session.status != "settled":
        return None
    return {
        "final_equity_cents": session.final_equity_cents,
        "return_bp": session.return_bp,
        "benchmark_return_bp": session.benchmark_return_bp,
        "excess_bp": session.excess_bp,
        "points_total": session.points_total,
    }


def session_view(db: Session, save: Save) -> dict[str, Any]:
    """ReplaySessionOut。"""
    ctx = load_ctx(db, save)
    session = ctx.session
    level, version = _level_and_version(db, session)
    state = build_state(ctx, int(save.tick))
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    qty = equity_service.holding_quantities(db, save.id)
    market_value = sum(q * prices.get(code, 0) for code, q in qty.items())
    settled = ctx.settled
    answers = predictions.answers_by_question(db, save.id)
    pos_tick = phase_tick(ctx.day, ctx.phase)
    pending: list[str] = []
    open_ids: list[str] = []
    if not settled:
        pending = predictions.pending_at(ctx, answers, ctx.day, ctx.phase)
        open_ids = [
            q.id
            for q in ctx.pack.questions
            if predictions.question_opened(q, ctx.day, ctx.phase)
            and phase_tick(q.closes.day, q.closes.phase) >= pos_tick
        ]
    return {
        "save_id": save.id,
        "name": save.name,
        "level": {
            "slug": level.slug,
            "version": version.version,
            "title": level.title_masked if ctx.masked else level.title,
        },
        "masked": ctx.masked,
        "status": session.status,
        "day_idx": ctx.day,
        "play_days": ctx.pack.play_days,
        "phase": ctx.phase,
        "tick": int(save.tick),
        "date": date_iso(ctx, ctx.day),
        "date_label": date_label(ctx, ctx.day),
        "cash_cents": int(save.cash_cents),
        "initial_fund_cents": int(save.initial_fund_cents),
        "equity_cents": int(save.cash_cents) + market_value,
        "pending_question_ids": pending,
        "open_question_ids": open_ids,
        "settled": _settled_out(session),
        "created_at": save.created_at,
    }


def get_session(db: Session, user: User, save_id: uuid.UUID) -> dict[str, Any]:
    return session_view(db, load_session_save(db, user, save_id))


def list_sessions(db: Session, user: User) -> list[dict[str, Any]]:
    saves = db.scalars(
        select(Save)
        .join(ReplaySession, ReplaySession.save_id == Save.id)
        .where(ReplaySession.user_id == user.id)
        .order_by(Save.created_at.desc())
    ).all()
    return [session_view(db, s) for s in saves]


# ---------- 建会话 ----------


def create_session(
    db: Session,
    user: User,
    *,
    level_slug: str,
    masked: bool,
    name: str,
    limit: int,
) -> Save:
    level = levels.get_published(db, level_slug)
    if masked and not level.masked_allowed:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "masked"})
    count = db.scalar(
        select(func.count()).select_from(ReplaySession).where(ReplaySession.user_id == user.id)
    )
    if (count or 0) >= limit:
        raise AppError(ErrorCode.SAVE_LIMIT_REACHED, {"limit": limit, "mode": "replay"})
    version = levels.current_version(db, level)
    prior = db.scalar(
        select(func.count())
        .select_from(ReplaySession)
        .join(ReplayLevelVersion, ReplaySession.level_version_id == ReplayLevelVersion.id)
        .where(ReplaySession.user_id == user.id, ReplayLevelVersion.level_id == level.id)
    )
    now = utcnow()
    save = Save(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name[:20],
        mode=SAVE_MODE_REPLAY,
        initial_fund_cents=INITIAL_FUND_CENTS,
        cash_cents=INITIAL_FUND_CENTS,
        buy_fee_rate=BUY_FEE_RATE.quantize(Decimal("0.000001")),
        sell_fee_rate=SELL_FEE_RATE.quantize(Decimal("0.000001")),
        t0_mode=False,
        trade_unit=TRADE_UNIT,
        market_seed=0,
        events_enabled=False,
        events_ruleset=0,
        clock_rules=CLOCK_RULES_V1,
        tick=0,
        trade_seq=0,
        trading_day=0,
        clock_minute=PHASE_MINUTE["pre_open"],
        paused=True,
        last_tick_at=None,
        auto_enabled=False,
        auto_paused=False,
        auto_max_total_trades=100,
        created_at=now,
        updated_at=now,
    )
    db.add(save)
    db.flush()
    db.add(SaveStats(save_id=save.id))
    db.add(
        ReplaySession(
            save_id=save.id,
            user_id=user.id,
            level_version_id=version.id,
            masked=masked,
            status="active",
            is_first_attempt=(prior or 0) == 0,
            points_total=0,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return save


# ---------- 推进 ----------


def _snapshot_close(db: Session, save: Save, ctx: Ctx, next_tick: int) -> None:
    """离开收盘阶段时写当日权益快照（以收盘价估值，幂等覆盖）。"""
    state = build_state(ctx, int(save.tick))
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    qty = equity_service.holding_quantities(db, save.id)
    market_value = sum(q * prices.get(code, 0) for code, q in qty.items())
    equity_service.upsert_snapshot(db, save, ctx.day, int(save.cash_cents), market_value, next_tick)


def _skip(
    db: Session,
    save: Save,
    answers: dict[str, ReplayPrediction],
    qid: str,
    now: datetime,
) -> None:
    row = answers.get(qid)
    if row is None:
        row = ReplayPrediction(save_id=save.id, question_id=qid, submitted_tick=int(save.tick))
        db.add(row)
        answers[qid] = row
    row.answer = None
    row.skipped = True
    row.score = 0
    row.points = 0
    row.scored_at = now


def _settle(
    db: Session,
    save: Save,
    ctx: Ctx,
    answers: dict[str, ReplayPrediction],
    *,
    user_id: uuid.UUID,
    level_id: uuid.UUID,
    now: datetime,
) -> list[str]:
    """结算：剩余题计分（未答记 0 分）、按最后可见价估值、写结算指标。调用方负责提交。"""
    session = ctx.session
    scored = predictions.score_due(
        db,
        save,
        ctx,
        answers,
        user_id=user_id,
        level_id=level_id,
        upto_day=None,
        upto_phase=None,
        now=now,
    )
    state = build_state(ctx, int(save.tick))
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    qty = equity_service.holding_quantities(db, save.id)
    market_value = sum(q * prices.get(code, 0) for code, q in qty.items())
    final_equity = int(save.cash_cents) + market_value
    initial = int(save.initial_fund_cents)
    ret = bp_return(initial, final_equity)
    end_day = views.visible_close_day(ctx)
    bench = bp_return(views.benchmark_close(ctx, -1), views.benchmark_close(ctx, end_day))

    session.status = "settled"
    session.settled_at = now
    session.final_equity_cents = final_equity
    session.return_bp = ret
    session.benchmark_return_bp = bench
    session.excess_bp = ret - bench
    save.clock_minute = PHASE_MINUTE["post_close"]
    save.trading_day = ctx.pack.play_days - 1
    save.tick = ctx.pack.play_days * 4
    db.flush()
    return scored


def _advance_once(
    db: Session,
    user: User,
    save: Save,
    *,
    to: str,
    expected_tick: int,
    skip_pending: bool,
) -> dict[str, Any]:
    session = db.get(ReplaySession, save.id)
    if session is None or session.status == "settled":
        raise AppError(ErrorCode.REPLAY_SESSION_SETTLED, {"save_id": str(save.id)})
    if expected_tick != save.tick:
        return {"stale": True, "stopped_reason": None, "feed": [], "scored": []}

    base = load_ctx(db, save)
    level_id = _level_and_version(db, session)[0].id
    answers = predictions.answers_by_question(db, save.id)
    now = utcnow()
    play = base.pack.play_days
    day, phase = base.day, base.phase
    feed: list[dict[str, Any]] = []
    scored: list[str] = []
    stopped: str | None = None

    while True:
        ctx = replace(base, day=day, phase=phase)
        pending = predictions.pending_at(ctx, answers, day, phase)
        if pending:
            if skip_pending:
                for qid in pending:
                    _skip(db, save, answers, qid, now)
                scored.extend(pending)
            elif to == "next_day":
                stopped = "question_due"
                break
            else:
                raise AppError(ErrorCode.REPLAY_PREDICTION_PENDING, {"question_ids": pending})

        nxt = next_position(day, phase, play)
        if nxt is None:
            scored.extend(
                _settle(db, save, ctx, answers, user_id=user.id, level_id=level_id, now=now)
            )
            stopped = "settled"
            break

        nday, nphase = nxt
        if phase == "close":
            _snapshot_close(db, save, ctx, phase_tick(nday, nphase))
        before = {i for i, _ in visible_at(base.pack, masked=base.masked, day=day, phase=phase)}
        day, phase = nday, nphase
        save.trading_day = day
        save.clock_minute = PHASE_MINUTE[phase]
        save.tick = phase_tick(day, phase)
        new_ctx = replace(base, day=day, phase=phase)
        for i, ev in visible_at(base.pack, masked=base.masked, day=day, phase=phase):
            if i not in before:
                feed.append(to_feed_item(ev, new_ctx))
        scored.extend(
            predictions.score_due(
                db,
                save,
                new_ctx,
                answers,
                user_id=user.id,
                level_id=level_id,
                upto_day=day,
                upto_phase=phase,
                now=now,
            )
        )

        if to == "next_phase":
            break
        if any((q.opens.day, q.opens.phase) == (day, phase) for q in base.pack.questions):
            stopped = "question_open"
            break
        if phase == "pre_open":
            break

    db.flush()
    return {"stale": False, "stopped_reason": stopped, "feed": feed, "scored": scored}


def advance(
    db: Session,
    user: User,
    save_id: uuid.UUID,
    *,
    to: str,
    expected_tick: int,
    skip_pending: bool,
) -> dict[str, Any]:
    """POST /replay/sessions/{id}/advance。返回 AdvanceOut 的字段（session 为推进后的视图）。"""
    save = load_session_save(db, user, save_id)
    result = run_in_transaction(
        db,
        lambda: _advance_once(
            db, user, save, to=to, expected_tick=expected_tick, skip_pending=skip_pending
        ),
        refresh=[save],
    )
    return {
        "session": session_view(db, save),
        "stale": result["stale"],
        "stopped_reason": result["stopped_reason"],
        "new_feed_items": result["feed"],
        "scored_question_ids": result["scored"],
    }


def finish(db: Session, user: User, save_id: uuid.UUID) -> dict[str, Any]:
    """POST /replay/sessions/{id}/finish：提前结束并结算。"""
    save = load_session_save(db, user, save_id)

    def act() -> None:
        session = db.get(ReplaySession, save.id)
        if session is None or session.status == "settled":
            raise AppError(ErrorCode.REPLAY_SESSION_SETTLED, {"save_id": str(save.id)})
        ctx = load_ctx(db, save)
        level_id = _level_and_version(db, session)[0].id
        answers = predictions.answers_by_question(db, save.id)
        _settle(db, save, ctx, answers, user_id=user.id, level_id=level_id, now=utcnow())

    run_in_transaction(db, act, refresh=[save])
    return session_view(db, save)


# ---------- 作答 ----------


def answer(
    db: Session,
    user: User,
    save_id: uuid.UUID,
    question_id: str,
    *,
    probs: list[int] | None,
    order: list[str] | None,
) -> dict[str, Any]:
    """PUT .../questions/{qid}/answer：截止前可反复覆盖。返回 ReplayQuestionOut。"""
    save = load_session_save(db, user, save_id)

    def act() -> None:
        session = db.get(ReplaySession, save.id)
        if session is None or session.status == "settled":
            raise AppError(ErrorCode.REPLAY_SESSION_SETTLED, {"save_id": str(save.id)})
        ctx = load_ctx(db, save)
        q = _question(ctx, question_id)
        predictions.check_position_for_answer(ctx, q)
        payload = predictions.build_answer(ctx, q, probs, order)
        answers = predictions.answers_by_question(db, save.id)
        row = answers.get(question_id)
        if row is None:
            row = ReplayPrediction(save_id=save.id, question_id=question_id)
            db.add(row)
        row.answer = payload
        row.skipped = False
        row.submitted_tick = int(save.tick)

    run_in_transaction(db, act, refresh=[save])
    ctx = load_ctx(db, save)
    q = _question(ctx, question_id)
    row = predictions.answers_by_question(db, save.id).get(question_id)
    return predictions.question_out(ctx, q, row)


def _question(ctx: Ctx, question_id: str) -> PackQuestion:
    for q in ctx.pack.questions:
        if q.id == question_id:
            return q
    raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "question_id"})


def list_questions(db: Session, user: User, save_id: uuid.UUID) -> dict[str, Any]:
    """只含已开放的题（05 §5.8）。"""
    save = load_session_save(db, user, save_id)
    ctx = load_ctx(db, save)
    answers = predictions.answers_by_question(db, save.id)
    items = [
        predictions.question_out(ctx, q, answers.get(q.id))
        for q in ctx.pack.questions
        if predictions.question_opened(q, ctx.day, ctx.phase)
    ]
    return {"items": items}


def feed(
    db: Session, user: User, save_id: uuid.UUID, *, cursor: str | None, limit: int
) -> dict[str, Any]:
    save = load_session_save(db, user, save_id)
    ctx = load_ctx(db, save)
    if cursor is not None and not cursor.isdigit():
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
    items, next_cursor = feed_page(
        ctx, cursor=int(cursor) if cursor is not None else None, limit=limit
    )
    return {"items": items, "next_cursor": next_cursor}


def benchmark(db: Session, user: User, save_id: uuid.UUID) -> dict[str, Any]:
    save = load_session_save(db, user, save_id)
    return views.benchmark(load_ctx(db, save))


__all__ = [
    "INITIAL_FUND_CENTS",
    "advance",
    "answer",
    "benchmark",
    "create_session",
    "feed",
    "finish",
    "get_session",
    "list_questions",
    "list_sessions",
    "load_session_save",
    "session_view",
]
