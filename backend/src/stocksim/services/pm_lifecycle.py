"""预测市场生命周期（04 §3.5–§3.6、§5.1–§5.3、§5.6）。

materialize、sync_market、sync_challenge、sync_due、void_challenge。

状态机：scheduled → open → closed → resolved，任意非终态 → voided。
状态以公共 tt 为准，sync_market 连跳到应达状态。

事务约定：
- materialize / void_challenge 是挑战钩子（03 §1.3），运行在调用方事务内：不 commit，幂等。
- sync_market 自成事务，两阶段执行：
  1. 无锁阶段：做需要 I/O 的核对（事件指纹、结算涨跌幅）。
     registry.reference_change_bp 会推进 master 并 commit，
     因此必须在任何写入之前完成。结果只是一个 _Check，结算值确定，重试无副作用。
  2. 锁阶段：SELECT … FOR UPDATE（SQLite 忽略）后按 _Check 推进状态、开市、结算或作废，commit。
     并发冲突（StaleDataError/IntegrityError）整体回滚重做，最多 PM_MAX_ATTEMPTS 次。
- 事件只经挑战的 master 存档（A 的 events_for_days，include_unpublished=True）取得，D 不读取 seed；
  这里不调用 registry.challenge_events：它会先推进 master（commit），
  而 materialize 处于挑战生成事务中。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import timebase
from stocksim.domain.events.types import GameEvent
from stocksim.domain.prediction_market import (
    ContractContext,
    ContractSpec,
    contracts_for_challenge,
    resolve_bucket,
    resolve_rumor,
)
from stocksim.domain.prediction_market.constants import SHARE_PAYOUT_POINTS
from stocksim.domain.prediction_market.lmsr import b_for_subsidy, prices_ppm, subsidy_for
from stocksim.models import (
    Challenge,
    PredictionMarket,
    PredictionMarketOutcome,
    PredictionPosition,
    PredictionSettlement,
    Stock,
)
from stocksim.services import events as events_service
from stocksim.services import points as points_service
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import clock, registry, timeutil
from stocksim.services.challenges.registry import ChallengeInfo

logger = logging.getLogger(__name__)

PM_MAX_ATTEMPTS = 5
TERMINAL_STATUSES = ("resolved", "voided")
NON_TERMINAL_STATUSES = ("scheduled", "open", "closed")

# void_reason 取值（04 §3.5）
VOID_CHALLENGE_REVOKED = "challenge_revoked"
VOID_EVENT_MISMATCH = "event_mismatch"
VOID_DATA_UNAVAILABLE = "data_unavailable"
VOID_RULESET_CHANGED = "ruleset_changed"

SessionFactory = Callable[[], Session]


# ---------------------------------------------------------------- 纯辅助


def fingerprint(ev: GameEvent) -> str:
    """事件指纹：完整 GameEvent 的 repr 的 sha256（含隐藏字段）。只用于比对，永不外发（04 §6）。"""
    return hashlib.sha256(repr(ev).encode("utf-8")).hexdigest()


def outcome_keys(kind: str, n_outcomes: int) -> tuple[str, ...]:
    """选项 key：传闻 (deny, confirm)，分档 b0..b{n-1}（04 §3.2）。"""
    if kind == "rumor":
        return ("deny", "confirm")
    return tuple(f"b{i}" for i in range(n_outcomes))


def _question(spec: ContractSpec, stock_name: str | None) -> dict[str, Any]:
    return {
        "scope": spec.scope,
        "industry": spec.industry,
        "code": spec.code,
        "stock_name": stock_name,
        "from_day": spec.from_day,
        "to_day": spec.to_day,
        "edges_bp": list(spec.edges_bp),
    }


def spec_of(m: PredictionMarket) -> ContractSpec:
    """由市场行还原合约定义（结算判定用）。"""
    q = m.question
    return ContractSpec(
        kind=m.kind,  # type: ignore[arg-type]
        event_id=m.event_id,
        scope=q["scope"],
        industry=q["industry"],
        code=q["code"],
        from_day=q["from_day"],
        to_day=q["to_day"],
        edges_bp=tuple(q["edges_bp"]),
        n_outcomes=m.n_outcomes,
        prior_ppm=tuple(m.prior_ppm),
        open_tt=m.open_tt,
        close_tt=m.close_tt,
        resolve_tt=m.resolve_tt,
        close_public=m.close_public,
    )


def _subject(q: dict[str, Any]) -> str | None:
    """reference_change_bp / change_bp_for 的 subject：行业名、股票代码，市场为 None。"""
    if q["scope"] == "industry":
        return q["industry"]
    if q["scope"] == "stock":
        return q["code"]
    return None


def _ref(m: PredictionMarket) -> str:
    return f"market:{m.id}"


# ---------------------------------------------------------------- 读取


def info_for(db: Session, row: Challenge) -> ChallengeInfo:
    timeline = None if row.status == "void" else clock.timeline_of(db, row)
    return registry.info_of(row, timeline)


def _events_by_id(db: Session, row: Challenge) -> dict[str, GameEvent]:
    """挑战全部排期日的服务端完整事件（含未发布），按 event_id 索引。不 commit。"""
    master = registry.market_save_for(db, row)
    last_day = timebase(row.clock_rules).day_of(row.end_tt)
    evs = events_service.events_for_days(db, master, 0, last_day, include_unpublished=True)
    return {ev.event_id: ev for ev in evs}


def _stock_name(db: Session, code: str | None) -> str | None:
    if code is None:
        return None
    return db.scalar(select(Stock.name).where(Stock.code == code))


def lock_market(db: Session, market_id: uuid.UUID) -> PredictionMarket | None:
    return db.scalar(
        select(PredictionMarket)
        .where(PredictionMarket.id == market_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _outcomes(db: Session, m: PredictionMarket) -> list[PredictionMarketOutcome]:
    return list(
        db.scalars(
            select(PredictionMarketOutcome)
            .where(PredictionMarketOutcome.market_id == m.id)
            .order_by(PredictionMarketOutcome.idx)
        )
    )


def _positions_by_user(
    db: Session, m: PredictionMarket
) -> list[tuple[uuid.UUID, list[PredictionPosition]]]:
    """按 user_id 升序分组的持仓行（结算与作废按此顺序逐个入账）。"""
    rows = db.scalars(
        select(PredictionPosition)
        .where(PredictionPosition.market_id == m.id)
        .order_by(PredictionPosition.user_id, PredictionPosition.outcome_idx)
    ).all()
    groups: dict[uuid.UUID, list[PredictionPosition]] = {}
    for row in rows:
        groups.setdefault(row.user_id, []).append(row)
    return sorted(groups.items(), key=lambda item: item[0])


# ---------------------------------------------------------------- 物化（挑战钩子，不 commit）


def materialize(db: Session, info: ChallengeInfo) -> int:
    """挑战的全部市场（scheduled，API 不可见）。

    on_created 钩子与 sweeper 共用；幂等（按 event_id+kind 跳过已有）。

    返回新建的市场数。调用方负责事务边界（钩子内不 commit）。
    """
    row = db.get(Challenge, info.id)
    if row is None or row.status == "void":
        return 0
    existing = set(
        db.execute(
            select(PredictionMarket.event_id, PredictionMarket.kind).where(
                PredictionMarket.challenge_id == row.id
            )
        ).all()
    )
    rounds = registry.round_event_ids(db, row)
    events = _events_by_id(db, row)
    ctx = ContractContext(
        clock_rules=row.clock_rules,
        first_tt=info.first_tt,
        last_tt=row.end_tt,
        structure=predictions_service.structure_for(row.events_ruleset),
    )
    specs = contracts_for_challenge(events.values(), ctx, round_event_ids=rounds)
    now = timeutil.now()
    created = 0
    for spec in specs:
        if (spec.event_id, spec.kind) in existing:
            continue
        ev = events[spec.event_id]
        m = PredictionMarket(
            id=uuid.uuid4(),
            challenge_id=row.id,
            event_id=spec.event_id,
            kind=spec.kind,
            status="scheduled",
            question=_question(spec, _stock_name(db, spec.code)),
            n_outcomes=spec.n_outcomes,
            prior_ppm=list(spec.prior_ppm),
            events_ruleset=row.events_ruleset,
            event_fingerprint=fingerprint(ev),
            open_tt=spec.open_tt,
            close_tt=spec.close_tt,
            resolve_tt=spec.resolve_tt,
            close_public=spec.close_public,
            created_at=now,
            updated_at=now,
        )
        db.add(m)
        db.flush()
        for idx, key in enumerate(outcome_keys(spec.kind, spec.n_outcomes)):
            db.add(
                PredictionMarketOutcome(
                    id=uuid.uuid4(), market_id=m.id, idx=idx, key=key, q0_shares=0, q_shares=0
                )
            )
        created += 1
    db.flush()
    return created


def void_challenge(db: Session, info: ChallengeInfo, reason: str) -> int:
    """挑战作废钩子（03 §1.3，reason 为 C 的作废原因）：所有非终态市场按 challenge_revoked 作废。

    不 commit，幂等（终态市场跳过）。返回作废的市场数。
    """
    del reason  # 市场侧统一记 challenge_revoked（04 §3.5）
    ids = db.scalars(
        select(PredictionMarket.id).where(
            PredictionMarket.challenge_id == info.id,
            PredictionMarket.status.in_(NON_TERMINAL_STATUSES),
        )
    ).all()
    now = timeutil.now()
    voided = 0
    for market_id in ids:
        m = lock_market(db, market_id)
        if m is None or m.status in TERMINAL_STATUSES:
            continue
        _void(db, m, VOID_CHALLENGE_REVOKED, now)
        voided += 1
    return voided


# ---------------------------------------------------------------- 核对（无锁阶段，可 commit）


@dataclass(frozen=True)
class _Check:
    """无锁阶段的核对结果。void_reason 非空即作废；winning 非空即可结算。"""

    void_reason: str | None = None
    winning: int | None = None
    value_bp: int | None = None


def _verify(db: Session, row: Challenge, m: PredictionMarket, *, resolve_due: bool) -> _Check:
    """开市与结算前的重算核对（04 §3.5）。可能 commit（reference_change_bp 推进 master）。"""
    if row.events_ruleset != m.events_ruleset:
        return _Check(void_reason=VOID_RULESET_CHANGED)
    ev = _events_by_id(db, row).get(m.event_id)
    if ev is None or fingerprint(ev) != m.event_fingerprint:
        return _Check(void_reason=VOID_EVENT_MISMATCH)
    if not resolve_due:
        return _Check()
    if m.kind == "rumor":
        return _Check(winning=resolve_rumor(ev))
    q = m.question
    value = registry.reference_change_bp(
        db, row, q["scope"], _subject(q), q["from_day"], m.resolve_tt
    )
    if value is None:
        return _Check(void_reason=VOID_DATA_UNAVAILABLE)
    return _Check(winning=resolve_bucket(spec_of(m), value), value_bp=value)


# ---------------------------------------------------------------- 状态迁移（锁阶段，不 commit）


def _open(db: Session, m: PredictionMarket, row: Challenge, now: datetime) -> None:
    """scheduled → open：记补贴发行 S，定 b 与 q0，写选项份额（只发生一次，04 §3.6、§4.4）。"""
    s = subsidy_for(registry.expected_participants(db, row))
    b_milli, q0 = b_for_subsidy(s, m.prior_ppm)
    m.status = "open"
    m.subsidy_points = s
    m.liquidity_b_milli = b_milli
    m.pool_points = s
    m.prices_ppm = list(prices_ppm(q0, b_milli))
    m.opened_at = now
    for out in _outcomes(db, m):
        out.q0_shares = q0[out.idx]
        out.q_shares = q0[out.idx]


def _resolve(db: Session, m: PredictionMarket, check: _Check, now: datetime) -> None:
    """closed → resolved：按获胜选项兑付，剩余池记入 subsidy_returned_points（04 §3.4、§5.2）。

    所有入账在同一事务内按 user_id 升序完成。池余额理论上不为负（04 §4.4 最大亏损证明）；
    为负只说明有 bug，记日志，差额照常写入（负值）。
    """
    winning = check.winning
    assert winning is not None
    total_payout = 0
    for user_id, rows in _positions_by_user(db, m):
        bought = sum(r.bought_points for r in rows)
        sold = sum(r.sold_points for r in rows)
        net = bought - sold
        win_shares = sum(r.shares for r in rows if r.outcome_idx == winning)
        payout = SHARE_PAYOUT_POINTS * win_shares
        if payout > 0:
            points_service.credit(
                db,
                user_id=user_id,
                delta=payout,
                reason="market_payout",
                ref=_ref(m),
                idempotency_key=f"market_payout:{m.id}:{user_id}",
            )
        db.add(
            PredictionSettlement(
                id=uuid.uuid4(),
                market_id=m.id,
                user_id=user_id,
                kind="resolved",
                winning_shares=win_shares,
                payout_points=payout,
                net_cost_points=net,
                pnl_points=payout - net,
                created_at=now,
            )
        )
        total_payout += payout
    remaining = m.pool_points - total_payout
    if remaining < 0:
        logger.error("prediction market pool negative after payout: market=%s", m.id)
    m.subsidy_returned_points = remaining
    m.pool_points = 0
    m.status = "resolved"
    m.winning_outcome = winning
    m.resolution_value_bp = check.value_bp
    m.resolved_at = now


def _void(db: Session, m: PredictionMarket, reason: str, now: datetime) -> None:
    """任意非终态 → voided。

    每人退 max(0, 净投入)，池余额（可为负）记入 subsidy_returned_points（04 §3.5）。
    """
    total_refund = 0
    for user_id, rows in _positions_by_user(db, m):
        bought = sum(r.bought_points for r in rows)
        sold = sum(r.sold_points for r in rows)
        net = bought - sold
        refund = max(0, net)
        if refund > 0:
            points_service.credit(
                db,
                user_id=user_id,
                delta=refund,
                reason="market_refund",
                ref=_ref(m),
                idempotency_key=f"market_refund:{m.id}:{user_id}",
            )
        db.add(
            PredictionSettlement(
                id=uuid.uuid4(),
                market_id=m.id,
                user_id=user_id,
                kind="voided",
                winning_shares=0,
                payout_points=refund,
                net_cost_points=net,
                pnl_points=refund - net,
                created_at=now,
            )
        )
        total_refund += refund
    m.subsidy_returned_points = m.pool_points - total_refund
    m.pool_points = 0
    m.status = "voided"
    m.void_reason = reason


def _advance_locked(
    db: Session,
    m: PredictionMarket,
    row: Challenge,
    ptt: int,
    check: _Check | None,
    now: datetime,
) -> bool:
    """锁内按公共 tt 连跳状态。

    check 为无锁阶段的核对结果（None 表示本轮不需要核对）。返回是否变化。
    """
    if m.status in TERMINAL_STATUSES:
        return False
    if check is not None and check.void_reason is not None:
        _void(db, m, check.void_reason, now)
        return True
    changed = False
    if m.status == "scheduled" and ptt >= m.open_tt:
        _open(db, m, row, now)
        changed = True
    if m.status == "open" and ptt >= m.close_tt:
        m.status = "closed"
        changed = True
    if (
        m.status == "closed"
        and ptt >= m.resolve_tt
        and check is not None
        and check.winning is not None
    ):
        _resolve(db, m, check, now)
        changed = True
    return changed


def public_tt(info: ChallengeInfo, row: Challenge, now: datetime) -> int:
    """公共 tt。挑战已结算时视为走到 last_tt+1，使传闻在 min(r, last+1) 处可结算（04 §3.3）。"""
    ptt = registry.public_trading_tick(info, now)
    if row.status == "settled":
        ptt = max(ptt, info.last_tt + 1)
    return ptt


# ---------------------------------------------------------------- 对外：同步


def sync_market(db: Session, market_id: uuid.UUID, now: datetime | None = None) -> bool:
    """把市场推进到公共 tt 应达的状态。自成事务；返回本次是否发生状态变化。幂等。"""
    now = now or timeutil.now()
    for _ in range(PM_MAX_ATTEMPTS):
        try:
            return _sync_once(db, market_id, now)
        except (StaleDataError, IntegrityError):
            db.rollback()
    raise AppError(ErrorCode.PM_BUSY, {"market_id": str(market_id)})


def _sync_once(db: Session, market_id: uuid.UUID, now: datetime) -> bool:
    m = db.get(PredictionMarket, market_id)
    if m is None or m.status in TERMINAL_STATUSES:
        return False
    row = db.get(Challenge, m.challenge_id)
    if row is None:
        return False
    if row.status == "void":
        # 挑战无时间线：直接按撤销作废（钩子通常已做，这里兜底）
        return _commit_locked(
            db, market_id, row, 0, _Check(void_reason=VOID_CHALLENGE_REVOKED), now
        )
    info = info_for(db, row)
    ptt = public_tt(info, row, now)
    open_due = m.status == "scheduled" and ptt >= m.open_tt
    resolve_due = ptt >= m.resolve_tt
    if not (open_due or resolve_due or (m.status == "open" and ptt >= m.close_tt)):
        return False
    check = _verify(db, row, m, resolve_due=resolve_due) if (open_due or resolve_due) else None
    return _commit_locked(db, market_id, row, ptt, check, now)


def _commit_locked(
    db: Session,
    market_id: uuid.UUID,
    row: Challenge,
    ptt: int,
    check: _Check | None,
    now: datetime,
) -> bool:
    m = lock_market(db, market_id)
    if m is None:
        db.rollback()
        return False
    changed = _advance_locked(db, m, row, ptt, check, now)
    db.commit()
    return changed


def void_market(db: Session, market_id: uuid.UUID, reason: str) -> bool:
    """人工作废（调试接口，04 §3.5 的 manual）。非终态才生效，自成事务。返回是否作废。"""
    now = timeutil.now()
    for _ in range(PM_MAX_ATTEMPTS):
        try:
            m = lock_market(db, market_id)
            if m is None or m.status in TERMINAL_STATUSES:
                db.rollback()
                return False
            _void(db, m, reason[:32], now)
            db.commit()
            return True
        except (StaleDataError, IntegrityError):
            db.rollback()
    raise AppError(ErrorCode.PM_BUSY, {"market_id": str(market_id)})


def sync_challenge(db: Session, challenge_id: uuid.UUID, now: datetime | None = None) -> int:
    """挑战内所有非终态市场逐个同步（列表读取前调用）。返回变化的市场数。"""
    now = now or timeutil.now()
    ids = db.scalars(
        select(PredictionMarket.id).where(
            PredictionMarket.challenge_id == challenge_id,
            PredictionMarket.status.in_(NON_TERMINAL_STATUSES),
        )
    ).all()
    return sum(1 for market_id in ids if sync_market(db, market_id, now))


def sync_due(session_factory: SessionFactory, now: datetime | None = None) -> int:
    """后台 sweeper（04 §8.1）：live 挑战物化（幂等）+ 所有非终态市场逐个同步。与有无 WS 连接无关。

    每个市场、每个挑战各用一个会话与事务，单步失败记日志后继续。返回变化的市场数。
    """
    now = now or timeutil.now()
    with session_factory() as db:
        infos = registry.live_challenges(db, now)
    for info in infos:
        with session_factory() as db:
            try:
                materialize(db, info)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("materialize failed: challenge=%s", info.id)
    with session_factory() as db:
        market_ids: Sequence[uuid.UUID] = db.scalars(
            select(PredictionMarket.id).where(PredictionMarket.status.in_(NON_TERMINAL_STATUSES))
        ).all()
    changed = 0
    for market_id in market_ids:
        with session_factory() as db:
            try:
                changed += int(sync_market(db, market_id, now))
            except Exception:
                db.rollback()
                logger.exception("sync_market failed: market=%s", market_id)
    return changed


__all__ = [
    "NON_TERMINAL_STATUSES",
    "PM_MAX_ATTEMPTS",
    "TERMINAL_STATUSES",
    "fingerprint",
    "info_for",
    "lock_market",
    "materialize",
    "outcome_keys",
    "public_tt",
    "spec_of",
    "sync_challenge",
    "sync_due",
    "sync_market",
    "void_challenge",
    "void_market",
]
