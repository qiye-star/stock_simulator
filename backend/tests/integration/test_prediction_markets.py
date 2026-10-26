"""预测市场（模式 D）集成测试。步骤 5：生命周期与作废（04 §3.5–§3.6、§5.6）。

时间由 fake_clock 控制（timeutil.now）；市场时点换算为真实时间用 registry.real_time_of。
持仓用测试内的 fake_buy / fake_sell 模拟（只写账本与持仓表，不经 LMSR；交易服务在步骤 6 实现）。
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.models import (
    Challenge,
    LedgerEntry,
    PointAccount,
    PredictionMarket,
    PredictionMarketOutcome,
    PredictionPosition,
    PredictionSettlement,
    User,
)
from stocksim.services import pm_lifecycle
from stocksim.services import points as points_service
from stocksim.services.challenges import generate, registry

MARKET_REASONS = ("market_buy", "market_sell", "market_payout", "market_refund")
SUBSIDY_TIERS = {1000, 2000, 4000}


# ---------------------------------------------------------------- 辅助


def _challenge(db: Session, fake_clock) -> Challenge:
    from datetime import date

    return generate.ensure_challenge(db, date(2026, 10, 26), now=fake_clock.value)


def _markets(db: Session, ch: Challenge) -> list[PredictionMarket]:
    return list(
        db.scalars(
            select(PredictionMarket)
            .where(PredictionMarket.challenge_id == ch.id)
            .order_by(PredictionMarket.open_tt, PredictionMarket.event_id, PredictionMarket.kind)
        )
    )


def _real(db: Session, ch: Challenge, tt: int):
    info = registry.get_challenge(db, ch.id)
    return registry.real_time_of(info, tt)


def _at(db: Session, fake_clock, ch: Challenge, tt: int) -> None:
    fake_clock.value = _real(db, ch, tt)


def _outs(db: Session, m: PredictionMarket) -> list[PredictionMarketOutcome]:
    return list(
        db.scalars(
            select(PredictionMarketOutcome)
            .where(PredictionMarketOutcome.market_id == m.id)
            .order_by(PredictionMarketOutcome.idx)
        )
    )


def _user_seq(db: Session, m: PredictionMarket) -> int:
    return (
        int(
            db.scalar(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.reason.in_(MARKET_REASONS))
            )
            or 0
        )
        + 1
    )


def fake_buy(db: Session, m: PredictionMarket, user: User, outcome: int, shares: int, cost: int):
    """测试用买入：扣积分、加份额与持仓、池增加。不经 LMSR（只验证生命周期与账本）。"""
    seq = _user_seq(db, m)
    points_service.debit(
        db,
        user_id=user.id,
        amount=cost,
        reason="market_buy",
        ref=f"market:{m.id}",
        idempotency_key=f"market_buy:{m.id}:{seq}",
    )
    out = next(o for o in _outs(db, m) if o.idx == outcome)
    out.q_shares += shares
    m.pool_points += cost
    pos = db.scalar(
        select(PredictionPosition).where(
            PredictionPosition.market_id == m.id,
            PredictionPosition.user_id == user.id,
            PredictionPosition.outcome_idx == outcome,
        )
    )
    if pos is None:
        pos = PredictionPosition(
            market_id=m.id,
            user_id=user.id,
            outcome_idx=outcome,
            shares=0,
            bought_points=0,
            sold_points=0,
            cost_points=0,
        )
        db.add(pos)
    pos.shares += shares
    pos.bought_points += cost
    pos.cost_points += cost
    db.commit()


def ledger_market_total(db: Session) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
                LedgerEntry.reason.in_(MARKET_REASONS)
            )
        )
        or 0
    )


def assert_conservation(db: Session) -> None:
    """04 §5.6：Σ 账本 market_* delta + Σ pool = Σ subsidy − Σ returned；池非负；q 不低于 q0。"""
    rows = db.scalars(select(PredictionMarket)).all()
    pool = sum(m.pool_points for m in rows)
    subsidy = sum(m.subsidy_points for m in rows)
    returned = sum(m.subsidy_returned_points or 0 for m in rows)
    assert ledger_market_total(db) + pool == subsidy - returned
    assert all(m.pool_points >= 0 for m in rows)
    for m in rows:
        for o in _outs(db, m):
            assert o.q_shares >= o.q0_shares >= 0


def _positions_sum(db: Session, m: PredictionMarket) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for p in db.scalars(select(PredictionPosition).where(PredictionPosition.market_id == m.id)):
        totals[p.outcome_idx] += p.shares
    return totals


# ---------------------------------------------------------------- 物化


def test_materialize_only_round_events_and_hidden_until_open(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    assert markets, "compact 挑战的回合事件应至少产生一个市场"
    round_ids = set(registry.round_event_ids(db, ch))
    assert {m.event_id for m in markets} <= round_ids
    assert all(m.status == "scheduled" for m in markets)
    for m in markets:
        outs = _outs(db, m)
        assert len(outs) == m.n_outcomes
        assert m.n_outcomes == (2 if m.kind == "rumor" else m.n_outcomes)
        assert m.kind in ("bucket", "rumor")
        assert all(o.q_shares == 0 and o.q0_shares == 0 for o in outs)
        assert m.subsidy_points == 0 and m.pool_points == 0 and m.liquidity_b_milli == 0
    # 幂等：再次物化不新增
    info = registry.get_challenge(db, ch.id)
    assert pm_lifecycle.materialize(db, info) == 0
    db.commit()
    assert len(_markets(db, ch)) == len(markets)


def test_scheduled_market_not_opened_before_open_tick(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    fake_clock.value = _real(db, ch, 0)
    assert pm_lifecycle.sync_market(db, m.id) is False
    db.refresh(m)
    assert m.status == "scheduled"


# ---------------------------------------------------------------- 生命周期


def test_lifecycle_all_markets_follow_public_timeline(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    checkpoints = sorted(
        {m.open_tt for m in markets}
        | {m.close_tt for m in markets}
        | {m.resolve_tt for m in markets}
    )
    buyer_a = _make(db, "buyer_a")
    buyer_b = _make(db, "buyer_b")
    for tt in checkpoints:
        _at(db, fake_clock, ch, tt)
        for m in markets:
            if m.open_tt == tt:
                pm_lifecycle.sync_market(db, m.id)
                db.refresh(m)
                assert m.status == "open"
                assert m.subsidy_points in SUBSIDY_TIERS
                assert m.pool_points == m.subsidy_points
                assert m.liquidity_b_milli > 0
                assert sum(m.prices_ppm) == 1_000_000
                assert [o.q_shares for o in _outs(db, m)] == [o.q0_shares for o in _outs(db, m)]
                # 每个选项各 1 份（A），第 0 个选项 2 份（B）
                for idx in range(m.n_outcomes):
                    fake_buy(db, m, buyer_a, idx, 1, 50)
                fake_buy(db, m, buyer_b, 0, 2, 80)
        for m in markets:
            if m.close_tt == tt:
                pm_lifecycle.sync_market(db, m.id)
                db.refresh(m)
                assert m.status in ("closed", "resolved")
        for m in markets:
            if m.resolve_tt == tt:
                pm_lifecycle.sync_market(db, m.id)
                db.refresh(m)
                assert m.status == "resolved"
                assert m.winning_outcome is not None
                assert m.pool_points == 0
                # 池余额记入 returned
                assert m.subsidy_returned_points is not None
                assert m.subsidy_returned_points >= 0
                settle = {
                    s.user_id: s
                    for s in db.scalars(
                        select(PredictionSettlement).where(PredictionSettlement.market_id == m.id)
                    )
                }
                assert set(settle) == {buyer_a.id, buyer_b.id}
                win = m.winning_outcome
                sa = settle[buyer_a.id]
                sb = settle[buyer_b.id]
                assert sa.kind == sb.kind == "resolved"
                assert sa.winning_shares == 1 and sa.payout_points == 100
                expected_b = 200 if win == 0 else 0
                assert sb.payout_points == expected_b
                assert sa.net_cost_points == 50 * m.n_outcomes
                assert sb.net_cost_points == 80
                assert sa.pnl_points == 100 - 50 * m.n_outcomes
        assert_conservation(db)
    # 全部市场都已结算（终态）
    assert all(m.status == "resolved" for m in _markets(db, ch))
    # 不变量：正常结算的 returned 等于池余额（这里 pool 已清零）
    assert_conservation(db)


def _make(db: Session, name: str) -> User:
    from datetime import UTC, datetime

    from stocksim.services import auth as auth_service

    user = auth_service.register(db, name, "secret1")
    user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    # 测试用：补足积分（欢迎积分 200 不够多市场买入）
    points_service.credit(
        db,
        user_id=user.id,
        delta=10_000,
        reason="admin_adjust",
        ref=f"test:{name}",
        idempotency_key=f"admin_adjust:test-{name}",
    )
    db.commit()
    return user


def test_sync_is_idempotent(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    assert pm_lifecycle.sync_market(db, m.id) is True
    assert pm_lifecycle.sync_market(db, m.id) is False
    db.refresh(m)
    assert m.status == "open"
    s_before = m.subsidy_points
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    assert m.subsidy_points == s_before and m.status == "open"
    assert_conservation(db)


def test_sync_due_is_idempotent_across_sessions(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    first_open = min(m.open_tt for m in markets)
    _at(db, fake_clock, ch, first_open)
    factory = challenge_app.state.session_factory
    n1 = pm_lifecycle.sync_due(factory)
    n2 = pm_lifecycle.sync_due(factory)
    assert n1 >= 1 and n2 == 0
    db.expire_all()
    assert any(m.status == "open" for m in _markets(db, ch))


# ---------------------------------------------------------------- 作废


def test_challenge_revoked_refunds_net_positions(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    buyer = _make(db, "refund_a")
    seller = _make(db, "refund_b")
    fake_buy(db, m, buyer, 0, 3, 120)
    fake_buy(db, m, seller, 1, 2, 70)
    # seller 卖出 1 份（回款 40）：净投入 30，退款 30
    _sell(db, m, seller, 1, 1, 40)
    assert_conservation(db)
    generate.void_challenge(db, ch, "manual")
    db.refresh(m)
    assert m.status == "voided" and m.void_reason == "challenge_revoked"
    settle = {
        s.user_id: s
        for s in db.scalars(
            select(PredictionSettlement).where(PredictionSettlement.market_id == m.id)
        )
    }
    assert settle[buyer.id].payout_points == 120
    assert settle[seller.id].payout_points == 30
    assert settle[seller.id].pnl_points == 30 - 30
    assert m.pool_points == 0
    # 池 = S + 190 − 40 = S + 150，退款 150，余额 = S（卖出回款不计入退款）
    assert m.subsidy_returned_points == m.subsidy_points
    assert_conservation(db)


def test_voided_market_pool_shortfall_is_negative_returned(challenge_app, db, fake_clock) -> None:
    """退款超过池余额（卖出获利者）时，差额为负写入 returned，池不为负（04 §3.5）。"""
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    u = _make(db, "short_a")
    fake_buy(db, m, u, 0, 2, 60)
    # 卖出回款超过池子里的份额成本（人为制造：卖出回款 = 60 + 200）
    _sell(db, m, u, 0, 2, 260)
    # 此时净投入 = 60 − 260 = −200，退款 0；池 = S + 60 − 260 = S − 200
    generate.void_challenge(db, ch, "manual")
    db.refresh(m)
    assert m.status == "voided"
    assert m.pool_points == 0
    assert m.subsidy_returned_points == m.subsidy_points - 200
    assert_conservation(db)


def test_event_mismatch_voids_at_open(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    m.event_fingerprint = "0" * 64
    db.commit()
    _at(db, fake_clock, ch, m.open_tt)
    assert pm_lifecycle.sync_market(db, m.id) is True
    db.refresh(m)
    assert m.status == "voided" and m.void_reason == "event_mismatch"
    assert m.subsidy_points == 0 and m.subsidy_returned_points == 0
    assert_conservation(db)


def test_ruleset_changed_voids(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    ch_row = db.get(Challenge, ch.id)
    ch_row.events_ruleset = ch_row.events_ruleset + 1
    db.commit()
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    assert m.status == "voided" and m.void_reason == "ruleset_changed"


def _sell(db: Session, m: PredictionMarket, user: User, outcome: int, shares: int, proceeds: int):
    """测试用卖出：回款入账，份额与池扣减，净成本按比例扣减（不经 LMSR）。"""
    seq = _user_seq(db, m)
    points_service.credit(
        db,
        user_id=user.id,
        delta=proceeds,
        reason="market_sell",
        ref=f"market:{m.id}",
        idempotency_key=f"market_sell:{m.id}:{seq}",
    )
    out = next(o for o in _outs(db, m) if o.idx == outcome)
    out.q_shares -= shares
    m.pool_points -= proceeds
    pos = db.scalar(
        select(PredictionPosition).where(
            PredictionPosition.market_id == m.id,
            PredictionPosition.user_id == user.id,
            PredictionPosition.outcome_idx == outcome,
        )
    )
    pos.shares -= shares
    pos.sold_points += proceeds
    db.commit()


def test_account_exists_for_payout(challenge_app, db, fake_clock) -> None:
    """兑付入账走 points.credit，用户账户存在且余额随之变化。"""
    ch = _challenge(db, fake_clock)
    markets = _markets(db, ch)
    m = markets[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    u = _make(db, "payout_user")
    fake_buy(db, m, u, 0, 1, 50)
    _at(db, fake_clock, ch, m.resolve_tt)
    pm_lifecycle.sync_market(db, m.id)  # 先 close
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    assert m.status == "resolved"
    acct = db.get(PointAccount, u.id)
    assert acct is not None and acct.balance >= 0
    assert db.scalar(
        select(func.count())
        .select_from(LedgerEntry)
        .where(LedgerEntry.user_id == u.id, LedgerEntry.reason == "market_payout")
    ) == (1 if m.winning_outcome == 0 else 0)
    assert_conservation(db)


def test_challenge_row_unchanged_by_lifecycle(challenge_app, db, fake_clock) -> None:
    """生命周期不改挑战状态（挑战由 C 推进）。"""
    ch = _challenge(db, fake_clock)
    before = (ch.status, ch.version)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(ch)
    assert (ch.status, ch.version) == before


@pytest.mark.parametrize("n", [1])
def test_sync_challenge_bulk(challenge_app, db, fake_clock, n) -> None:
    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    assert pm_lifecycle.sync_challenge(db, ch.id) >= n
    assert_conservation(db)
    assert db.get(PredictionMarket, m.id).status == "open"


def test_concurrent_sync_due_settles_once(challenge_app, db, fake_clock) -> None:
    """多实例模拟（04 §8.3）：三个线程并发执行 sync_due，结算与兑付只生效一次。"""
    import threading

    ch = _challenge(db, fake_clock)
    m = _markets(db, ch)[0]
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    u = _make(db, "multi_inst")
    fake_buy(db, m, u, 0, 2, 60)
    _at(db, fake_clock, ch, m.resolve_tt)
    factory = challenge_app.state.session_factory
    threads = [
        threading.Thread(target=pm_lifecycle.sync_due, args=(factory,)) for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    db.expire_all()
    db.refresh(m)
    assert m.status == "resolved"
    rows = db.scalars(
        select(PredictionSettlement).where(PredictionSettlement.market_id == m.id)
    ).all()
    assert len(rows) == 1 and rows[0].user_id == u.id
    payouts = db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.reason == "market_payout", LedgerEntry.user_id == u.id
        )
    ).all()
    assert len(payouts) == (1 if m.winning_outcome == 0 else 0)
    assert_conservation(db)
