"""回合与题目（03 §7.5）：出题 materialize_round、作答 answer_round、判定 resolve_question。

B 的接口只在本文件适配（R4）：structure_for / change_bp_for（services.predictions）、
validate_answers / build_questions / resolve_rank（domain.predictions）。
题目是 seed 与回合事件的确定函数，重放幂等；服务端 QuestionSpec 每次由 build_questions 重算，
不依赖 to_public 的 JSON（服务端字段 edges_bp、tt_end 不外发）。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.constants import (
    CHALLENGE_CLOCK_RULES,
    CHALLENGE_MAX_REVISIONS,
    CHALLENGE_PEER_MIN,
)
from stocksim.domain.challenge.scoring import question_results
from stocksim.domain.clock import timebase
from stocksim.domain.errors import DomainError
from stocksim.domain.events.types import GameEvent
from stocksim.domain.predictions.constants import DIRECTION_WINDOW_DAYS
from stocksim.domain.predictions.questions import (
    QuestionContext,
    build_questions,
    resolve_rank,
    validate_answers,
)
from stocksim.domain.predictions.types import BucketQ, QuestionSpec, RankQ
from stocksim.domain.scoring import (
    bucket_of,
    expected_random_ndcg_score,
    ndcg_at_k_score,
    rps_score,
    uniform_rps_score,
)
from stocksim.models import Challenge, ChallengeAnswer, ChallengeEntry, ChallengeRound, Save
from stocksim.services import events as events_service
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import hooks

EVENT_ID_RE = re.compile(r"^e(\d{1,9})-(\d{1,2})$")


def event_of(seed: int, events_ruleset: int, event_id: str) -> GameEvent:
    """按 event_id 从 seed 重新生成回合事件（服务端完整对象）。event_id 形如 e{day}-{slot}。"""
    match = EVENT_ID_RE.match(event_id)
    if match is None:
        raise RuntimeError(f"malformed event id {event_id!r}")
    day = int(match.group(1))
    for ev in events_service.day_events(seed, events_ruleset, CHALLENGE_CLOCK_RULES, day):
        if ev.event_id == event_id:
            return ev
    raise RuntimeError(f"round event {event_id} not found on day {day}")


def round_specs(
    seed: int, ch: Challenge, rnd: ChallengeRound
) -> tuple[GameEvent, tuple[QuestionSpec, ...]]:
    """回合的服务端题目（build_questions 的结果），trigger = 停顿 tick。"""
    ev = event_of(seed, ch.events_ruleset, rnd.event_id)
    specs = build_questions(
        ev,
        QuestionContext(
            seed=seed,
            trigger_trading_tick=rnd.hold_tt,
            structure=predictions_service.structure_for(ch.events_ruleset),
            window_days=DIRECTION_WINDOW_DAYS,
            clock_rules=CHALLENGE_CLOCK_RULES,
        ),
    )
    return ev, specs


def resolve_tt_of(ev: GameEvent, spec: QuestionSpec) -> int:
    """单题判定 tick（02 §3.4；与 domain.challenge.script.major_ref 的口径一致）。"""
    tb = timebase(CHALLENGE_CLOCK_RULES)
    if isinstance(spec, BucketQ):
        return tb.first_tt(spec.to_day + 1)
    if isinstance(spec, RankQ):
        return tb.first_tt(spec.at_day + 1)
    if ev.rumor is None:
        raise ValueError("binary question without rumor")
    return ev.rumor.resolve_trading_tick


def materialize_round(
    db: Session, ch: Challenge, master: Save, rnd: ChallengeRound, now: datetime
) -> bool:
    """首次到达停顿点时出题：写 questions 与 opened_at（幂等：opened_at 非空则不做）。不 commit。

    返回是否本次首次打开；为 True 时调用方触发 hooks.run_round_open（03 §7.3）。
    """
    if rnd.opened_at is not None:
        return False
    _, specs = round_specs(master.market_seed, ch, rnd)
    rnd.questions = [q.to_public() for q in specs]
    rnd.opened_at = now
    return True


def answer_round(
    db: Session,
    ch: Challenge,
    master: Save,
    entry: ChallengeEntry | None,
    round_index: int,
    answers_in: Mapping[str, Any],
    *,
    now: datetime,
    round_row: ChallengeRound | None,
) -> ChallengeAnswer:
    """作答（03 §7.5）。调用方传入 round_row（由 registry.round_by_index 取得）。不 commit。

    错误顺序：未报名 → 回合不可见（含未到停顿、不存在）→ 已截止 → 修改次数用尽 → 校验。
    """
    if entry is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_ENTERED, {"challenge_id": str(ch.id)})
    if round_row is None or now < _aware(round_row.hold_at):
        raise AppError(ErrorCode.CHALLENGE_ROUND_NOT_FOUND, {"round_index": round_index})
    if now >= _aware(round_row.closes_at):
        raise AppError(
            ErrorCode.CHALLENGE_ROUND_CLOSED,
            {"round_index": round_index, "closes_at": _aware(round_row.closes_at).isoformat()},
        )
    # 正常路径下推进已打开该回合；推进尚未发生时在此补开（同样只触发一次钩子）
    if materialize_round(db, ch, master, round_row, now):
        hooks.run_round_open(db, ch, round_row)
    existing = db.scalar(
        select(ChallengeAnswer).where(
            ChallengeAnswer.round_id == round_row.id, ChallengeAnswer.entry_id == entry.id
        )
    )
    if existing is not None and existing.revision >= CHALLENGE_MAX_REVISIONS:
        raise AppError(ErrorCode.CHALLENGE_ANSWER_LIMIT, {"limit": CHALLENGE_MAX_REVISIONS})
    cleaned = {k: v for k, v in answers_in.items() if v is not None}
    try:
        validate_answers(round_row.questions or [], cleaned)
    except DomainError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, dict(exc.params)) from exc
    if existing is None:
        row = ChallengeAnswer(
            id=uuid.uuid4(),
            round_id=round_row.id,
            entry_id=entry.id,
            answers=cleaned,
            revision=1,
            first_submitted_at=now,
            submitted_tt=round_row.hold_tt,
            results={},
            round_score=0,
        )
        db.add(row)
        entry.answered_rounds += 1
        round_row.answer_count += 1
    else:
        existing.answers = cleaned
        existing.revision += 1
        row = existing
    db.flush()
    return row


def resolve_question(
    db: Session,
    ch: Challenge,
    rnd: ChallengeRound,
    qid: str,
    master: Save,
    *,
    now: datetime,
) -> None:
    """判定一题（03 §7.5、§1.6）：写 outcomes[qid]，按 §8.1 为全部作答计 results[qid]。

    dir 真值为 None 时该题作废（{"void": true}，计 0 分）。全部题判定后写 resolved_at。不 commit。
    """
    if qid in (rnd.outcomes or {}):
        return
    ev, specs = round_specs(master.market_seed, ch, rnd)
    spec = next((s for s in specs if s.qid == qid), None)
    if spec is None:
        raise RuntimeError(f"question {qid} not in round {rnd.round_index}")
    outcome = _truth(db, master, ev, spec)
    rnd.outcomes = {**(rnd.outcomes or {}), qid: outcome}
    _score_question(db, rnd, spec, ev, outcome, qid)
    if set((rnd.resolve_tts or {}).keys()) <= set(rnd.outcomes):
        rnd.resolved_at = now


def _truth(db: Session, master: Save, ev: GameEvent, spec: QuestionSpec) -> dict[str, Any]:
    """真值（03 §1.6）：dir 用 change_bp_for+bucket_of；rank 用 resolve_rank；rumor 用 truth。"""
    if isinstance(spec, BucketQ):
        change = predictions_service.change_bp_for(
            db,
            master,
            target_kind=spec.target_kind,
            target=spec.target,
            from_day=spec.from_day,
            to_day=spec.to_day,
        )
        if change is None:
            return {"void": True}
        return {"outcome_bucket": bucket_of(change, spec.edges_bp), "change_bp": change}
    if isinstance(spec, RankQ):
        return {"relevance": resolve_rank(ev, spec)}
    return {"truth": bool(ev.rumor.truth)}  # type: ignore[union-attr]


def _raw_scores(
    spec: QuestionSpec, outcome: Mapping[str, Any], answer: Mapping[str, Any]
) -> tuple[int, int]:
    """单人单题的原始分 S 与均匀基线 U（02 §4.5 口径，复用 domain.scoring）。"""
    if isinstance(spec, BucketQ):
        bucket = int(outcome["outcome_bucket"])
        return (
            rps_score(answer[spec.qid]["probs"], bucket),
            uniform_rps_score(spec.k, bucket),
        )
    if isinstance(spec, RankQ):
        relevance = outcome["relevance"]
        return (
            ndcg_at_k_score(answer[spec.qid]["order"], relevance, spec.k),
            expected_random_ndcg_score(len(spec.candidates), relevance, spec.k),
        )
    truth = 1 if outcome["truth"] else 0
    return rps_score(answer[spec.qid]["probs"], truth), uniform_rps_score(spec.k, truth)


def _score_question(
    db: Session,
    rnd: ChallengeRound,
    spec: QuestionSpec,
    ev: GameEvent,
    outcome: Mapping[str, Any],
    qid: str,
) -> None:
    rows = db.execute(
        select(ChallengeAnswer, ChallengeEntry.eligible)
        .join(ChallengeEntry, ChallengeEntry.id == ChallengeAnswer.entry_id)
        .where(ChallengeAnswer.round_id == rnd.id)
    ).all()
    if "void" in outcome:
        for ans, _ in rows:
            ans.results = {**(ans.results or {}), qid: {"void": True, "score": 0}}
    else:
        raws = [_raw_scores(spec, outcome, ans.answers) for ans, _ in rows]
        results = question_results(
            [s for s, _ in raws],
            [u for _, u in raws],
            [bool(e) for _, e in rows],
            peer_min=CHALLENGE_PEER_MIN,
        )
        for (ans, _), r in zip(rows, results, strict=True):
            ans.results = {
                **(ans.results or {}),
                qid: {
                    "raw": r.raw,
                    "uniform_score": r.uniform_score,
                    "baseline": r.baseline,
                    "peer": r.peer,
                    "score": r.score,
                    "used": r.used,
                },
            }
    for ans, _ in rows:
        ans.round_score = sum(int(v["score"]) for v in (ans.results or {}).values())


def _aware(value: datetime) -> datetime:
    """SQLite 读回的 datetime 可能无时区；统一按 UTC 解释。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "answer_round",
    "event_of",
    "materialize_round",
    "resolve_question",
    "resolve_tt_of",
    "round_specs",
]
