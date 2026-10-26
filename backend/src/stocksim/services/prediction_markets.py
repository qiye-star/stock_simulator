"""预测市场服务（模式 D，04 §5.1、§5.4、§5.5、§9）。

报价、下单、列表与详情视图、历史与成交带、我的持仓与结算、收益榜。

下单事务（§5.1）：先 sync（推进状态，自成事务），再 lock 市场行，
锁内完成状态、超前、频率、额度与滑点判定；积分 debit/credit 与市场、持仓、成交写入同一事务提交。
乐观锁冲突或幂等键唯一冲突整体回滚重做。
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import timebase
from stocksim.domain.errors import DomainError
from stocksim.domain.money import round_half_up_div
from stocksim.domain.prediction_market import (
    CHALLENGE_BUY_CAP_POINTS,
    MAX_SHARES_PER_TRADE,
    POINTS_PER_SHARE,
    PRICE_PPM_TOTAL,
    SHARE_PAYOUT_POINTS,
    LimitState,
    check_trade,
    market_cap_points,
    max_shares_for_budget,
    prices_ppm,
    quote,
)
from stocksim.domain.prediction_market.constants import RATE_LIMIT_TRADES, RATE_LIMIT_WINDOW_S
from stocksim.models import (
    Challenge,
    PredictionMarket,
    PredictionMarketOutcome,
    PredictionPosition,
    PredictionSettlement,
    PredictionTrade,
    Stock,
    User,
)
from stocksim.services import pm_lifecycle
from stocksim.services import points as points_service
from stocksim.services.challenges import config as challenge_config
from stocksim.services.challenges import registry, timeutil
from stocksim.services.challenges.registry import ChallengeInfo

PM_MAX_ATTEMPTS = pm_lifecycle.PM_MAX_ATTEMPTS
PUBLIC_STATUSES = ("open", "closed", "resolved", "voided")
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class TradeOrder:
    """下单参数（已由 schema 形状校验；这里做业务组合校验）。"""

    side: Side
    outcome: int
    shares: int | None = None
    budget_points: int | None = None
    max_cost_points: int | None = None
    min_proceeds_points: int | None = None


# ---------------------------------------------------------------- 游标与小工具


def _encode_cursor(parts: list[Any]) -> str:
    raw = json.dumps(parts, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, n: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parts = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(parts, list) or len(parts) != n:
            raise ValueError
        return parts
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _uuid_or_422(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


def _ref(market_id: uuid.UUID) -> str:
    return f"market:{market_id}"


def _half_up(numerator: int, denominator: int) -> int:
    return round_half_up_div(numerator, denominator)


def _value_points(shares: int, price_ppm: int) -> int:
    """份额按现价折算的积分：shares · price_ppm · 100 / 1e6，四舍五入（04 §9.2）。"""
    return _half_up(shares * price_ppm * POINTS_PER_SHARE, PRICE_PPM_TOTAL)


def _domain_to_app(exc: DomainError) -> AppError:
    return AppError(ErrorCode(exc.code), exc.params)


def _validate(order: TradeOrder, n_outcomes: int) -> None:
    if order.side not in ("buy", "sell"):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "side"})
    if not 0 <= order.outcome < n_outcomes:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "outcome"})
    if order.side == "buy":
        if (order.shares is None) == (order.budget_points is None):
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "shares"})
        if order.budget_points is not None and order.budget_points < 1:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "budget_points"})
        if order.min_proceeds_points is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "min_proceeds_points"})
    else:
        if order.shares is None or order.budget_points is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "shares"})
        if order.max_cost_points is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "max_cost_points"})
    if order.shares is not None and not 1 <= order.shares <= MAX_SHARES_PER_TRADE:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "shares"})


# ---------------------------------------------------------------- 读取辅助


def _market(db: Session, market_id: uuid.UUID) -> PredictionMarket:
    m = db.get(PredictionMarket, market_id, populate_existing=True)
    if m is None or m.status == "scheduled":
        raise AppError(ErrorCode.PM_NOT_FOUND, {"market_id": str(market_id)})
    return m


def _prepare(
    db: Session, market_id: uuid.UUID, now: datetime
) -> tuple[PredictionMarket, Challenge, ChallengeInfo, int]:
    """sync（推进到公共 tt）后读取市场、挑战与公共 tt。不加锁。"""
    pm_lifecycle.sync_market(db, market_id, now)
    m = _market(db, market_id)
    row = db.get(Challenge, m.challenge_id)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(m.challenge_id)})
    info = pm_lifecycle.info_for(db, row)
    ptt = pm_lifecycle.public_tt(info, row, now)
    return m, row, info, ptt


def _effective_status(m: PredictionMarket, ptt: int) -> str:
    """交易视角的状态：open 但已到关市 tick 视为 closed（sweeper 尚未迁移时）。"""
    if m.status == "open" and ptt >= m.close_tt:
        return "closed"
    return m.status


def _positions(db: Session, m: PredictionMarket, user_id: uuid.UUID) -> list[PredictionPosition]:
    return list(
        db.scalars(
            select(PredictionPosition)
            .where(
                PredictionPosition.market_id == m.id,
                PredictionPosition.user_id == user_id,
            )
            .order_by(PredictionPosition.outcome_idx)
        )
    )


def _outcomes(db: Session, m: PredictionMarket) -> list[PredictionMarketOutcome]:
    return list(
        db.scalars(
            select(PredictionMarketOutcome)
            .where(PredictionMarketOutcome.market_id == m.id)
            .order_by(PredictionMarketOutcome.idx)
        )
    )


def _account_eligible(user: User, now: datetime) -> bool:
    hours = challenge_config.current_settings().CHALLENGE_MIN_ACCOUNT_AGE_HOURS
    return _aware(user.created_at) <= now - timedelta(hours=hours)


def _challenge_buy_points(db: Session, row: Challenge, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(PredictionPosition.bought_points), 0))
            .join(PredictionMarket, PredictionPosition.market_id == PredictionMarket.id)
            .where(
                PredictionMarket.challenge_id == row.id,
                PredictionPosition.user_id == user_id,
            )
        )
        or 0
    )


def _market_net_cost(rows: Sequence[PredictionPosition]) -> int:
    return sum(r.bought_points - r.sold_points for r in rows)


def _held(rows: Sequence[PredictionPosition], outcome: int) -> int:
    for r in rows:
        if r.outcome_idx == outcome:
            return r.shares
    return 0


# ---------------------------------------------------------------- 视图


def _event_ref(
    db: Session, user: User, row: Challenge, m: PredictionMarket, ptt: int
) -> dict[str, Any]:
    at = max(0, min(ptt, m.resolve_tt if m.status == "resolved" else ptt))
    try:
        ev = registry.public_event(db, row, m.event_id, user.lang, at)
    except ValueError:
        ev = None
    if ev is None:
        q = m.question or {}
        return {
            "event_id": m.event_id,
            "kind": m.kind,
            "scope": q.get("scope"),
            "major": True,
            "sentiment": None,
            "title": "",
            "first_seen_trading_tick": m.open_tt,
            "rumor_status": None,
        }
    return {
        "event_id": ev["event_id"],
        "kind": ev["kind"],
        "scope": ev["scope"],
        "major": ev["major"],
        "sentiment": ev["sentiment"],
        "title": ev["title"],
        "first_seen_trading_tick": ev["first_seen_trading_tick"],
        "rumor_status": ev.get("rumor_status"),
    }


def _times(info: ChallengeInfo, m: PredictionMarket) -> dict[str, Any]:
    """开/关/结算的 tick 与真实时间。传闻在 open 状态隐藏 close/resolve（04 §3.3）。"""
    hidden = m.kind == "rumor" and m.status == "open"
    if hidden:
        return {
            "close_tt": None,
            "resolve_tt": None,
            "opens_at": registry.real_time_of(info, m.open_tt),
            "closes_at": None,
            "resolves_at": None,
        }
    return {
        "close_tt": m.close_tt,
        "resolve_tt": m.resolve_tt,
        "opens_at": registry.real_time_of(info, m.open_tt),
        "closes_at": registry.real_time_of(info, m.close_tt),
        "resolves_at": registry.real_time_of(info, m.resolve_tt),
    }


def market_out(
    db: Session,
    user: User,
    row: Challenge,
    info: ChallengeInfo,
    m: PredictionMarket,
    ptt: int,
    *,
    my_shares: list[int] | None,
) -> dict[str, Any]:
    """PmMarketOut（04 §9.2）。不含 event_fingerprint、隐藏事件字段与 scheduled 市场。"""
    q = m.question or {}
    prices = list(m.prices_ppm or [])
    return {
        "id": m.id,
        "challenge_id": m.challenge_id,
        "event_id": m.event_id,
        "kind": m.kind,
        "status": m.status,
        "question": {
            "scope": q.get("scope"),
            "industry": q.get("industry"),
            "code": q.get("code"),
            "stock_name": q.get("stock_name"),
            "from_day": q.get("from_day"),
            "to_day": q.get("to_day"),
            "edges_bp": list(q.get("edges_bp", [])),
        },
        "event": _event_ref(db, user, row, m, ptt),
        "outcomes": [
            {"idx": i, "key": o.key, "price_ppm": prices[i] if i < len(prices) else 0}
            for i, o in enumerate(_outcomes(db, m))
        ],
        "open_tt": m.open_tt,
        **_times(info, m),
        "trade_seq": m.trade_seq,
        "volume_shares": m.volume_shares,
        "traders": m.traders,
        "liquidity_b_milli": m.liquidity_b_milli,
        "subsidy_points": m.subsidy_points,
        "winning_outcome": m.winning_outcome,
        "resolution_value_bp": m.resolution_value_bp,
        "void_reason": m.void_reason,
        "my_shares": my_shares,
    }


def _my_shares(db: Session, m: PredictionMarket, user_id: uuid.UUID | None) -> list[int] | None:
    if user_id is None:
        return None
    rows = _positions(db, m, user_id)
    if not rows:
        return None
    n = m.n_outcomes
    return [_held(rows, i) for i in range(n)]


def my_position_out(db: Session, m: PredictionMarket, user_id: uuid.UUID) -> dict[str, Any] | None:
    """PmMyPositionOut。

    value：open/closed 按现价，resolved 按兑付，voided 按退款（净投入正部分）。
    """
    rows = _positions(db, m, user_id)
    if not rows:
        return None
    bought = sum(r.bought_points for r in rows)
    sold = sum(r.sold_points for r in rows)
    net = bought - sold
    prices = list(m.prices_ppm or [])
    outs: list[dict[str, Any]] = []
    value_total = 0
    for r in rows:
        if m.status == "resolved":
            value = SHARE_PAYOUT_POINTS * r.shares if r.outcome_idx == m.winning_outcome else 0
        elif m.status == "voided":
            value = 0
        else:
            value = (
                _value_points(r.shares, prices[r.outcome_idx]) if r.outcome_idx < len(prices) else 0
            )
        value_total += value
        outs.append(
            {
                "idx": r.outcome_idx,
                "shares": r.shares,
                "cost_points": r.cost_points,
                "value_points": value,
            }
        )
    if m.status == "voided":
        value_total = max(0, net)
    return {
        "outcomes": outs,
        "bought_points": bought,
        "sold_points": sold,
        "net_cost_points": net,
        "value_points": value_total,
        "pnl_points": value_total - net,
    }


def _limits(
    db: Session,
    user: User,
    row: Challenge,
    m: PredictionMarket,
    ptt: int,
    now: datetime,
) -> dict[str, Any]:
    rows = _positions(db, m, user.id)
    return {
        "market_net_cost_cap_points": market_cap_points(m.subsidy_points),
        "market_net_cost_used_points": _market_net_cost(rows),
        "challenge_buy_cap_points": CHALLENGE_BUY_CAP_POINTS,
        "challenge_buy_used_points": _challenge_buy_points(db, row, user.id),
        "locked_ahead": _locked_ahead(db, user, row, ptt),
        "eligible": _account_eligible(user, now),
    }


def _locked_ahead(db: Session, user: User, row: Challenge, ptt: int) -> bool:
    kt = registry.knowledge_trading_tick(db, user.id, row)
    return kt is not None and kt > ptt


def _window_change_bp(db: Session, row: Challenge, m: PredictionMarket, ptt: int) -> int | None:
    if m.kind != "bucket" or m.status == "voided":
        return None
    q = m.question or {}
    scope = q["scope"]
    subject = (
        q.get("industry") if scope == "industry" else q.get("code") if scope == "stock" else None
    )
    upto = min(ptt, m.resolve_tt)
    try:
        return registry.reference_change_bp(db, row, scope, subject, q["from_day"], upto)
    except ValueError:
        return None


# ---------------------------------------------------------------- 公共时钟与列表


def public_clock(db: Session, row: Challenge, now: datetime) -> dict[str, Any]:
    info = pm_lifecycle.info_for(db, row)
    ptt = pm_lifecycle.public_tt(info, row, now)
    return {
        "challenge_id": row.id,
        "public_trading_tick": ptt,
        "public_trading_day": timebase(row.clock_rules).day_of(ptt),
        "server_time": now,
    }


def _challenge_for(db: Session, challenge_id: uuid.UUID | None, now: datetime) -> Challenge:
    if challenge_id is not None:
        row = db.get(Challenge, challenge_id)
        if row is None:
            raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(challenge_id)})
        return row
    row = registry.current_challenge(db, now)
    if row is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": None})
    return row


def list_markets(
    db: Session,
    user: User,
    *,
    challenge_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    cursor: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """PmMarketPageOut：排序 (open_tt 降序, id 升序)，永不含 scheduled。"""
    now = now or timeutil.now()
    row = _challenge_for(db, challenge_id, now)
    pm_lifecycle.sync_challenge(db, row.id, now)
    info = pm_lifecycle.info_for(db, row)
    ptt = pm_lifecycle.public_tt(info, row, now)
    stmt = select(PredictionMarket).where(PredictionMarket.challenge_id == row.id)
    if status in (None, "all"):
        stmt = stmt.where(PredictionMarket.status.in_(PUBLIC_STATUSES))
    elif status in PUBLIC_STATUSES:
        stmt = stmt.where(PredictionMarket.status == status)
    else:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "status"})
    if cursor is not None:
        open_tt, cid = _decode_cursor(cursor, 2)
        if not isinstance(open_tt, int):
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
        cuuid = _uuid_or_422(cid)
        stmt = stmt.where(
            or_(
                PredictionMarket.open_tt < open_tt,
                and_(PredictionMarket.open_tt == open_tt, PredictionMarket.id > cuuid),
            )
        )
    rows = list(
        db.scalars(
            stmt.order_by(PredictionMarket.open_tt.desc(), PredictionMarket.id.asc()).limit(
                limit + 1
            )
        )
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor([last.open_tt, str(last.id)])
    items = [
        market_out(db, user, row, info, m, ptt, my_shares=_my_shares(db, m, user.id)) for m in rows
    ]
    return {
        "items": items,
        "next_cursor": next_cursor,
        "public": public_clock(db, row, now),
    }


def market_detail(
    db: Session, user: User, market_id: uuid.UUID, now: datetime | None = None
) -> dict[str, Any]:
    """PmMarketDetailOut。"""
    now = now or timeutil.now()
    m, row, info, ptt = _prepare(db, market_id, now)
    out = market_out(db, user, row, info, m, ptt, my_shares=_my_shares(db, m, user.id))
    outs = _outcomes(db, m)
    out.update(
        {
            "q_shares": [o.q_shares for o in outs],
            "window_change_bp": _window_change_bp(db, row, m, ptt),
            "my": my_position_out(db, m, user.id),
            "limits": _limits(db, user, row, m, ptt, now),
            "balance_points": points_service.balance(db, user_id=user.id),
        }
    )
    return out


# ---------------------------------------------------------------- 报价


def _amounts(
    m: PredictionMarket,
    outs: Sequence[PredictionMarketOutcome],
    side: Side,
    outcome: int,
    *,
    shares: int | None,
    budget_points: int | None,
) -> tuple[int, Any]:
    """返回 (份额, Quote)。预算买入取满足预算的最大份额（上限 MAX_SHARES_PER_TRADE）。"""
    q = [o.q_shares for o in outs]
    b = m.liquidity_b_milli
    if side == "buy" and budget_points is not None:
        n = max_shares_for_budget(q, b, outcome, budget_points, MAX_SHARES_PER_TRADE)
        if n < 1:
            raise AppError(ErrorCode.PM_TRADE_TOO_SMALL, {"points": budget_points})
        shares = n
    assert shares is not None
    return shares, quote(q, b, side, outcome, shares)


def quote_market(
    db: Session,
    user: User,
    market_id: uuid.UUID,
    *,
    side: Side,
    outcome: int,
    shares: int | None = None,
    budget_points: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """PmQuoteOut：纯报价（不扣款、不写库，sync 除外）。"""
    now = now or timeutil.now()
    m, _row, _info, ptt = _prepare(db, market_id, now)
    status = _effective_status(m, ptt)
    if status != "open":
        raise AppError(ErrorCode.PM_NOT_OPEN, {"market_id": str(market_id), "status": status})
    order = TradeOrder(side=side, outcome=outcome, shares=shares, budget_points=budget_points)
    _validate(order, m.n_outcomes)
    outs = _outcomes(db, m)
    if side == "sell":
        held = _held(_positions(db, m, user.id), outcome)
        if shares is not None and shares > held:
            raise AppError(ErrorCode.PM_INSUFFICIENT_SHARES, {"held": held, "requested": shares})
    n, qt = _amounts(m, outs, side, outcome, shares=shares, budget_points=budget_points)
    return {
        "market_id": m.id,
        "side": side,
        "outcome": outcome,
        "shares": n,
        "points": qt.points,
        "avg_price_ppm": qt.avg_price_ppm,
        "price_before_ppm": qt.price_before_ppm,
        "prices_after_ppm": list(qt.prices_after_ppm),
        "trade_seq": m.trade_seq,
    }


# ---------------------------------------------------------------- 下单


def _trade_out(t: PredictionTrade) -> dict[str, Any]:
    return {
        "id": t.id,
        "market_id": t.market_id,
        "seq": t.seq,
        "side": t.side,
        "outcome": t.outcome_idx,
        "shares": t.shares,
        "points": t.points,
        "price_before_ppm": t.price_before_ppm,
        "prices_after_ppm": list(t.prices_after_ppm),
        "public_tt": t.public_tt,
        "created_at": t.created_at,
    }


def _result(
    db: Session,
    user: User,
    trade_row: PredictionTrade,
    *,
    replayed: bool,
    now: datetime,
) -> dict[str, Any]:
    m, row, info, ptt = _prepare(db, trade_row.market_id, now)
    return {
        "trade": _trade_out(trade_row),
        "market": market_out(db, user, row, info, m, ptt, my_shares=_my_shares(db, m, user.id)),
        "my": my_position_out(db, m, user.id),
        "balance_points": points_service.balance(db, user_id=user.id),
        "replayed": replayed,
    }


def _existing_by_key(db: Session, user_id: uuid.UUID, key: str) -> PredictionTrade | None:
    return db.scalar(
        select(PredictionTrade).where(
            PredictionTrade.user_id == user_id, PredictionTrade.idempotency_key == key
        )
    )


def trade(
    db: Session,
    user: User,
    market_id: uuid.UUID,
    order: TradeOrder,
    *,
    idempotency_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """下单（04 §5.1）。返回 PmTradeResultOut；同键同市场重放时 replayed=True。"""
    now = now or timeutil.now()
    if not idempotency_key or len(idempotency_key) > 64:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "Idempotency-Key"})
    for _ in range(PM_MAX_ATTEMPTS):
        existing = _existing_by_key(db, user.id, idempotency_key)
        if existing is not None:
            if existing.market_id != market_id:
                raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "Idempotency-Key"})
            return _result(db, user, existing, replayed=True, now=now)
        try:
            trade_row = _trade_once(db, user, market_id, order, idempotency_key, now)
            db.commit()
        except (IntegrityError, StaleDataError):
            db.rollback()
            continue
        except DomainError as exc:
            db.rollback()
            raise _domain_to_app(exc) from exc
        except AppError:
            db.rollback()
            raise
        return _result(db, user, trade_row, replayed=False, now=now)
    raise AppError(ErrorCode.PM_BUSY, {})


def _trade_once(
    db: Session,
    user: User,
    market_id: uuid.UUID,
    order: TradeOrder,
    key: str,
    now: datetime,
) -> PredictionTrade:
    m, row, _info, ptt = _prepare(db, market_id, now)  # 推进状态，自成事务
    m = pm_lifecycle.lock_market(db, market_id)  # 锁市场行（SQLite 忽略，靠版本号）
    if m is None:
        raise AppError(ErrorCode.PM_NOT_FOUND, {"market_id": str(market_id)})
    status = _effective_status(m, ptt)
    if status != "open":
        raise AppError(ErrorCode.PM_NOT_OPEN, {"market_id": str(market_id), "status": status})
    if _locked_ahead(db, user, row, ptt):
        raise AppError(ErrorCode.PM_LOCKED_AHEAD, {"challenge_id": str(row.id)})
    if not _account_eligible(user, now):
        raise AppError(ErrorCode.PM_NOT_ELIGIBLE, {"reason": "account_age"})
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW_S)
    recent = db.scalar(
        select(func.count())
        .select_from(PredictionTrade)
        .where(PredictionTrade.user_id == user.id, PredictionTrade.created_at >= window_start)
    )
    if (recent or 0) >= RATE_LIMIT_TRADES:
        raise AppError(ErrorCode.PM_RATE_LIMITED, {"retry_after_s": RATE_LIMIT_WINDOW_S})

    outs = _outcomes(db, m)
    _validate(order, m.n_outcomes)
    rows = _positions(db, m, user.id)
    held = _held(rows, order.outcome)
    if order.side == "sell" and order.shares is not None and order.shares > held:
        raise AppError(ErrorCode.PM_INSUFFICIENT_SHARES, {"held": held, "requested": order.shares})
    n, qt = _amounts(
        m,
        outs,
        order.side,
        order.outcome,
        shares=order.shares,
        budget_points=order.budget_points,
    )
    state = LimitState(
        subsidy_points=m.subsidy_points,
        market_net_cost_points=_market_net_cost(rows),
        challenge_buy_points=_challenge_buy_points(db, row, user.id),
        held_shares=held,
    )
    check_trade(side=order.side, shares=n, amount_points=qt.points, state=state)
    # 滑点（04 §5.4）：买入花费不得超过 max_cost（预算买入默认等于预算）；
    # 卖出回款不得低于 min_proceeds
    if order.side == "buy":
        limit = order.max_cost_points if order.max_cost_points is not None else order.budget_points
        if limit is not None and qt.points > limit:
            raise AppError(
                ErrorCode.PM_SLIPPAGE_EXCEEDED, {"quoted_points": qt.points, "limit_points": limit}
            )
    elif order.min_proceeds_points is not None and qt.points < order.min_proceeds_points:
        raise AppError(
            ErrorCode.PM_SLIPPAGE_EXCEEDED,
            {"quoted_points": qt.points, "limit_points": order.min_proceeds_points},
        )

    seq = m.trade_seq + 1
    if order.side == "buy":
        points_service.debit(
            db,
            user_id=user.id,
            amount=qt.points,
            reason="market_buy",
            ref=_ref(m.id),
            idempotency_key=f"market_buy:{m.id}:{seq}",
        )
        m.pool_points += qt.points
    else:
        points_service.credit(
            db,
            user_id=user.id,
            delta=qt.points,
            reason="market_sell",
            ref=_ref(m.id),
            idempotency_key=f"market_sell:{m.id}:{seq}",
        )
        m.pool_points -= qt.points
    outs[order.outcome].q_shares += n if order.side == "buy" else -n
    m.trade_seq = seq
    m.volume_shares += n
    m.prices_ppm = list(qt.prices_after_ppm)

    pos = next((r for r in rows if r.outcome_idx == order.outcome), None)
    if pos is None:
        pos = PredictionPosition(
            market_id=m.id,
            user_id=user.id,
            outcome_idx=order.outcome,
            shares=0,
            bought_points=0,
            sold_points=0,
            cost_points=0,
            updated_at=now,
        )
        db.add(pos)
    if not rows:
        m.traders += 1
    if order.side == "buy":
        pos.shares += n
        pos.bought_points += qt.points
        pos.cost_points += qt.points
    else:
        # 剩余份额的平均成本按卖出份额比例扣减（四舍五入）
        portion = _half_up(pos.cost_points * n, held)
        pos.cost_points -= portion
        pos.shares -= n
        pos.sold_points += qt.points
    pos.updated_at = now

    trade_row = PredictionTrade(
        id=uuid.uuid4(),
        market_id=m.id,
        user_id=user.id,
        seq=seq,
        side=order.side,
        outcome_idx=order.outcome,
        shares=n,
        points=qt.points,
        price_before_ppm=qt.price_before_ppm,
        prices_after_ppm=list(qt.prices_after_ppm),
        public_tt=ptt,
        idempotency_key=key,
        created_at=now,
    )
    db.add(trade_row)
    db.flush()
    return trade_row


# ---------------------------------------------------------------- 历史、成交带、我的持仓与结算


def _sample(items: list[Any], max_points: int) -> list[Any]:
    """等间隔抽样，保留首尾。"""
    if len(items) <= max_points:
        return items
    if max_points <= 1:
        return [items[-1]]
    last = len(items) - 1
    idxs = sorted({round(i * last / (max_points - 1)) for i in range(max_points)})
    return [items[i] for i in idxs]


def price_history(
    db: Session, market_id: uuid.UUID, max_points: int, now: datetime | None = None
) -> dict[str, Any]:
    """PmHistoryOut：首点为开盘先验（seq=0），之后按 seq 抽样，末点必含。"""
    now = now or timeutil.now()
    m, _row, info, _ptt = _prepare(db, market_id, now)
    b = m.liquidity_b_milli
    q0 = [o.q0_shares for o in _outcomes(db, m)]
    points: list[dict[str, Any]] = [
        {
            "seq": 0,
            "public_tt": m.open_tt,
            "at": registry.real_time_of(info, m.open_tt),
            "prices_ppm": list(prices_ppm(q0, b)) if b > 0 else [],
        }
    ]
    trades = db.scalars(
        select(PredictionTrade)
        .where(PredictionTrade.market_id == m.id)
        .order_by(PredictionTrade.seq)
    ).all()
    for t in trades:
        points.append(
            {
                "seq": t.seq,
                "public_tt": t.public_tt,
                "at": registry.real_time_of(info, t.public_tt),
                "prices_ppm": list(t.prices_after_ppm),
            }
        )
    sampled = _sample(points, max_points)
    if sampled[-1]["seq"] != points[-1]["seq"]:
        sampled[-1] = points[-1]
    return {"market_id": m.id, "items": sampled}


def tape_page(
    db: Session,
    market_id: uuid.UUID,
    cursor: str | None,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    """PmTapePageOut：匿名成交带，按 seq 降序，每页 50 条。"""
    now = now or timeutil.now()
    m, _row, info, _ptt = _prepare(db, market_id, now)
    stmt = select(PredictionTrade).where(PredictionTrade.market_id == m.id)
    if cursor is not None:
        (before,) = _decode_cursor(cursor, 1)
        if not isinstance(before, int):
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
        stmt = stmt.where(PredictionTrade.seq < before)
    rows = list(db.scalars(stmt.order_by(PredictionTrade.seq.desc()).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor([rows[-1].seq])
    items = [
        {
            "seq": t.seq,
            "side": t.side,
            "outcome": t.outcome_idx,
            "shares": t.shares,
            "points": t.points,
            "public_tt": t.public_tt,
            "at": registry.real_time_of(info, t.public_tt),
        }
        for t in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


def my_positions(
    db: Session,
    user: User,
    *,
    status: Literal["active", "settled"],
    cursor: str | None,
    limit: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    """PmPositionSummaryOut 列表：active = open/closed，settled = resolved/voided。"""
    now = now or timeutil.now()
    wanted = ("open", "closed") if status == "active" else ("resolved", "voided")
    market_ids = select(PredictionPosition.market_id).where(PredictionPosition.user_id == user.id)
    stmt = select(PredictionMarket).where(
        PredictionMarket.id.in_(market_ids), PredictionMarket.status.in_(wanted)
    )
    if cursor is not None:
        open_tt, cid = _decode_cursor(cursor, 2)
        if not isinstance(open_tt, int):
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
        cuuid = _uuid_or_422(cid)
        stmt = stmt.where(
            or_(
                PredictionMarket.open_tt < open_tt,
                and_(PredictionMarket.open_tt == open_tt, PredictionMarket.id > cuuid),
            )
        )
    rows = list(
        db.scalars(
            stmt.order_by(PredictionMarket.open_tt.desc(), PredictionMarket.id.asc()).limit(
                limit + 1
            )
        )
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor([rows[-1].open_tt, str(rows[-1].id)])
    items = []
    for m in rows:
        row = db.get(Challenge, m.challenge_id)
        info = pm_lifecycle.info_for(db, row)
        ptt = pm_lifecycle.public_tt(info, row, now)
        items.append(
            {
                "market": market_out(
                    db, user, row, info, m, ptt, my_shares=_my_shares(db, m, user.id)
                ),
                "my": my_position_out(db, m, user.id),
            }
        )
    return {"items": items, "next_cursor": next_cursor}


def my_settlements(
    db: Session, user: User, *, cursor: str | None, limit: int = 20
) -> dict[str, Any]:
    """PmSettlementOut 列表，按 created_at 降序。"""
    stmt = select(PredictionSettlement, PredictionMarket).join(
        PredictionMarket, PredictionSettlement.market_id == PredictionMarket.id
    )
    stmt = stmt.where(PredictionSettlement.user_id == user.id)
    if cursor is not None:
        created, sid = _decode_cursor(cursor, 2)
        if not isinstance(created, str):
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
        try:
            cdt = datetime.fromisoformat(created)
        except ValueError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc
        suuid = _uuid_or_422(sid)
        stmt = stmt.where(
            or_(
                PredictionSettlement.created_at < cdt,
                and_(PredictionSettlement.created_at == cdt, PredictionSettlement.id < suuid),
            )
        )
    rows = db.execute(
        stmt.order_by(PredictionSettlement.created_at.desc(), PredictionSettlement.id.desc()).limit(
            limit + 1
        )
    ).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1][0]
        next_cursor = _encode_cursor([_aware(last.created_at).isoformat(), str(last.id)])
    items = []
    for s, m in rows:
        q = m.question or {}
        items.append(
            {
                "market_id": m.id,
                "event_id": m.event_id,
                "kind": s.kind,
                "question": {
                    "scope": q.get("scope"),
                    "industry": q.get("industry"),
                    "code": q.get("code"),
                    "stock_name": q.get("stock_name"),
                    "from_day": q.get("from_day"),
                    "to_day": q.get("to_day"),
                    "edges_bp": list(q.get("edges_bp", [])),
                },
                "market_kind": m.kind,
                "winning_outcome": m.winning_outcome,
                "winning_shares": s.winning_shares,
                "payout_points": s.payout_points,
                "net_cost_points": s.net_cost_points,
                "pnl_points": s.pnl_points,
                "created_at": s.created_at,
            }
        )
    return {"items": items, "next_cursor": next_cursor}


def pnl_by_user(db: Session, challenge_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """给挑战排行榜用：已结算（resolved/voided）市场的 pnl_points 合计（04 §1.3）。"""
    rows = db.execute(
        select(
            PredictionSettlement.user_id,
            func.coalesce(func.sum(PredictionSettlement.pnl_points), 0),
        )
        .join(PredictionMarket, PredictionSettlement.market_id == PredictionMarket.id)
        .where(PredictionMarket.challenge_id == challenge_id)
        .group_by(PredictionSettlement.user_id)
    ).all()
    return {uid: int(total) for uid, total in rows}


def stock_names(db: Session, codes: Sequence[str]) -> dict[str, str]:
    if not codes:
        return {}
    return dict(db.execute(select(Stock.code, Stock.name).where(Stock.code.in_(codes))).all())


__all__ = [
    "PUBLIC_STATUSES",
    "TradeOrder",
    "list_markets",
    "market_detail",
    "my_positions",
    "my_settlements",
    "pnl_by_user",
    "price_history",
    "public_clock",
    "quote_market",
    "tape_page",
    "trade",
]
