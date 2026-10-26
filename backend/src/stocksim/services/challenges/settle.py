"""结算（03 §7.6、§8）：算终局权益与收益、交易分、总分、竞赛排名，发奖，最后置 settled。

流程（settle_if_due，幂等）：
1. 前置：status=='running' 且 now ≥ ends_at；先把 master 推到 tt(now)（到 end_tt）；
   master tt == end_tt 且全部回合 resolved_at 非空，否则返回 False。
2. 只读计算（_compute）：每个报名的终局权益、return_bp、成交数、预测分、交易分、总分；
   合格者竞赛排名与奖励。
3. 分批写入（每 SETTLE_BATCH 人一个事务）：成绩字段 + points.credit（reason=challenge）。
   批次可重跑：积分靠幂等键 challenge:{cid}:{uid} 兜底，成绩字段是确定值。
4. 最后一个事务：run_settled 钩子（写 status 之前）→ status=settled、settled_at=revealed_at=now。
   status 最后才改；已非 running（另一实例已结算）则返回 False。

日志不记 seed、盐、commitment_input（03 §5 #11）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.constants import (
    CHALLENGE_PEER_MIN,
)
from stocksim.domain.challenge.ranking import competition_ranks, reward_points
from stocksim.domain.challenge.scoring import trade_scores
from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.models import (
    Challenge,
    ChallengeAnswer,
    ChallengeEntry,
    ChallengeRound,
    Save,
    Trade,
)
from stocksim.services import equity as equity_service
from stocksim.services import market as market_service
from stocksim.services import points
from stocksim.services.challenges import hooks, registry, sync
from stocksim.services.tx import run_in_transaction

logger = logging.getLogger(__name__)

SETTLE_BATCH = 200  # 每个写入事务的报名人数（03 §7.6）
REWARD_REASON = "challenge"


@dataclass(frozen=True)
class EntryOutcome:
    """单个报名的结算结果（只读计算的产物，批次写入时原样落库）。"""

    entry_id: uuid.UUID
    user_id: uuid.UUID
    challenge_date: str
    eligible: bool
    rewardable: bool
    final_equity_cents: int
    return_bp: int
    trade_count: int
    forecast_score: int
    trade_score: int
    total_score: int
    rank: int | None
    reward: int


def settle_if_due(db: Session, ch: Challenge, now: datetime) -> bool:
    """结算到期的挑战（03 §7.6）。返回本次是否完成结算；未到期、已结算或作废返回 False。幂等。"""
    row = db.get(Challenge, ch.id)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(ch.id)})
    if row.status != "running" or _aware(row.ends_at) > now:
        return False
    sync.advance_master(db, row, now)  # 推到 tt(now)，即 end_tt（已 commit）
    db.refresh(row)
    if row.status != "running":
        return False
    master = registry.market_save_for(db, row)
    if market_service.current_trading_tick(db, master) != row.end_tt:
        return False
    rounds = registry.rounds_of(db, row)
    if any(r.resolved_at is None for r in rounds):
        return False

    outcomes, eligible_count = _compute(db, row, master)
    for start in range(0, len(outcomes), SETTLE_BATCH):
        batch = outcomes[start : start + SETTLE_BATCH]
        run_in_transaction(db, lambda b=batch: _write_batch(db, row.id, b, now))
    done = run_in_transaction(db, lambda: _finalize(db, row.id, eligible_count, now))
    if done:
        logger.info(
            "challenge settled: date=%s eligible=%d entries=%d",
            row.challenge_date.isoformat(),
            eligible_count,
            len(outcomes),
        )
    return done


def _compute(db: Session, row: Challenge, master: Save) -> tuple[list[EntryOutcome], int]:
    """只读计算全部报名的结算结果。返回 (结果列表, 合格人数)。"""
    entries = list(
        db.scalars(
            select(ChallengeEntry)
            .where(ChallengeEntry.challenge_id == row.id)
            .order_by(ChallengeEntry.joined_at, ChallengeEntry.id)
        )
    )
    state, _ = market_service.load_market(db, master)
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    forecast = {
        entry_id: int(total or 0)
        for entry_id, total in db.execute(
            select(ChallengeAnswer.entry_id, func.sum(ChallengeAnswer.round_score))
            .join(ChallengeRound, ChallengeRound.id == ChallengeAnswer.round_id)
            .where(ChallengeRound.challenge_id == row.id)
            .group_by(ChallengeAnswer.entry_id)
        ).all()
    }

    equities: list[int] = []
    returns: list[int] = []
    trades: list[int] = []
    for entry in entries:
        save = _save_of(db, entry)
        holdings = equity_service.holding_quantities(db, save.id)
        market_value = 0
        for code, qty in holdings.items():
            if code not in prices:
                raise RuntimeError(f"no master price for held stock {code}")
            market_value += qty * prices[code]
        equity = save.cash_cents + market_value
        equities.append(equity)
        returns.append(
            round_half_up_div(
                (equity - save.initial_fund_cents) * BP_DENOMINATOR, save.initial_fund_cents
            )
        )
        trades.append(
            int(db.scalar(select(func.count(Trade.id)).where(Trade.save_id == save.id)) or 0)
        )

    eligible = [e.eligible for e in entries]
    trade_pts = trade_scores(returns, eligible, peer_min=CHALLENGE_PEER_MIN)
    totals = [forecast.get(e.id, 0) + trade_pts[i] for i, e in enumerate(entries)]

    elig_idx = [i for i, ok in enumerate(eligible) if ok]
    eligible_count = len(elig_idx)
    ranks: list[int | None] = [None] * len(entries)
    for i, rank in zip(elig_idx, competition_ranks([totals[i] for i in elig_idx]), strict=True):
        ranks[i] = rank

    outcomes: list[EntryOutcome] = []
    for i, entry in enumerate(entries):
        rewardable = bool(eligible[i]) and (entry.answered_rounds >= 1 or trades[i] > 0)
        reward = reward_points(ranks[i], eligible_count) if rewardable else 0
        outcomes.append(
            EntryOutcome(
                entry_id=entry.id,
                user_id=entry.user_id,
                challenge_date=row.challenge_date.isoformat(),
                eligible=bool(eligible[i]),
                rewardable=rewardable,
                final_equity_cents=equities[i],
                return_bp=returns[i],
                trade_count=trades[i],
                forecast_score=forecast.get(entry.id, 0),
                trade_score=trade_pts[i],
                total_score=totals[i],
                rank=ranks[i],
                reward=reward,
            )
        )
    return outcomes, eligible_count


def _save_of(db: Session, entry: ChallengeEntry) -> Save:
    save = db.get(Save, entry.save_id) if entry.save_id is not None else None
    if save is None:
        # 结算前玩家存档不会被清理（03 §6.3 仅在 settled_at 之后删除），缺失即数据损坏
        raise RuntimeError(f"challenge entry {entry.id} has no player save")
    return save


def _write_batch(
    db: Session, challenge_id: uuid.UUID, batch: Sequence[EntryOutcome], now: datetime
) -> None:
    """一个批次的写入（不 commit，由 run_in_transaction 提交）：成绩字段 + 积分入账。"""
    for out in batch:
        entry = db.get(ChallengeEntry, out.entry_id)
        if entry is None:
            raise RuntimeError(f"challenge entry {out.entry_id} vanished during settlement")
        entry.final_equity_cents = out.final_equity_cents
        entry.return_bp = out.return_bp
        entry.trade_count = out.trade_count
        entry.forecast_score = out.forecast_score
        entry.trade_score = out.trade_score
        entry.total_score = out.total_score
        entry.rank = out.rank
        entry.points_awarded = out.reward
        entry.settled_at = now
        if out.reward > 0:  # 0 不入账，points_awarded=0 已留痕
            points.credit(
                db,
                user_id=out.user_id,
                delta=out.reward,
                reason=REWARD_REASON,
                ref=f"challenge:{out.challenge_date}",
                idempotency_key=f"challenge:{challenge_id}:{out.user_id}",
                save_id=None,
                meta={"rank": out.rank, "total_score": out.total_score},
            )


def _finalize(db: Session, challenge_id: uuid.UUID, eligible_count: int, now: datetime) -> bool:
    """最后事务：钩子（写 status 之前）→ status=settled。已非 running 返回 False。"""
    row = db.get(Challenge, challenge_id)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(challenge_id)})
    if row.status != "running":
        return False
    row.eligible_count = eligible_count
    hooks.run_settled(db, row)
    row.status = "settled"
    row.settled_at = now
    row.revealed_at = now
    db.flush()  # 乐观锁冲突在此抛 StaleDataError，由 run_in_transaction 重做
    return True


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["SETTLE_BATCH", "EntryOutcome", "settle_if_due"]
