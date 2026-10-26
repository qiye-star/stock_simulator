"""挑战对外 dict 的唯一出口（03 §5、§7.1、§10.2）。REST 与 WS 都经本模块组装，不在路由里拼字段。

保密规则（03 §5）在这里逐条落实：
- 回合的 event_id / hold_at 只在 now ≥ hold_at 后输出；题目（questions）同理；未到回合不进卡片。
- 群体分布 crowd 只在 now ≥ closes_at 后输出，且只统计合格报名。
- ChallengeOut 不含 end_tt、ends_at、seed、salt、commitment_input；settle_expected_at 为上界。
- reveal 只对 settled 与 void 可用；void 没有回合与结算数据，只输出承诺与 seed 字段。
- 日志与返回值之外不输出 seed、盐（03 §5 #11）。

时间字段以 datetime 返回（aware, UTC）；序列化由 Pydantic（REST）或调用方（WS）负责。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.commit import commitment_input, verify_commitment
from stocksim.domain.challenge.constants import (
    CHALLENGE_ROUNDS,
    COMMITMENT_SCHEME,
)
from stocksim.domain.money import round_half_up_div
from stocksim.domain.scoring import argmax_pick
from stocksim.models import Challenge, ChallengeAnswer, ChallengeEntry, ChallengeRound, Save
from stocksim.services.challenges import clock, registry
from stocksim.services.challenges.sync import RUNNING_PHASES
from stocksim.services.challenges.timeutil import from_ms

RoundState = str  # pending | burst | open | closed | resolved


def export_challenge_block(db: Session, save: Save) -> dict[str, Any] | None:
    """挑战玩家存档导出的 challenge 块（03 §5 #1）：只含公开的 id 与日期，不含 seed。"""
    row = db.execute(
        select(Challenge.id, Challenge.challenge_date)
        .join(ChallengeEntry, ChallengeEntry.challenge_id == Challenge.id)
        .where(ChallengeEntry.save_id == save.id)
    ).first()
    if row is None:
        return None
    challenge_id, challenge_date = row
    return {"challenge_id": str(challenge_id), "challenge_date": challenge_date.isoformat()}


# ---------------------------------------------------------------- 阶段与回合


def phase_of(db: Session, ch: Challenge, now: datetime) -> tuple[str, int | None, datetime | None]:
    """(phase, round_index, next_change_at)。void 没有时间线，固定为 ended。

    next_change_at 只在时刻公开时给出（03 §5 #8）：before 为 starts_at，hold 为本回合的恢复时刻
    （resume_{k+1}，排程固定）。burst 的下一次变化是 hold_at，final 的下一次变化是 ends_at，二者在
    到达前都是保密的（hold_at 只在 now ≥ hold_at 后输出，ends_at 永不输出），此处返回 None。
    """
    if ch.status == "void":
        return "ended", None, None
    info = clock.phase_at(db, ch, now)
    public = info.phase in ("before", "hold")
    next_at = from_ms(info.next_change_ms) if public and info.next_change_ms is not None else None
    return info.phase, info.round_index, next_at


def clock_overrides(db: Session, save: Save, now: datetime) -> dict[str, datetime | int | None]:
    """挑战存档的 ClockOut 覆盖（03 §3.2）：market.clock_view 对 CHALLENGE_MODES 调用。

    - ms_per_minute：快放段（burst/final）为挑战 tick_ms，其余（赛前、停顿、结束）为 None；
    - next_tick_at：快放段为 real_time_of(tt+1)（tt+1 超过 end_tt 时为 None），其余为 None；
    - fast_forward_at：恒为 None（挑战没有停留点快进）；
    - next_event_at：仅赛前为 starts_at（与 phase_of 的公开口径一致）；快放段的 hold_at 与 final 的
      ends_at 保密，停顿段为 None。
    save.tick 必须已由 sync_entry_save 镜像为 tt(now)。
    """
    ch = registry.challenge_of_save(db, save)
    phase, _round_index, next_at = phase_of(db, ch, now)
    fast = phase in RUNNING_PHASES
    next_tick = None
    if fast and save.tick + 1 <= ch.end_tt:
        next_tick = clock.reached_at(db, ch, int(save.tick) + 1)
    return {
        "ms_per_minute": ch.tick_ms if fast else None,
        "next_tick_at": next_tick,
        "fast_forward_at": None,
        "next_event_at": next_at if phase == "before" else None,
    }


def round_state(rnd: ChallengeRound, now: datetime) -> RoundState:
    """回合状态（03 §1.1）：resolved（题已全判定）> closed（过截止）> open（停顿中）> burst。"""
    if rnd.resolved_at is not None:
        return "resolved"
    if now >= _aware(rnd.closes_at):
        return "closed"
    if now >= _aware(rnd.hold_at):
        return "open"
    if now >= _aware(rnd.resume_at):
        return "burst"
    return "pending"


def is_visible(rnd: ChallengeRound, now: datetime) -> bool:
    """回合对玩家可见：已到停顿时刻（03 §5 #8）。"""
    return now >= _aware(rnd.hold_at)


def round_out(rnd: ChallengeRound, now: datetime) -> dict[str, Any]:
    visible = is_visible(rnd, now)
    return {
        "round_index": rnd.round_index,
        "state": round_state(rnd, now),
        "resume_at": _aware(rnd.resume_at),
        "closes_at": _aware(rnd.closes_at),
        "hold_at": _aware(rnd.hold_at) if visible else None,
        "event_id": rnd.event_id if visible else None,
    }


# ---------------------------------------------------------------- 挑战与报名


def challenge_out(
    db: Session, ch: Challenge, *, viewer: uuid.UUID | None, now: datetime
) -> dict[str, Any]:
    """ChallengeOut（03 §10.2）。不含 end_tt / ends_at / seed / salt / commitment_input。"""
    phase, round_index, next_at = phase_of(db, ch, now)
    rounds = [] if ch.status == "void" else registry.rounds_of(db, ch)
    entry = registry.entry_for(db, ch, viewer) if viewer is not None else None
    public_tt = 0 if ch.status == "void" else clock.tt_at(db, ch, now)
    return {
        "id": ch.id,
        "challenge_date": ch.challenge_date,
        "status": ch.status,
        "phase": phase,
        "round_index": round_index,
        "rounds_total": CHALLENGE_ROUNDS,
        "schedule_mode": ch.schedule_mode,
        "starts_at": _aware(ch.starts_at),
        "entry_closes_at": _aware(ch.entry_closes_at),
        "settle_expected_at": _aware(ch.settle_expected_at),
        "next_change_at": next_at,
        "server_time": now,
        "tick_ms": ch.tick_ms,
        "clock_rules": f"v{ch.clock_rules}",
        "events_ruleset": ch.events_ruleset,
        "seed_commitment": ch.seed_commitment,
        "commitment_scheme": COMMITMENT_SCHEME,
        "participant_count": participant_count(db, ch),
        "public_trading_tick": public_tt,
        "rounds": [round_out(r, now) for r in rounds],
        "my_entry": entry_out(entry, ch) if entry is not None else None,
    }


def participant_count(db: Session, ch: Challenge) -> int:
    return int(
        db.scalar(select(func.count(ChallengeEntry.id)).where(ChallengeEntry.challenge_id == ch.id))
        or 0
    )


def entry_out(entry: ChallengeEntry, ch: Challenge) -> dict[str, Any]:
    """ChallengeEntryOut（03 §10.2）。result 在结算后出现。"""
    return {
        "entry_id": entry.id,
        "challenge_id": entry.challenge_id,
        "save_id": entry.save_id,
        "eligible": bool(entry.eligible),
        "joined_at": _aware(entry.joined_at),
        "answered_rounds": int(entry.answered_rounds),
        "result": entry_result_out(entry, ch.eligible_count),
    }


def entry_result_out(entry: ChallengeEntry, eligible_count: int) -> dict[str, Any] | None:
    """个人结算成绩（EntryResultOut）。尚未结算（settled_at 为空）返回 None。"""
    if entry.settled_at is None:
        return None
    return {
        "final_equity_cents": entry.final_equity_cents,
        "return_bp": entry.return_bp,
        "forecast_score": entry.forecast_score,
        "trade_score": entry.trade_score,
        "total_score": entry.total_score,
        "rank": entry.rank,
        "eligible_count": eligible_count,
        "points_awarded": entry.points_awarded,
    }


# ---------------------------------------------------------------- 回合卡


def round_card_out(
    db: Session,
    ch: Challenge,
    rnd: ChallengeRound,
    entry: ChallengeEntry | None,
    *,
    now: datetime,
    lang: str,
) -> dict[str, Any]:
    """ChallengeRoundCardOut（03 §10.2）。调用方只传入已可见的回合（is_visible）。

    event 经 A 的公开形态（at_tt = 停顿 tick）；questions 为 B 的 to_public；
    results 只含已判定的题；crowd 只在截止后出现。
    """
    answer = _my_answer(db, rnd, entry) if entry is not None else None
    questions = list(rnd.questions or [])
    return {
        "round_index": rnd.round_index,
        "state": round_state(rnd, now),
        "event": _event_out(db, ch, rnd, lang),
        "closes_at": _aware(rnd.closes_at),
        "questions": questions,
        "my_answers": _answers_out(questions, answer.answers) if answer is not None else [],
        "my_revision": int(answer.revision) if answer is not None else 0,
        "results": _results_out(questions, rnd, answer),
        "my_round_score": (
            int(answer.round_score) if answer is not None and rnd.resolved_at is not None else None
        ),
        "crowd": _crowd(db, rnd, questions) if now >= _aware(rnd.closes_at) else None,
    }


def _my_answer(db: Session, rnd: ChallengeRound, entry: ChallengeEntry) -> ChallengeAnswer | None:
    return db.scalar(
        select(ChallengeAnswer).where(
            ChallengeAnswer.round_id == rnd.id, ChallengeAnswer.entry_id == entry.id
        )
    )


def _event_out(db: Session, ch: Challenge, rnd: ChallengeRound, lang: str) -> dict[str, Any] | None:
    """A 的公开 EventOut（at_tt 取停顿 tick，只含该时刻前已发布的快讯）。master 已清理则为 None。"""
    if ch.status == "void" or ch.master_save_id is None:
        return None
    return registry.public_event(db, ch, rnd.event_id, lang, at_tt=rnd.hold_tt)


def _answers_out(questions: list[dict[str, Any]], answers: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in questions:
        qid = str(q["qid"])
        ans = answers.get(qid)
        if ans is None:
            continue
        if "probs" in ans:
            probs = [int(p) for p in ans["probs"]]
            out.append(
                {
                    "qid": qid,
                    "probs": probs,
                    "order": None,
                    "pick": argmax_pick(probs),
                    "claimed_pct": max(probs),
                }
            )
        else:
            out.append(
                {
                    "qid": qid,
                    "probs": None,
                    "order": [str(c) for c in ans["order"]],
                    "pick": None,
                    "claimed_pct": None,
                }
            )
    return out


def _results_out(
    questions: list[dict[str, Any]], rnd: ChallengeRound, answer: ChallengeAnswer | None
) -> list[dict[str, Any]]:
    """已判定题的结果（公开的真值 + 本人的分数）。未判定的题不出现。"""
    judged = rnd.outcomes or {}
    mine = (answer.results or {}) if answer is not None else {}
    out: list[dict[str, Any]] = []
    for q in questions:
        qid = str(q["qid"])
        if qid not in judged:
            continue
        truth = judged[qid]
        own = mine.get(qid) or {}
        out.append(
            {
                "qid": qid,
                "resolved": True,
                "void": bool(truth.get("void", False)),
                "outcome_bucket": truth.get("outcome_bucket"),
                "change_bp": truth.get("change_bp"),
                "true_top": None,
                "relevance": truth.get("relevance"),
                "candidate_change_bp": None,
                "truth": truth.get("truth"),
                "score": own.get("score"),
                "uniform_score": own.get("uniform_score"),
                "baseline": own.get("baseline"),
                "points": None,
                "hit": None,
                "peer": own.get("peer"),
                "used": own.get("used"),
            }
        )
    return out


def _crowd(db: Session, rnd: ChallengeRound, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """截止后的群体分布（只统计合格报名）：bucket/binary 为各档平均概率（整数，合计约 100），
    rank 为各候选进入前三的次数。"""
    rows = db.scalars(
        select(ChallengeAnswer.answers)
        .join(ChallengeEntry, ChallengeEntry.id == ChallengeAnswer.entry_id)
        .where(ChallengeAnswer.round_id == rnd.id, ChallengeEntry.eligible.is_(True))
    ).all()
    n = len(rows)
    by_qid: dict[str, dict[str, Any]] = {}
    for q in questions:
        qid = str(q["qid"])
        if n == 0:
            break
        if q["kind"] in ("bucket", "binary"):
            k = len(q["edges_bp"]) + 1 if q["kind"] == "bucket" else 2
            sums = [0] * k
            for answers in rows:
                probs = (answers.get(qid) or {}).get("probs")
                if probs is None:
                    continue
                for i, p in enumerate(probs):
                    sums[i] += int(p)
            by_qid[qid] = {"mean_probs": [round_half_up_div(s, n) for s in sums]}
        elif q["kind"] == "rank":
            counts = {str(c): 0 for c in q["candidates"]}
            for answers in rows:
                order = (answers.get(qid) or {}).get("order")
                for cand in (order or [])[:3]:
                    if str(cand) in counts:
                        counts[str(cand)] += 1
            by_qid[qid] = {"top3_counts": counts}
    return {"n": n, "by_qid": by_qid}


# ---------------------------------------------------------------- 复盘与 reveal


def review_out(
    db: Session, ch: Challenge, entry: ChallengeEntry, *, now: datetime, lang: str
) -> dict[str, Any]:
    """ReviewOut（03 §10.2）：本人的复盘。save_available 在玩家存档被清理后为 false。"""
    rounds = registry.rounds_of(db, ch)
    return {
        "challenge": challenge_out(db, ch, viewer=entry.user_id, now=now),
        "entry": entry_out(entry, ch),
        "rounds": [round_card_out(db, ch, r, entry, now=now, lang=lang) for r in rounds],
        "save_available": entry.save_id is not None,
    }


def reveal_out(db: Session, ch: Challenge) -> dict[str, Any]:
    """RevealOut（03 §1.4、§10.2）。settled 与 void 可用；其它状态抛 CHALLENGE_NOT_SETTLED。

    seed 以十进制字符串输出（> 2^53）。commitment_input 由 domain 复算，与 seed_commitment
    不一致视为数据损坏。void 没有回合与 end_tt：rounds 为空、end_tt 为 null，
    review_available 为 false。
    """
    row = db.get(Challenge, ch.id)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(ch.id)})
    if row.status not in ("settled", "void"):
        raise AppError(ErrorCode.CHALLENGE_NOT_SETTLED, {"challenge_id": str(row.id)})
    text = commitment_input(
        date_iso=row.challenge_date.isoformat(),
        events_ruleset=row.events_ruleset,
        clock_rules=row.clock_rules,
        seed=row.market_seed,
        salt_hex=row.seed_salt,
    )
    if not verify_commitment(text, row.seed_commitment):
        raise RuntimeError(f"challenge {row.id} seed commitment does not match its reveal data")
    is_void = row.status == "void"
    rounds = [] if is_void else registry.rounds_of(db, row)
    return {
        "challenge_id": row.id,
        "challenge_date": row.challenge_date,
        "status": row.status,
        "market_seed": str(row.market_seed),
        "seed_salt": row.seed_salt,
        "seed_commitment": row.seed_commitment,
        "commitment_input": text,
        "events_ruleset": row.events_ruleset,
        "clock_rules": f"v{row.clock_rules}",
        "format_version": row.format_version,
        "start_minute": row.start_minute,
        "tick_ms": row.tick_ms,
        "end_tt": None if is_void else int(row.end_tt),
        "rounds": [
            {
                "round_index": r.round_index,
                "event_id": r.event_id,
                "hold_tt": int(r.hold_tt),
                "resolve_tts": {qid: int(tt) for qid, tt in (r.resolve_tts or {}).items()},
                "resume_at": _aware(r.resume_at),
                "hold_at": _aware(r.hold_at),
                "closes_at": _aware(r.closes_at),
            }
            for r in rounds
        ],
        "review_available": (not is_void) and row.master_save_id is not None,
    }


def _aware(value: datetime) -> datetime:
    """SQLite 读回的 datetime 可能无时区；统一按 UTC 解释。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "challenge_out",
    "entry_out",
    "entry_result_out",
    "export_challenge_block",
    "is_visible",
    "phase_of",
    "reveal_out",
    "review_out",
    "round_card_out",
    "round_out",
    "round_state",
]
