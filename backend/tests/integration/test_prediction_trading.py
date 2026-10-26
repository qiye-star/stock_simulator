"""预测市场（模式 D）集成测试。步骤 6：报价、下单、幂等、并发、滑点、限额、视图（04 §5、§9）。

时间由 fake_clock 控制；市场时点换算为真实时间用 registry.real_time_of。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError
from stocksim.models import (
    Challenge,
    LedgerEntry,
    PredictionMarket,
    PredictionMarketOutcome,
    PredictionPosition,
    PredictionSettlement,
    PredictionTrade,
    User,
)
from stocksim.services import auth as auth_service
from stocksim.services import pm_lifecycle
from stocksim.services import points as points_service
from stocksim.services import prediction_markets as pm
from stocksim.services.challenges import generate, registry

MARKET_REASONS = ("market_buy", "market_sell", "market_payout", "market_refund")


# ---------------------------------------------------------------- 辅助


def _challenge(db: Session, fake_clock) -> Challenge:
    return generate.ensure_challenge(db, date(2026, 10, 26), now=fake_clock.value)


def _markets(db: Session, ch: Challenge) -> list[PredictionMarket]:
    return list(
        db.scalars(
            select(PredictionMarket)
            .where(PredictionMarket.challenge_id == ch.id)
            .order_by(PredictionMarket.open_tt, PredictionMarket.event_id, PredictionMarket.kind)
        )
    )


def _at(db: Session, fake_clock, ch: Challenge, tt: int) -> None:
    info = registry.get_challenge(db, ch.id)
    fake_clock.value = registry.real_time_of(info, tt)


def _open_market(
    db: Session, fake_clock, ch: Challenge, *, bucket: bool = True
) -> PredictionMarket:
    """取一个分档（或传闻）市场，推进到开市时刻。"""
    m = next(x for x in _markets(db, ch) if (x.kind == "bucket") == bucket)
    _at(db, fake_clock, ch, m.open_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    assert m.status == "open"
    return m


def _user(db: Session, name: str, funded: bool = True) -> User:
    user = auth_service.register(db, name, "secret1")
    user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    if funded:
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


def _order(side: str, outcome: int, **kw) -> pm.TradeOrder:
    return pm.TradeOrder(side=side, outcome=outcome, **kw)  # type: ignore[arg-type]


def _buy(db: Session, m: PredictionMarket, user: User, outcome: int, shares: int, key: str):
    return pm.trade(db, user, m.id, _order("buy", outcome, shares=shares), idempotency_key=key)


def _error_code(fn: Callable[[], object]) -> tuple[str, dict]:
    with pytest.raises(AppError) as info:
        fn()
    return info.value.code.value, dict(info.value.params)


def _ledger_market_total(db: Session) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
                LedgerEntry.reason.in_(MARKET_REASONS)
            )
        )
        or 0
    )


def _assert_conservation(db: Session) -> None:
    rows = db.scalars(select(PredictionMarket)).all()
    pool = sum(m.pool_points for m in rows)
    subsidy = sum(m.subsidy_points for m in rows)
    returned = sum(m.subsidy_returned_points or 0 for m in rows)
    assert _ledger_market_total(db) + pool == subsidy - returned
    assert all(m.pool_points >= 0 for m in rows)
    for m in rows:
        outs = db.scalars(
            select(PredictionMarketOutcome).where(PredictionMarketOutcome.market_id == m.id)
        ).all()
        assert all(o.q_shares >= o.q0_shares >= 0 for o in outs)


def _held(db: Session, m: PredictionMarket, user: User, outcome: int) -> int:
    p = db.scalar(
        select(PredictionPosition).where(
            PredictionPosition.market_id == m.id,
            PredictionPosition.user_id == user.id,
            PredictionPosition.outcome_idx == outcome,
        )
    )
    return p.shares if p else 0


# ---------------------------------------------------------------- 报价与下单


def test_quote_matches_trade(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "quote_a")
    before = points_service.balance(db, user_id=u.id)
    q = pm.quote_market(db, u, m.id, side="buy", outcome=1, shares=3)
    assert q["points"] > 0 and q["shares"] == 3
    res = _buy(db, m, u, 1, 3, key="k-quote-1")
    assert res["replayed"] is False
    assert res["trade"]["points"] == q["points"]
    assert res["trade"]["seq"] == 1
    assert res["balance_points"] == before - q["points"]
    assert res["market"]["trade_seq"] == 1
    db.refresh(m)
    assert m.pool_points == m.subsidy_points + q["points"]
    assert _held(db, m, u, 1) == 3
    _assert_conservation(db)


def test_idempotent_replay_and_key_reuse_across_markets(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    other = [x for x in _markets(db, ch) if x.id != m.id and x.kind == "bucket"]
    u = _user(db, "idem_a")
    first = _buy(db, m, u, 0, 2, key="same-key")
    again = _buy(db, m, u, 0, 2, key="same-key")
    assert again["replayed"] is True
    assert again["trade"]["id"] == first["trade"]["id"]
    assert db.scalar(select(func.count()).select_from(PredictionTrade)) == 1
    assert pm.trade is not None
    if other:
        code, params = _error_code(
            lambda: pm.trade(
                db, u, other[0].id, _order("buy", 0, shares=1), idempotency_key="same-key"
            )
        )
        assert code == "VALIDATION_ERROR" and params == {"field": "Idempotency-Key"}
    _assert_conservation(db)


def test_concurrent_same_key_creates_one_trade(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "idem_threads")
    factory = challenge_app.state.session_factory
    results: list[bool] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        s = factory()
        try:
            user = s.get(User, u.id)
            res = pm.trade(
                s, user, m.id, _order("buy", 0, shares=2), idempotency_key="threaded-key"
            )
            with lock:
                results.append(res["replayed"])
        except AppError as exc:
            with lock:
                errors.append(exc.code.value)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert results.count(False) == 1
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PredictionTrade)) == 1
    _assert_conservation(db)


def test_threads_trade_consistently(challenge_app, db, fake_clock) -> None:
    """多人并发下单打同一市场：全部成功或 PM_BUSY；trade_seq 连续，成交行数一致。"""
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    users = [_user(db, f"conc_{i}") for i in range(4)]
    factory = challenge_app.state.session_factory
    failures: list[str] = []
    lock = threading.Lock()

    def worker(uid, n: int) -> None:
        s = factory()
        try:
            user = s.get(User, uid)
            for k in range(n):
                try:
                    pm.trade(
                        s,
                        user,
                        m.id,
                        _order("buy", k % m.n_outcomes, shares=1),
                        idempotency_key=f"conc-{uid}-{k}",
                    )
                except AppError as exc:
                    with lock:
                        failures.append(exc.code.value)
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(u.id, 3)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(failures) <= {"PM_BUSY"}
    db.expire_all()
    db.refresh(m)
    n_trades = db.scalar(
        select(func.count()).select_from(PredictionTrade).where(PredictionTrade.market_id == m.id)
    )
    seqs = sorted(db.scalars(select(PredictionTrade.seq).where(PredictionTrade.market_id == m.id)))
    assert seqs == list(range(1, n_trades + 1))
    assert m.trade_seq == n_trades
    _assert_conservation(db)


def test_sell_round_trip_no_arbitrage(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "roundtrip")
    bought = _buy(db, m, u, 2, 5, key="rt-buy")
    sold = pm.trade(db, u, m.id, _order("sell", 2, shares=5), idempotency_key="rt-sell")
    assert sold["trade"]["points"] <= bought["trade"]["points"]
    assert _held(db, m, u, 2) == 0
    pos = pm.my_position_out(db, m, u.id)
    assert pos is not None and pos["net_cost_points"] == pos["bought_points"] - pos["sold_points"]
    _assert_conservation(db)


def test_sell_more_than_held_is_rejected(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "oversell")
    _buy(db, m, u, 0, 1, key="os-buy")
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("sell", 0, shares=2), idempotency_key="os-sell")
    )
    assert code == "PM_INSUFFICIENT_SHARES" and params == {"held": 1, "requested": 2}


def test_slippage_guard_on_buy_and_sell(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    a = _user(db, "slip_a")
    b = _user(db, "slip_b")
    quoted = pm.quote_market(db, a, m.id, side="buy", outcome=0, shares=4)
    _buy(db, m, b, 0, 3, key="slip-b")  # 他人先买，价格上行
    code, params = _error_code(
        lambda: pm.trade(
            db,
            a,
            m.id,
            _order("buy", 0, shares=4, max_cost_points=quoted["points"]),
            idempotency_key="slip-a",
        )
    )
    assert code == "PM_SLIPPAGE_EXCEEDED"
    assert params["limit_points"] == quoted["points"] and params["quoted_points"] > quoted["points"]
    # 放宽后可成交
    res = pm.trade(
        db,
        a,
        m.id,
        _order("buy", 0, shares=4, max_cost_points=params["quoted_points"]),
        idempotency_key="slip-a2",
    )
    assert res["trade"]["shares"] == 4
    # 卖出：回款低于 min_proceeds 被拒
    code, _ = _error_code(
        lambda: pm.trade(
            db,
            a,
            m.id,
            _order("sell", 0, shares=4, min_proceeds_points=10**6),
            idempotency_key="slip-sell",
        )
    )
    assert code == "PM_SLIPPAGE_EXCEEDED"


def test_budget_buy_fits_budget(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "budget")
    res = pm.trade(db, u, m.id, _order("buy", 1, budget_points=120), idempotency_key="budget-1")
    assert 1 <= res["trade"]["shares"] <= 200
    assert res["trade"]["points"] <= 120
    _assert_conservation(db)


def test_position_limit_and_insufficient_points(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "limit_a")
    # 单市场净投入上限 max(200, S//4)：200 份一次性买入远超上限
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=200), idempotency_key="lim-1")
    )
    assert code == "PM_POSITION_LIMIT" and params["limit_points"] == max(200, m.subsidy_points // 4)
    # 积分不足：余额清零后买入 1 份（不触发额度）
    poor = _user(db, "poor", funded=False)
    # 首次记账会发放欢迎积分 200，这里开户后扣光余额
    points_service.open_account(db, poor.id)
    points_service.debit(
        db,
        user_id=poor.id,
        amount=points_service.balance(db, user_id=poor.id),
        reason="admin_adjust",
        ref="test:poor",
        idempotency_key="admin_adjust:poor-zero",
    )
    db.commit()
    assert points_service.balance(db, user_id=poor.id) == 0
    code, _ = _error_code(
        lambda: pm.trade(db, poor, m.id, _order("buy", 2, shares=1), idempotency_key="poor-1")
    )
    assert code == "POINTS_INSUFFICIENT"
    db.refresh(m)
    assert m.trade_seq == 0 and m.pool_points == m.subsidy_points
    assert all(o.q_shares == o.q0_shares for o in _outcomes(db, m))


def _outcomes(db: Session, m: PredictionMarket):
    return db.scalars(
        select(PredictionMarketOutcome).where(PredictionMarketOutcome.market_id == m.id)
    ).all()


def test_daily_buy_cap(challenge_app, db, fake_clock, monkeypatch) -> None:
    from stocksim.domain.prediction_market import limits as pm_limits

    monkeypatch.setattr(pm_limits, "CHALLENGE_BUY_CAP_POINTS", 50)
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "daily")
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=5), idempotency_key="daily-1")
    )
    assert code == "PM_DAILY_LIMIT" and params["limit_points"] == 50


def test_rate_limit_on_thirteenth_trade(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "rate")
    # 买一份再卖出一份：净投入约为 0，不触发额度，只消耗频率配额
    for k in range(6):
        _buy(db, m, u, 0, 1, key=f"rate-b{k}")
        pm.trade(db, u, m.id, _order("sell", 0, shares=1), idempotency_key=f"rate-s{k}")
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=1), idempotency_key="rate-13")
    )
    assert code == "PM_RATE_LIMITED" and params == {"retry_after_s": 60}


def test_closed_market_refuses_trades(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    _at(db, fake_clock, ch, m.close_tt)
    u = _user(db, "late")
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=1), idempotency_key="late-1")
    )
    assert code == "PM_NOT_OPEN" and params["status"] == "closed"


def test_locked_ahead_is_rejected(challenge_app, db, fake_clock, monkeypatch) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "ahead")
    real_ptt = None

    def ahead(db_, uid, ch_):
        return real_ptt + 5

    info = registry.get_challenge(db, ch.id)
    real_ptt = registry.public_trading_tick(info, fake_clock.value)
    monkeypatch.setattr(registry, "knowledge_trading_tick", ahead)
    code, _ = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=1), idempotency_key="ahead-1")
    )
    assert code == "PM_LOCKED_AHEAD"


def test_account_age_gate(challenge_app, db, fake_clock, monkeypatch) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "young")
    monkeypatch.setattr(pm, "_account_eligible", lambda user, now: False)
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=1), idempotency_key="young-1")
    )
    assert code == "PM_NOT_ELIGIBLE" and params == {"reason": "account_age"}


def test_trade_validation(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "val")
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 99, shares=1), idempotency_key="v-1")
    )
    assert code == "VALIDATION_ERROR" and params == {"field": "outcome"}
    code, params = _error_code(
        lambda: pm.trade(db, u, m.id, _order("buy", 0, shares=1), idempotency_key="")
    )
    assert code == "VALIDATION_ERROR" and params == {"field": "Idempotency-Key"}


# ---------------------------------------------------------------- 视图与结算


def test_views_history_tape_and_detail(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "views")
    _buy(db, m, u, 0, 2, key="v-b1")
    _buy(db, m, u, 1, 1, key="v-b2")
    db.refresh(m)
    hist = pm.price_history(db, m.id, 200)
    items = hist["items"]
    assert items[0]["seq"] == 0 and items[-1]["seq"] == m.trade_seq
    assert items[-1]["prices_ppm"] == list(m.prices_ppm)
    assert len(pm.price_history(db, m.id, 2)["items"]) <= 2
    tape = pm.tape_page(db, m.id, None)
    assert [t["seq"] for t in tape["items"]] == [2, 1]
    assert "user_id" not in tape["items"][0]
    detail = pm.market_detail(db, u, m.id)
    assert detail["my"]["bought_points"] > 0
    assert detail["q_shares"][0] == 2 and detail["q_shares"][1] == 1
    assert detail["balance_points"] == points_service.balance(db, user_id=u.id)
    if m.kind == "rumor":
        assert detail["close_tt"] is None and detail["resolve_tt"] is None
    # 开放全部市场，保证列表至少两页
    _at(db, fake_clock, ch, max(x.open_tt for x in _markets(db, ch)))
    pm_lifecycle.sync_challenge(db, ch.id)
    lst = pm.list_markets(
        db, u, challenge_id=ch.id, status=None, limit=1, cursor=None, now=fake_clock.value
    )
    assert lst["next_cursor"] is not None
    assert len(lst["items"]) == 1
    assert all(x["status"] != "scheduled" for x in lst["items"])
    nxt = pm.list_markets(
        db,
        u,
        challenge_id=ch.id,
        status=None,
        limit=1,
        cursor=lst["next_cursor"],
        now=fake_clock.value,
    )
    assert nxt["items"][0]["id"] != lst["items"][0]["id"]
    assert len(nxt["items"]) == 1


def test_settlement_and_pnl_after_resolve(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "settler")
    _buy(db, m, u, 0, 3, key="st-b")
    _at(db, fake_clock, ch, m.close_tt)
    pm_lifecycle.sync_market(db, m.id)
    _at(db, fake_clock, ch, m.resolve_tt)
    pm_lifecycle.sync_market(db, m.id)
    db.refresh(m)
    assert m.status == "resolved"
    page = pm.my_settlements(db, u, cursor=None)
    assert len(page["items"]) == 1
    row = page["items"][0]
    assert row["market_id"] == m.id and row["kind"] == "resolved"
    assert row["payout_points"] == (300 if m.winning_outcome == 0 else 0)
    assert pm.pnl_by_user(db, ch.id)[u.id] == row["pnl_points"]
    settled = pm.my_positions(db, u, status="settled", cursor=None)
    assert [x["market"]["id"] for x in settled["items"]] == [m.id]
    active = pm.my_positions(db, u, status="active", cursor=None)
    assert all(x["market"]["id"] != m.id for x in active["items"])
    assert (
        db.scalar(
            select(func.count())
            .select_from(PredictionSettlement)
            .where(PredictionSettlement.user_id == u.id)
        )
        == 1
    )
    _assert_conservation(db)


def test_public_views_do_not_leak_hidden_fields(challenge_app, db, fake_clock) -> None:
    ch = _challenge(db, fake_clock)
    m = _open_market(db, fake_clock, ch)
    u = _user(db, "secret_v")
    detail = pm.market_detail(db, u, m.id)

    def keys(obj, acc: set[str]) -> set[str]:
        if isinstance(obj, dict):
            for k, v in obj.items():
                acc.add(k)
                keys(v, acc)
        elif isinstance(obj, list):
            for v in obj:
                keys(v, acc)
        return acc

    names = keys(detail, set())
    for hidden in (
        "event_fingerprint",
        "magnitude_ppm",
        "knots",
        "impacts",
        "truth",
        "expectation",
        "publish_trading_tick",
        "resolve_trading_tick",
        "seed",
    ):
        assert hidden not in names, hidden
    if m.kind == "rumor":
        assert detail["close_tt"] is None and detail["resolve_tt"] is None
    assert isinstance(PredictionTrade, type)
