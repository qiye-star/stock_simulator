"""预测卡服务（02 §1.3、§3、§5.7、§10）。

- 出卡：`on_publish` 挂在 A 的发布钩子上（推进事务内运行，不 commit）。重大事件的第一条快讯
  tick 出一张卡，钩子返回 True，A 把存档暂停并截停本批。
- 截止：卡在触发交易 tick 打开，`deadline = opened_trading_tick`；行情再走一个交易 tick 即过期。
- 结算：`settle_due` 自己 commit（经 tx.run_in_transaction），幂等；题目按时间基到期后逐题结算，
  全部题结算后 answered → settled 并入账（每卡一次，幂等键 prediction:{card_id}，日上限）。
- 保密：题目 JSON 只含公开字段；结果只在对应题结算后给出。

CardPolicy（C/E 的扩展点）：`register_card_policy` 按注册顺序询问，第一个非 None 的生效。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.clock import timebase
from stocksim.domain.errors import DomainError
from stocksim.domain.events import EVENT_RULESET_VERSION, GameEvent
from stocksim.domain.money import round_half_up_div
from stocksim.domain.predictions import (
    DIRECTION_WINDOW_DAYS,
    PREDICTION_DAILY_POINTS_CAP,
    QuestionContext,
    RankQ,
    Structure,
    build_questions,
    rank_truth,
    validate_answers,
)
from stocksim.domain.predictions.constants import PREDICTION_RULES_VERSION
from stocksim.domain.scoring import (
    argmax_pick,
    baseline_score,
    bucket_of,
    calibration_bins,
    calibration_error_bp,
    expected_random_ndcg_score,
    ndcg_at_k_score,
    rps_score,
    uniform_rps_score,
)
from stocksim.models import (
    Candle,
    IntelRumorHint,
    MarketState,
    PredictionAnswer,
    PredictionCard,
    PredictionSetting,
    Save,
)
from stocksim.services import event_hooks, points
from stocksim.services import events as events_service
from stocksim.services import titles as titles_service
from stocksim.services.market import clock_view, current_trading_tick, market_key
from stocksim.services.tx import run_in_transaction

__all__ = [
    "AnswerRecord",
    "CardPolicy",
    "SettleReport",
    "answer_card",
    "answers_for_event",
    "card_out",
    "card_policy",
    "change_bp_for",
    "get_card",
    "get_settings_out",
    "list_cards",
    "on_publish",
    "on_reset",
    "register_card_policy",
    "register_hooks",
    "set_settings",
    "settle_due",
    "skip_card",
    "stats",
    "structure_for",
]

OPEN_LIKE = ("open", "answered")
LIST_STATUSES = ("open", "answered", "settled", "expired", "void")
EVENT_ID_RE = re.compile(r"^e(\d{1,9})-(\d{1,2})$")
KIND_OF = {"dir": "bucket", "rank": "rank", "rumor": "binary"}


# ---------------------------------------------------------------- CardPolicy（C/E 扩展点，02 §1.3）


@dataclass(frozen=True)
class CardPolicy:
    enabled: bool = True  # False = 该存档不出卡
    force_mode: Literal["pause", "off"] | None = None  # 覆盖存档设置
    points_reason: str | None = "prediction"  # None = 只计分不发积分
    daily_cap: int | None = PREDICTION_DAILY_POINTS_CAP
    intel_allowed: bool = True  # False = 情报卡 409 INTEL_UNAVAILABLE，揭示 provider 返回空


PolicyFn = Callable[[Session, Save], CardPolicy | None]
_policies: list[PolicyFn] = []


def register_card_policy(fn: PolicyFn) -> None:
    if fn not in _policies:
        _policies.append(fn)


def clear_card_policies() -> None:
    """仅测试用。"""
    _policies.clear()


def card_policy(db: Session, save: Save) -> CardPolicy:
    for fn in tuple(_policies):
        result = fn(db, save)
        if result is not None:
            return result
    return CardPolicy()


# ---------------------------------------------------------------- 结构与真值口径（C/D 调用）


@lru_cache(maxsize=8)
def _structure(version: int) -> Structure:
    rs = events_service.ruleset(version)  # 结构与时钟无关，取 v1 时间基即可
    industries = rs.industries
    adj: dict[str, set[str]] = {name: set() for name in industries}
    for e in rs.edges:
        a, b = industries[e.from_idx], industries[e.to_idx]
        adj[a].add(b)
        adj[b].add(a)
    return Structure(
        industries=tuple(industries),
        stock_count={name: rs.stock_counts[i] for i, name in enumerate(industries)},
        neighbors={k: frozenset(v) for k, v in adj.items()},
        stock_total=len(rs.stocks),
        stock_names={s.code: s.name for s in rs.stocks},
    )


def structure_for(events_ruleset: int) -> Structure:
    """公开产业链结构，按规则集版本进程内缓存。"""
    return _structure(events_ruleset or EVENT_RULESET_VERSION)


def change_bp_for(
    db: Session,
    save: Save,
    *,
    target_kind: Literal["industry", "stock", "market"],
    target: str | None,
    from_day: int,
    to_day: int,
) -> int | None:
    """方向题真值的唯一口径：from_day−1 收盘 → to_day 收盘，逐股 bp 后等权。

    industry 委托 events.industry_change_bp；stock / market 在此计算（口径相同）。
    越界或无数据返回 None。读 candles / market_states 一律经 market_key(save)。
    """
    if target_kind == "industry":
        if target is None:
            return None
        return events_service.industry_change_bp(db, save, target, from_day, to_day)
    rs = events_service.ruleset(save.events_ruleset, save.clock_rules)
    if target_kind == "stock":
        if target is None:
            return None
        codes = [target]
    else:
        codes = [s.code for s in rs.stocks]
    tb = timebase(save.clock_rules)
    cur_day = tb.day_of(current_trading_tick(db, save))
    if from_day < 0 or to_day < from_day or to_day > cur_day:
        return None
    mk = market_key(save)
    wanted = sorted({from_day - 1, to_day} - {cur_day})
    closes: dict[tuple[str, int], int] = {}
    if wanted:
        rows = db.execute(
            select(Candle.stock_code, Candle.trading_day, Candle.close_cents).where(
                Candle.save_id == mk,
                Candle.stock_code.in_(codes),
                Candle.trading_day.in_(wanted),
            )
        ).all()
        closes = {(code, day): int(close) for code, day, close in rows}
    payload = db.get(MarketState, mk).payload

    def close_of(code: str, day: int) -> int | None:
        if day == cur_day:
            return int(payload[code][0])
        return closes.get((code, day))

    changes: list[int] = []
    for code in codes:
        base = close_of(code, from_day - 1)
        last = close_of(code, to_day)
        if base is None or last is None or base <= 0:
            continue
        changes.append(round_half_up_div((last - base) * 10_000, base))
    if not changes:
        return None
    return round_half_up_div(sum(changes), len(changes))


# ---------------------------------------------------------------- 事务内小工具


def require_enabled(save: Save) -> None:
    if not save.events_enabled:
        raise AppError(ErrorCode.EVENTS_DISABLED, {"save_id": str(save.id)})


def _utc_day_start() -> datetime:
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def _settings_mode(db: Session, save: Save) -> str:
    row = db.get(PredictionSetting, save.id)
    return row.mode if row is not None else "pause"


def get_settings_out(db: Session, save: Save) -> dict[str, Any]:
    policy = card_policy(db, save)
    mode = policy.force_mode or _settings_mode(db, save)
    return {"mode": mode, "forced": policy.force_mode is not None}


def set_settings(db: Session, save: Save, mode: str) -> dict[str, Any]:
    policy = card_policy(db, save)
    if policy.force_mode is not None:
        if mode != policy.force_mode:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "mode", "reason": "forced"})
        return {"mode": policy.force_mode, "forced": True}

    def work() -> None:
        row = db.get(PredictionSetting, save.id)
        if row is None:
            db.add(PredictionSetting(save_id=save.id, mode=mode))
        else:
            row.mode = mode

    run_in_transaction(db, work)
    return get_settings_out(db, save)


def _load_event(db: Session, save: Save, event_id: str) -> GameEvent:
    m = EVENT_ID_RE.fullmatch(event_id)
    if m is None:
        raise RuntimeError(f"bad event id on card: {event_id}")
    day = int(m.group(1))
    for ev in events_service.events_for_days(db, save, day, day, include_unpublished=True):
        if ev.event_id == event_id:
            return ev
    raise RuntimeError(f"event missing for card: {event_id}")


def _event_cached(db: Session, save: Save, event_id: str, cache: dict[str, GameEvent]) -> GameEvent:
    if event_id not in cache:
        cache[event_id] = _load_event(db, save, event_id)
    return cache[event_id]


def _domain_to_app(exc: DomainError) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, dict(exc.params))


# ---------------------------------------------------------------- 出卡（发布钩子，02 §3.1）


def on_publish(db: Session, ctx: event_hooks.PublishContext) -> bool:
    save = ctx.save
    if not save.events_enabled:
        return False
    policy = card_policy(db, save)
    mode = policy.force_mode or _settings_mode(db, save)
    if not policy.enabled or mode == "off":
        return False
    triggers = [
        e for e in ctx.events if e.major and min(n.trading_tick for n in e.news) == ctx.trading_tick
    ]
    if not triggers:
        return False
    tb = timebase(save.clock_rules)
    structure = structure_for(save.events_ruleset)
    created = False
    for ev in sorted(triggers, key=lambda e: e.event_id):
        exists = db.scalar(
            select(PredictionCard.id).where(
                PredictionCard.save_id == save.id, PredictionCard.event_id == ev.event_id
            )
        )
        if exists is not None:
            continue
        specs = build_questions(
            ev,
            QuestionContext(
                seed=save.market_seed,
                trigger_trading_tick=ctx.trading_tick,
                structure=structure,
                window_days=DIRECTION_WINDOW_DAYS,
                clock_rules=save.clock_rules,
            ),
        )
        db.add(
            PredictionCard(
                id=uuid.uuid4(),
                save_id=save.id,
                user_id=save.user_id,
                event_id=ev.event_id,
                events_ruleset=save.events_ruleset,
                rules_version=PREDICTION_RULES_VERSION,
                opened_trading_tick=ctx.trading_tick,
                opened_tick=ctx.tick,
                opened_trading_day=tb.day_of(ctx.trading_tick),
                deadline_trading_tick=ctx.trading_tick,
                window_days=DIRECTION_WINDOW_DAYS,
                status="open",
                paused_by_card=True,
                questions=[q.to_public() for q in specs],
            )
        )
        created = True
    return created


def on_reset(db: Session, save: Save) -> None:
    """换 seed 前：未结算的卡作废（不发积分）；删除该存档的传闻提示（02 §3.5）。"""
    now = utcnow()
    cards = db.scalars(
        select(PredictionCard).where(
            PredictionCard.save_id == save.id, PredictionCard.settled_at.is_(None)
        )
    ).all()
    for card in cards:
        card.status = "void"
        card.settled_at = now
    db.execute(delete(IntelRumorHint).where(IntelRumorHint.save_id == save.id))


def register_hooks() -> None:
    """main.create_app 调用：注册发布钩子与 reset 钩子（揭示 provider 由 intel 注册）。"""
    event_hooks.register_publish_hook(on_publish)
    event_hooks.register_reset_hook(on_reset)


# ---------------------------------------------------------------- 卡片读取与过期


def _encode_cursor(tick: int, card_id: uuid.UUID) -> str:
    raw = json.dumps([tick, str(card_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        tick, ident = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if isinstance(tick, bool) or not isinstance(tick, int) or not isinstance(ident, str):
            raise ValueError
        uuid.UUID(ident)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc
    return tick, ident


def _expire_if_due(card: PredictionCard, cur: int) -> bool:
    if card.status == "open" and cur > card.deadline_trading_tick:
        card.status = "expired"
        return True
    return False


def _load_card(db: Session, save: Save, card_id: uuid.UUID) -> PredictionCard:
    card = db.get(PredictionCard, card_id)
    if card is None or card.save_id != save.id:
        raise AppError(ErrorCode.PREDICTION_NOT_FOUND, {"card_id": str(card_id)})
    return card


def get_card(db: Session, save: Save, card_id: uuid.UUID) -> PredictionCard:
    require_enabled(save)
    return _load_card(db, save, card_id)


def list_cards(
    db: Session,
    save: Save,
    *,
    status: str,
    limit: int,
    cursor: str | None,
) -> tuple[list[PredictionCard], str | None]:
    require_enabled(save)
    stmt = select(PredictionCard).where(PredictionCard.save_id == save.id)
    if status != "all":
        stmt = stmt.where(PredictionCard.status == status)
    if cursor is not None:
        tick, ident = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                PredictionCard.opened_trading_tick < tick,
                (PredictionCard.opened_trading_tick == tick)
                & (PredictionCard.id < uuid.UUID(ident)),
            )
        )
    rows = list(
        db.scalars(
            stmt.order_by(
                PredictionCard.opened_trading_tick.desc(), PredictionCard.id.desc()
            ).limit(limit + 1)
        )
    )
    if len(rows) > limit:
        page = rows[:limit]
        return page, _encode_cursor(page[-1].opened_trading_tick, page[-1].id)
    return rows, None


# ---------------------------------------------------------------- 作答 / 不答（02 §3.3、§10.1）


def _maybe_resume(db: Session, save: Save, card: PredictionCard, cur: int, resume: bool) -> None:
    if not (resume and save.paused):
        return
    others = db.scalar(
        select(func.count()).where(
            PredictionCard.save_id == save.id,
            PredictionCard.status == "open",
            PredictionCard.deadline_trading_tick >= cur,
            PredictionCard.id != card.id,
        )
    )
    if not others:
        save.paused = False
        save.last_tick_at = utcnow()


def _write_answers(
    db: Session, card: PredictionCard, user_id: uuid.UUID, answers: Mapping[str, Any]
) -> None:
    existing = {
        a.qid: a
        for a in db.scalars(select(PredictionAnswer).where(PredictionAnswer.card_id == card.id))
    }
    for q in card.questions:
        qid = str(q["qid"])
        ans = answers[qid]
        row = existing.get(qid)
        if qid == "rank":
            payload: dict[str, Any] = {"order": list(ans["order"])}
            pick = claimed = None
        else:
            probs = list(ans["probs"])
            payload = {"probs": probs}
            pick = argmax_pick(probs)
            claimed = max(probs)
        if row is None:
            db.add(
                PredictionAnswer(
                    id=uuid.uuid4(),
                    card_id=card.id,
                    user_id=user_id,
                    qid=qid,
                    kind=KIND_OF[qid],
                    answer=payload,
                    pick=pick,
                    claimed_pct=claimed,
                )
            )
        else:
            row.answer = payload
            row.pick = pick
            row.claimed_pct = claimed


def _closed_payload(card: PredictionCard) -> AppError:
    return AppError(ErrorCode.PREDICTION_CLOSED, {"card_id": str(card.id), "status": card.status})


def answer_card(
    db: Session,
    save: Save,
    card_id: uuid.UUID,
    answers: Mapping[str, Any],
    *,
    resume: bool,
    lang: str,
) -> dict[str, Any]:
    """作答。answers 形如 {"dir": {"probs": [...]}, "rank": {"order": [...]}, "rumor": {...}}。"""
    require_enabled(save)
    state: dict[str, Any] = {}

    def work() -> None:
        card = _load_card(db, save, card_id)
        cur = current_trading_tick(db, save)
        _expire_if_due(card, cur)
        if card.status not in OPEN_LIKE:
            state["closed"] = card.status
            return
        try:
            validate_answers(card.questions, answers)
        except DomainError as exc:
            raise _domain_to_app(exc) from exc
        _write_answers(db, card, save.user_id, answers)
        card.status = "answered"
        card.answered_at = utcnow()
        card.answered_trading_tick = cur
        _maybe_resume(db, save, card, cur, resume)
        state["card_id"] = card.id

    run_in_transaction(db, work, refresh=[save])
    if "closed" in state:
        card = _load_card(db, save, card_id)
        raise _closed_payload(card)
    return _answer_out(db, save, card_id, lang)


def skip_card(
    db: Session, save: Save, card_id: uuid.UUID, *, resume: bool, lang: str
) -> dict[str, Any]:
    """主动不答：open → expired（不发积分）；可选恢复行情。"""
    require_enabled(save)
    state: dict[str, Any] = {}

    def work() -> None:
        card = _load_card(db, save, card_id)
        cur = current_trading_tick(db, save)
        _expire_if_due(card, cur)
        if card.status != "open":
            state["closed"] = card.status
            return
        card.status = "expired"
        _maybe_resume(db, save, card, cur, resume)

    run_in_transaction(db, work, refresh=[save])
    if "closed" in state:
        raise _closed_payload(_load_card(db, save, card_id))
    return _answer_out(db, save, card_id, lang)


def _answer_out(db: Session, save: Save, card_id: uuid.UUID, lang: str) -> dict[str, Any]:
    card = _load_card(db, save, card_id)
    db.refresh(save)
    return {"card": card_out(db, save, card, lang), "clock": clock_view(db, save)}


# ---------------------------------------------------------------- 结算（02 §3.4）


@dataclass(frozen=True)
class SettleReport:
    settled: tuple[str, ...] = ()  # 本次完成结算的卡 id
    expired: tuple[str, ...] = ()  # 本次转为 expired 的卡 id
    points: int = 0  # 本次入账合计（未计 capped 之前的实际发放）
    new_titles: tuple[str, ...] = ()


def _score_probs(ans: PredictionAnswer, outcome: int, k: int) -> None:
    probs = list(ans.answer["probs"])
    score = rps_score(probs, outcome)
    uniform = uniform_rps_score(k, outcome)
    pick = argmax_pick(probs)
    ans.score = score
    ans.uniform_score = uniform
    ans.baseline = baseline_score(score, uniform)
    ans.p_outcome_pct = probs[outcome]
    ans.pick = pick
    ans.claimed_pct = max(probs)
    ans.hit = None if pick is None else pick == outcome
    ans.points = score


def _score_rank(ans: PredictionAnswer, relevance: Mapping[str, int], n_candidates: int) -> None:
    order = list(ans.answer["order"])
    score = ndcg_at_k_score(order, relevance, 3)
    uniform = expected_random_ndcg_score(n_candidates, relevance, 3)
    ans.score = score
    ans.uniform_score = uniform
    ans.baseline = baseline_score(score, uniform)
    ans.p_outcome_pct = None
    ans.hit = None
    ans.points = score


def _settle_card(
    db: Session,
    save: Save,
    card: PredictionCard,
    cur: int,
    now: datetime,
    ev_cache: dict[str, GameEvent],
    answers: dict[str, PredictionAnswer],
) -> tuple[bool, int]:
    """逐题结算。返回 (本卡是否全部结算完成, 本卡入账前的积分合计)。"""
    tb = timebase(save.clock_rules)
    results: dict[str, Any] = dict(card.outcomes or {})
    changed = False
    for q in card.questions:
        qid = str(q["qid"])
        if qid in results:
            continue
        if qid in ("dir", "rank"):
            to_day = int(q["to_day"]) if qid == "dir" else int(q["at_day"])
            if cur < tb.first_tt(to_day + 1):
                continue
            from_day = to_day - card.window_days + 1
        if qid == "dir":
            change = change_bp_for(
                db,
                save,
                target_kind=q["target_kind"],
                target=q["target"],
                from_day=int(q["from_day"]),
                to_day=to_day,
            )
            ans = answers.get("dir")
            if change is None:
                results["dir"] = {"void": True}
                if ans is not None:
                    ans.score = ans.uniform_score = ans.baseline = ans.points = None
                    ans.scored_at = now
            else:
                bucket = bucket_of(change, q["edges_bp"])
                results["dir"] = {"outcome_bucket": bucket, "change_bp": change}
                if ans is not None:
                    _score_probs(ans, bucket, len(q["edges_bp"]) + 1)
                    ans.scored_at = now
        elif qid == "rank":
            ev = _event_cached(db, save, card.event_id, ev_cache)
            rq = RankQ(
                candidates=tuple(q["candidates"]),
                exclude=q["exclude"],
                at_day=to_day,
                tt_end=tb.first_tt(to_day + 1) - 1,
            )
            top, relevance = rank_truth(ev, rq)
            changes = {
                name: change_bp_for(
                    db,
                    save,
                    target_kind="industry",
                    target=name,
                    from_day=from_day,
                    to_day=to_day,
                )
                for name in q["candidates"]
            }
            results["rank"] = {
                "true_top": top,
                "relevance": relevance,
                "candidate_change_bp": changes,
            }
            ans = answers.get("rank")
            if ans is not None:
                _score_rank(ans, relevance, len(q["candidates"]))
                ans.scored_at = now
        elif qid == "rumor":
            ev = _event_cached(db, save, card.event_id, ev_cache)
            if ev.rumor is None or cur < ev.rumor.resolve_trading_tick:
                continue
            truth = bool(ev.rumor.truth)
            results["rumor"] = {"truth": truth}
            ans = answers.get("rumor")
            if ans is not None:
                _score_probs(ans, 1 if truth else 0, 2)
                ans.scored_at = now
        else:  # pragma: no cover - 未知题型是数据错误
            continue
        changed = True
    if changed:
        card.outcomes = results
    done = all(str(q["qid"]) in results for q in card.questions)
    total = sum(int(a.points or 0) for a in answers.values())
    return done, total


def _credit_card(
    db: Session, save: Save, card: PredictionCard, total: int, policy: CardPolicy
) -> int:
    """每卡一次入账（幂等键 prediction:{card_id}）；日上限超出部分不发，points_capped=true。"""
    if policy.points_reason is None:
        card.points_capped = False
        return 0
    granted = total
    if policy.daily_cap is not None:
        used = points.sum_since(
            db,
            user_id=card.user_id,
            reasons=[policy.points_reason],
            since=_utc_day_start(),
        )
        granted = min(total, max(0, policy.daily_cap - used))
    card.points_capped = granted < total
    entry = points.credit(
        db,
        user_id=card.user_id,
        delta=granted,
        reason=policy.points_reason,
        ref=f"card:{card.id}",
        idempotency_key=f"prediction:{card.id}",
        save_id=save.id,
        meta={"event_id": card.event_id, "points_raw": total},
    )
    card.ledger_entry_id = entry.id
    return granted


def settle_due(db: Session, save: Save) -> SettleReport:
    """结算到期的题（自己 commit，幂等）。关闭事件的存档直接返回空报告。"""
    if not save.events_enabled:
        return SettleReport()
    cur = current_trading_tick(db, save)
    pending = list(
        db.scalars(
            select(PredictionCard.id).where(
                PredictionCard.save_id == save.id,
                PredictionCard.status.in_(("open", "answered", "expired")),
                PredictionCard.settled_at.is_(None),
            )
        )
    )
    if not pending:
        return SettleReport()

    def work() -> SettleReport:
        now = utcnow()
        policy = card_policy(db, save)
        settled: list[str] = []
        expired: list[str] = []
        total_granted = 0
        ev_cache: dict[str, GameEvent] = {}
        cards = db.scalars(
            select(PredictionCard)
            .where(PredictionCard.id.in_(pending))
            .order_by(PredictionCard.opened_trading_tick, PredictionCard.id)
        ).all()
        user_scored = False
        for card in cards:
            if _expire_if_due(card, cur):
                expired.append(str(card.id))
            answers = {
                a.qid: a
                for a in db.scalars(
                    select(PredictionAnswer).where(PredictionAnswer.card_id == card.id)
                )
            }
            done, total = _settle_card(db, save, card, cur, now, ev_cache, answers)
            user_scored = user_scored or any(a.scored_at is not None for a in answers.values())
            if done and card.settled_at is None:
                card.settled_at = now
                if card.status == "answered":
                    card.points = total
                    card.status = "settled"
                    total_granted += _credit_card(db, save, card, total, policy)
                    settled.append(str(card.id))
                else:
                    card.points = None
                    settled.append(str(card.id))
        new_titles: list[str] = []
        if user_scored:
            new_titles = titles_service.evaluate_for_user(db, save.user_id)
        return SettleReport(
            settled=tuple(settled),
            expired=tuple(expired),
            points=total_granted,
            new_titles=tuple(new_titles),
        )

    return run_in_transaction(db, work, refresh=[save])


# ---------------------------------------------------------------- 输出（PredictionCardOut）


def _answer_list(answers: Sequence[PredictionAnswer]) -> list[dict[str, Any]]:
    order = {"dir": 0, "rank": 1, "rumor": 2}
    out = []
    for a in sorted(answers, key=lambda x: order.get(x.qid, 9)):
        out.append(
            {
                "qid": a.qid,
                "probs": a.answer.get("probs"),
                "order": a.answer.get("order"),
                "pick": a.pick,
                "claimed_pct": a.claimed_pct,
            }
        )
    return out


def _result_list(
    card: PredictionCard, answers: Mapping[str, PredictionAnswer]
) -> list[dict[str, Any]]:
    outcomes = card.outcomes or {}
    out: list[dict[str, Any]] = []
    for q in card.questions:
        qid = str(q["qid"])
        res: dict[str, Any] = {
            "qid": qid,
            "resolved": qid in outcomes,
            "void": bool(outcomes.get(qid, {}).get("void", False)),
            "outcome_bucket": None,
            "change_bp": None,
            "true_top": None,
            "relevance": None,
            "candidate_change_bp": None,
            "truth": None,
            "score": None,
            "uniform_score": None,
            "baseline": None,
            "points": None,
            "hit": None,
        }
        if qid in outcomes:
            o = outcomes[qid]
            if qid == "dir":
                res["outcome_bucket"] = o.get("outcome_bucket")
                res["change_bp"] = o.get("change_bp")
            elif qid == "rank":
                res["true_top"] = o.get("true_top")
                res["relevance"] = o.get("relevance")
                res["candidate_change_bp"] = o.get("candidate_change_bp")
            elif qid == "rumor":
                res["truth"] = o.get("truth")
        ans = answers.get(qid)
        if ans is not None and ans.scored_at is not None:
            res.update(
                score=ans.score,
                uniform_score=ans.uniform_score,
                baseline=ans.baseline,
                points=ans.points,
                hit=ans.hit,
            )
        out.append(res)
    return out


def card_out(db: Session, save: Save, card: PredictionCard, lang: str) -> dict[str, Any]:
    answers = {
        a.qid: a
        for a in db.scalars(select(PredictionAnswer).where(PredictionAnswer.card_id == card.id))
    }
    return {
        "id": card.id,
        "save_id": card.save_id,
        "event_id": card.event_id,
        "event": events_service.event_out(db, save, card.event_id, lang),
        "status": card.status,
        "opened_trading_tick": card.opened_trading_tick,
        "opened_trading_day": card.opened_trading_day,
        "deadline_trading_tick": card.deadline_trading_tick,
        "window_days": card.window_days,
        "questions": list(card.questions),
        "answers": _answer_list(list(answers.values())),
        "results": _result_list(card, answers),
        "points": card.points,
        "points_capped": card.points_capped,
        "answered_at": card.answered_at,
        "settled_at": card.settled_at,
        "created_at": card.created_at,
    }


# ---------------------------------------------------------------- 统计（GET /points/stats）


def stats(
    db: Session, *, user_id: uuid.UUID, save_id: uuid.UUID | None, lang: str
) -> dict[str, Any]:
    stmt = select(PredictionCard).where(PredictionCard.user_id == user_id)
    if save_id is not None:
        stmt = stmt.where(PredictionCard.save_id == save_id)
    cards = list(db.scalars(stmt))
    card_ids = [c.id for c in cards]
    answers = (
        list(db.scalars(select(PredictionAnswer).where(PredictionAnswer.card_id.in_(card_ids))))
        if card_ids
        else []
    )
    by_card: dict[uuid.UUID, list[PredictionAnswer]] = {}
    for a in answers:
        by_card.setdefault(a.card_id, []).append(a)
    answered_cards = [c for c in cards if c.id in by_card]
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in ("bucket", "rank", "binary"):
        rows = [a for a in answers if a.kind == kind]
        scored = [a for a in rows if a.scored_at is not None]
        by_kind[kind] = {
            "answered": len(rows),
            "scored": len(scored),
            "avg_score": round_half_up_div(sum(a.score or 0 for a in scored), len(scored))
            if scored
            else None,
            "avg_baseline": round_half_up_div(sum(a.baseline or 0 for a in scored), len(scored))
            if scored
            else None,
        }
    prob = [a for a in answers if a.scored_at is not None and a.hit is not None]
    bins = calibration_bins((int(a.claimed_pct or 0), bool(a.hit)) for a in prob)
    calib = [
        {
            "lo_pct": b.lo_pct,
            "hi_pct": b.hi_pct,
            "n": b.n,
            "hits": b.hits,
            "avg_claimed_pct": round_half_up_div(b.claimed_sum, b.n) if b.n else None,
            "hit_rate_pct": round_half_up_div(100 * b.hits, b.n) if b.n else None,
        }
        for b in bins
    ]
    settled = [c for c in cards if c.status == "settled"]
    recent_cards = sorted(
        (c for c in settled if c.settled_at is not None),
        key=lambda c: (c.settled_at, c.id),
    )[-30:]
    recent = []
    for c in recent_cards:
        rows = [a for a in by_card.get(c.id, []) if a.scored_at is not None]
        recent.append(
            {
                "card_id": c.id,
                "event_id": c.event_id,
                "settled_at": c.settled_at,
                "avg_score": round_half_up_div(sum(a.score or 0 for a in rows), len(rows))
                if rows
                else None,
                "avg_baseline": round_half_up_div(sum(a.baseline or 0 for a in rows), len(rows))
                if rows
                else None,
                "points": c.points,
            }
        )
    return {
        "cards_answered": len(answered_cards),
        "cards_settled": len(settled),
        "cards_expired": sum(1 for c in cards if c.status == "expired"),
        "total_points": sum(int(c.points or 0) for c in settled),
        "by_kind": by_kind,
        "calibration": calib,
        "calibration_error_bp": calibration_error_bp(bins),
        "recent": recent,
    }


# ---------------------------------------------------------------- 服务层查询（供 C/D/E）


@dataclass(frozen=True)
class AnswerRecord:
    save_id: uuid.UUID
    user_id: uuid.UUID
    card_id: uuid.UUID
    event_id: str
    qid: str
    kind: str
    answer: Mapping[str, Any]
    answered_trading_tick: int
    score: int | None
    uniform_score: int | None
    baseline: int | None
    p_outcome_pct: int | None
    extra: dict[str, Any] = field(default_factory=dict)


def answers_for_event(
    db: Session, *, save_ids: Sequence[uuid.UUID], event_id: str
) -> list[AnswerRecord]:
    if not save_ids:
        return []
    rows = db.execute(
        select(PredictionAnswer, PredictionCard)
        .join(PredictionCard, PredictionCard.id == PredictionAnswer.card_id)
        .where(PredictionCard.save_id.in_(list(save_ids)), PredictionCard.event_id == event_id)
        .order_by(PredictionCard.save_id, PredictionAnswer.qid)
    ).all()
    out: list[AnswerRecord] = []
    for ans, card in rows:
        out.append(
            AnswerRecord(
                save_id=card.save_id,
                user_id=card.user_id,
                card_id=card.id,
                event_id=card.event_id,
                qid=ans.qid,
                kind=ans.kind,
                answer=dict(ans.answer),
                answered_trading_tick=int(card.answered_trading_tick or 0),
                score=ans.score,
                uniform_score=ans.uniform_score,
                baseline=ans.baseline,
                p_outcome_pct=ans.p_outcome_pct,
            )
        )
    return out
