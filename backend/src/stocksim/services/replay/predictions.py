"""复盘题的作答、展示与计分（05 §1.5、§5.6）。

- 计分只调用 `domain.scoring`（rps_score、ndcg_at_k_score、bucket_of）；
- 积分只走 `services.points.credit`，幂等键 `replay:{user}:{level}:{qid}`
  （按关卡而非版本，重开或升版本都不能刷分）；
- 只有该用户对该关卡的首个会话入账；匿名 ×1.0、实名 ×0.5（Q1 建议值）。
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.errors import DomainError
from stocksim.domain.money import round_half_up_div
from stocksim.domain.replay import phase_tick
from stocksim.domain.scoring import bucket_of, ndcg_at_k_score, rps_score, validate_probs
from stocksim.models import ReplayPrediction, Save
from stocksim.services import points as points_service
from stocksim.services.replay.pack import PackQuestion
from stocksim.services.replay.state import Ctx, code_of_key, key_of_code, stock_view


def answers_by_question(db: Session, save_id: uuid.UUID) -> dict[str, ReplayPrediction]:
    rows = db.scalars(select(ReplayPrediction).where(ReplayPrediction.save_id == save_id))
    return {row.question_id: row for row in rows}


def is_answered(row: ReplayPrediction | None) -> bool:
    return row is not None and row.answer is not None and not row.skipped


def is_scored(row: ReplayPrediction | None) -> bool:
    return row is not None and row.score is not None


def question_opened(q: PackQuestion, day: int, phase: str) -> bool:
    return phase_tick(q.opens.day, q.opens.phase) <= phase_tick(day, phase)


def question_closes_at(q: PackQuestion, day: int, phase: str) -> bool:
    return (q.closes.day, q.closes.phase) == (day, phase)


def pending_at(
    ctx: Ctx, answers: Mapping[str, ReplayPrediction], day: int, phase: str
) -> list[str]:
    """位置 (day, phase) 截止且未答的题（推进离开该位置前必须处理）。"""
    return [
        q.id
        for q in ctx.pack.questions
        if question_closes_at(q, day, phase) and not is_answered(answers.get(q.id))
    ]


def _pct(bp: int) -> str:
    return f"{bp / 100:.1f}%"


def bucket_labels(edges_bp: list[int]) -> list[dict[str, Any]]:
    """直接方向题的档位（左闭右开，与 bucket_of 一致）。"""
    out: list[dict[str, Any]] = [
        {"label": f"<{_pct(edges_bp[0])}", "lo_bp": None, "hi_bp": edges_bp[0]}
    ]
    for lo, hi in itertools.pairwise(edges_bp):
        out.append({"label": f"{_pct(lo)} ~ {_pct(hi)}", "lo_bp": lo, "hi_bp": hi})
    out.append({"label": f">={_pct(edges_bp[-1])}", "lo_bp": edges_bp[-1], "hi_bp": None})
    return out


def _status(q: PackQuestion, row: ReplayPrediction | None, pos_tick: int) -> str:
    if is_scored(row):
        return "skipped" if row.skipped else "scored"
    if is_answered(row):
        return "answered"
    if pos_tick > phase_tick(q.closes.day, q.closes.phase):
        return "closed"
    return "open"


def question_out(
    ctx: Ctx,
    q: PackQuestion,
    row: ReplayPrediction | None,
    *,
    reveal: bool = False,
) -> dict[str, Any]:
    """ReplayQuestionOut。答案只在计分后以 result 给出；reveal=True 时揭示真实代码与名称。"""
    masked = ctx.masked and not reveal
    pos_tick = phase_tick(ctx.day, ctx.phase)

    def code_of(key: str) -> tuple[str, str]:
        return stock_view(ctx.pack.stock(key), masked)

    if q.kind == "direction_bucket":
        assert q.stock_key is not None and q.edges_bp is not None
        code, name = code_of(q.stock_key)
        codes = [code]
        template = q.prompt_masked if masked else q.prompt
        prompt = template.replace("{name}", name)
        buckets = bucket_labels(q.edges_bp)
        top_k = None
    else:
        keys = q.stock_keys or []
        codes = [code_of(k)[0] for k in keys]
        prompt = q.prompt_masked if masked else q.prompt
        buckets = None
        top_k = q.top_k

    my_answer: dict[str, Any] | None = None
    if is_answered(row):
        my_answer = dict(row.answer or {})

    result: dict[str, Any] | None = None
    if is_scored(row) or reveal:
        result = {
            "score": int(row.score or 0) if row else 0,
            "points": int(row.points or 0) if row else 0,
        }
        if q.kind == "direction_bucket":
            ret = int(q.answer["return_bp"])
            result["return_bp"] = ret
            result["outcome_bucket"] = bucket_of(ret, q.edges_bp or [])
        else:
            returns = {code_of(k)[0]: int(v) for k, v in q.answer.get("returns_bp", {}).items()}
            result["returns_bp"] = returns
            ranked = sorted(returns.items(), key=lambda kv: (-kv[1], kv[0]))
            result["true_top"] = [c for c, _ in ranked[: q.top_k or 0]]

    return {
        "id": q.id,
        "kind": q.kind,
        "prompt": prompt,
        "codes": codes,
        "buckets": buckets,
        "top_k": top_k,
        "opens": {"day_idx": q.opens.day, "phase": q.opens.phase},
        "closes": {"day_idx": q.closes.day, "phase": q.closes.phase},
        "resolves": {"day_idx": q.resolves.day, "phase": q.resolves.phase},
        "status": _status(q, row, pos_tick),
        "my_answer": my_answer,
        "result": result,
    }


def _check_probs(probs: list[int] | None, k: int) -> list[int]:
    if probs is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "probs"})
    try:
        validate_probs(probs, k)
    except DomainError as exc:
        raise AppError(ErrorCode(exc.code), exc.params) from exc
    return list(probs)


def _check_order(order: list[str] | None, q: PackQuestion, ctx: Ctx) -> list[str]:
    candidates = [code_of_key(ctx, k) for k in (q.stock_keys or [])]
    if order is None or len(order) != q.top_k:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "order"})
    if len(set(order)) != len(order) or any(c not in candidates for c in order):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "order"})
    return list(order)


def check_position_for_answer(ctx: Ctx, q: PackQuestion) -> None:
    """作答窗口：opens ≤ 当前 ≤ closes。未开放或已截止给 REPLAY_QUESTION_CLOSED。"""
    pos_tick = phase_tick(ctx.day, ctx.phase)
    if pos_tick < phase_tick(q.opens.day, q.opens.phase):
        raise AppError(ErrorCode.REPLAY_QUESTION_CLOSED, {"question_id": q.id, "state": "not_open"})
    if pos_tick > phase_tick(q.closes.day, q.closes.phase):
        raise AppError(ErrorCode.REPLAY_QUESTION_CLOSED, {"question_id": q.id, "state": "closed"})


def build_answer(
    ctx: Ctx, q: PackQuestion, probs: list[int] | None, order: list[str] | None
) -> dict[str, Any]:
    """校验并规范化作答（代码为本会话可见代码）。"""
    if q.kind == "direction_bucket":
        if order is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "order"})
        k = len(q.edges_bp or []) + 1
        return {"probs": _check_probs(probs, k)}
    if probs is not None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "probs"})
    return {"order": _check_order(order, q, ctx)}


def points_for(score: int, masked: bool) -> int:
    """积分换算：匿名 ×1.0，实名 ×0.5（05 Q1，建议值）。"""
    return round_half_up_div(score * (100 if masked else 50), 100)


def score_question(ctx: Ctx, q: PackQuestion, row: ReplayPrediction | None) -> int:
    """0–100。无作答或跳过记 0 分。"""
    if row is None or row.answer is None or row.skipped:
        return 0
    if q.kind == "direction_bucket":
        outcome = bucket_of(int(q.answer["return_bp"]), q.edges_bp or [])
        return rps_score(list(row.answer["probs"]), outcome)
    order_keys = [key_of_code(ctx, c) for c in row.answer["order"]]
    relevance = {k: int(v) for k, v in q.answer.get("relevance", {}).items()}
    return ndcg_at_k_score([k for k in order_keys if k], relevance, k=int(q.top_k or 3))


def score_due(
    db: Session,
    save: Save,
    ctx: Ctx,
    answers: dict[str, ReplayPrediction],
    *,
    user_id: uuid.UUID,
    level_id: uuid.UUID,
    upto_day: int | None,
    upto_phase: str | None,
    now: datetime | None = None,
) -> list[str]:
    """对 resolves ≤ 给定位置（或全部，upto=None）且未计分的题计分并入账。返回新计分的题 ID。

    积分入账走 services.points（幂等）；非首次会话只记录分数，积分为 0。调用方负责提交。
    """
    now = now or utcnow()
    upto_t = None if upto_day is None else phase_tick(upto_day, upto_phase or "pre_open")
    scored: list[str] = []
    for q in ctx.pack.questions:
        row = answers.get(q.id)
        if is_scored(row):
            continue
        if upto_t is not None and phase_tick(q.resolves.day, q.resolves.phase) > upto_t:
            continue
        if row is None:
            row = ReplayPrediction(
                save_id=save.id,
                question_id=q.id,
                answer=None,
                skipped=True,
                submitted_tick=int(save.tick),
            )
            db.add(row)
            answers[q.id] = row
        score = score_question(ctx, q, row)
        points = 0
        ledger_ref: str | None = None
        if ctx.session.is_first_attempt and score > 0:
            points = points_for(score, ctx.masked)
        if points > 0:
            entry = points_service.credit(
                db,
                user_id=user_id,
                delta=points,
                reason="replay_prediction",
                ref=f"replay:{save.id.hex}:{q.id}",
                idempotency_key=f"replay:{user_id.hex}:{level_id.hex}:{q.id}",
                save_id=save.id,
                meta={"question_id": q.id, "score": score},
            )
            ledger_ref = entry.idempotency_key
        row.score = score
        row.points = points
        row.scored_at = now
        row.ledger_ref = ledger_ref
        ctx.session.points_total = int(ctx.session.points_total or 0) + points
        scored.append(q.id)
    return scored


__all__ = [
    "answers_by_question",
    "bucket_labels",
    "build_answer",
    "check_position_for_answer",
    "is_answered",
    "is_scored",
    "pending_at",
    "points_for",
    "question_opened",
    "question_out",
    "score_due",
    "score_question",
]
