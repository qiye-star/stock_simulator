"""积分账本服务（02 §1.1、§13.2）：幂等、余额下限、乐观锁并发、游标分页、删档与删用户语义。"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.models import LedgerEntry, PointAccount
from stocksim.services import points
from stocksim.services.tx import run_in_transaction


def _user_id(client: TestClient) -> uuid.UUID:
    return uuid.UUID(client.get("/api/v1/me").json()["id"])


@pytest.fixture
def user(registered_client: TestClient) -> uuid.UUID:
    return _user_id(registered_client)


def _commit_credit(app: FastAPI, uid: uuid.UUID, delta: int, key: str) -> None:
    with app.state.session_factory() as db:
        points.credit(
            db, user_id=uid, delta=delta, reason="admin_adjust", ref="t:1", idempotency_key=key
        )
        db.commit()


def _open(app: FastAPI, uid: uuid.UUID) -> None:
    with app.state.session_factory() as db:
        points.open_account(db, uid)
        db.commit()


def test_first_credit_opens_account_with_welcome_at_seq_one(app: FastAPI, user: uuid.UUID):
    with app.state.session_factory() as db:
        assert points.balance(db, user_id=user) == 0  # 无账户不建账户
        assert db.get(PointAccount, user) is None
        entry = points.credit(
            db,
            user_id=user,
            delta=5,
            reason="admin_adjust",
            ref="t:1",
            idempotency_key="admin_adjust:a",
        )
        db.commit()
        acct = db.get(PointAccount, user)
        assert acct.balance == points.WELCOME_POINTS + 5
        assert acct.lifetime_earned == points.WELCOME_POINTS + 5
        assert entry.seq == 2 and entry.balance_after == acct.balance
        welcome = db.scalar(select(LedgerEntry).where(LedgerEntry.seq == 1))
        assert welcome.reason == "welcome" and welcome.delta == points.WELCOME_POINTS
        assert welcome.idempotency_key == f"welcome:{user}"


def test_same_key_is_idempotent_and_conflict_raises(app: FastAPI, user: uuid.UUID):
    with app.state.session_factory() as db:
        first = points.credit(
            db,
            user_id=user,
            delta=7,
            reason="admin_adjust",
            ref="t:1",
            idempotency_key="admin_adjust:k",
        )
        again = points.credit(
            db,
            user_id=user,
            delta=7,
            reason="admin_adjust",
            ref="t:1",
            idempotency_key="admin_adjust:k",
        )
        assert again.id == first.id
        db.commit()
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS + 7
        with pytest.raises(points.LedgerConflict):
            points.credit(
                db,
                user_id=user,
                delta=8,
                reason="admin_adjust",
                ref="t:1",
                idempotency_key="admin_adjust:k",
            )


def test_debit_insufficient_leaves_balance_and_ledger_unchanged(app: FastAPI, user: uuid.UUID):
    _open(app, user)
    with app.state.session_factory() as db:
        with pytest.raises(AppError) as exc:
            points.debit(
                db,
                user_id=user,
                amount=points.WELCOME_POINTS + 1,
                reason="intel_card",
                ref="edge:x",
                idempotency_key="intel_edge:u:x:L1",
            )
        assert exc.value.code == ErrorCode.POINTS_INSUFFICIENT
        assert exc.value.params == {
            "required": points.WELCOME_POINTS + 1,
            "balance": points.WELCOME_POINTS,
        }
        db.rollback()
    with app.state.session_factory() as db:
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS
        assert db.scalar(select(LedgerEntry).where(LedgerEntry.reason == "intel_card")) is None


def test_check_constraint_rejects_negative_balance(app: FastAPI, user: uuid.UUID):
    _open(app, user)
    with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(update(PointAccount).where(PointAccount.user_id == user).values(balance=-1))
        db.rollback()


def test_concurrent_debits_do_not_lose_updates(app: FastAPI, user: uuid.UUID):
    """两个会话交错扣款：无论 ORM 是否刷新对象，最终余额都必须等于两笔扣款之和（无丢失更新）。"""
    _open(app, user)
    with app.state.session_factory() as db_a, app.state.session_factory() as db_b:
        points.open_account(db_a, user)
        points.open_account(db_b, user)
        points.debit(
            db_a,
            user_id=user,
            amount=50,
            reason="intel_card",
            ref="edge:a",
            idempotency_key="intel_edge:u:a:L1",
        )
        db_a.commit()

        def work():
            return points.debit(
                db_b,
                user_id=user,
                amount=30,
                reason="intel_card",
                ref="edge:b",
                idempotency_key="intel_edge:u:b:L1",
            )

        entry = run_in_transaction(db_b, work)
        assert entry.balance_after == points.WELCOME_POINTS - 50 - 30
    with app.state.session_factory() as db:
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS - 80


def test_run_in_transaction_retries_on_version_conflict(app: FastAPI, user: uuid.UUID):
    """冲突（乐观锁）后回滚、刷新并重做；第二次成功。"""
    _open(app, user)
    calls = {"n": 0}
    with app.state.session_factory() as db:

        def work():
            calls["n"] += 1
            if calls["n"] == 1:
                raise StaleDataError("simulated version conflict")
            return points.credit(
                db,
                user_id=user,
                delta=4,
                reason="admin_adjust",
                ref="t:retry",
                idempotency_key="admin_adjust:retry",
            )

        entry = run_in_transaction(db, work)
        assert calls["n"] == 2
        assert entry.delta == 4
    with app.state.session_factory() as db:
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS + 4


def test_run_in_transaction_reraises_after_attempts(app: FastAPI, user: uuid.UUID):
    _open(app, user)
    with app.state.session_factory() as db:

        def always_conflict():
            raise IntegrityError("stmt", {}, Exception("dup"))

        with pytest.raises(IntegrityError):
            run_in_transaction(db, always_conflict, attempts=2)


def test_same_key_from_second_session_is_idempotent(app: FastAPI, user: uuid.UUID):
    _open(app, user)
    key = "admin_adjust:race"
    with app.state.session_factory() as db_a, app.state.session_factory() as db_b:
        first = points.credit(
            db_a, user_id=user, delta=10, reason="admin_adjust", ref="t:1", idempotency_key=key
        )
        db_a.commit()
        # 另一会话重放同一幂等键：命中已提交流水，原样返回，不再改余额
        again = points.credit(
            db_b, user_id=user, delta=10, reason="admin_adjust", ref="t:1", idempotency_key=key
        )
        db_b.commit()
        assert again.id == first.id
    with app.state.session_factory() as db:
        rows = db.scalars(select(LedgerEntry).where(LedgerEntry.idempotency_key == key)).all()
        assert len(rows) == 1
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS + 10


def test_registry_and_direction_are_enforced(app: FastAPI, user: uuid.UUID):
    with app.state.session_factory() as db:
        with pytest.raises(ValueError):
            points.credit(
                db, user_id=user, delta=1, reason="no_such", ref="x", idempotency_key="a:b"
            )
        with pytest.raises(ValueError):
            points.credit(
                db, user_id=user, delta=1, reason="intel_card", ref="x", idempotency_key="a:b"
            )
        with pytest.raises(ValueError):
            points.debit(
                db, user_id=user, amount=1, reason="prediction", ref="x", idempotency_key="a:b"
            )
        with pytest.raises(ValueError):
            points.credit(
                db, user_id=user, delta=-1, reason="admin_adjust", ref="x", idempotency_key="a:b"
            )
        with pytest.raises(ValueError):
            points.credit(
                db, user_id=user, delta=1, reason="admin_adjust", ref="x", idempotency_key="nocolon"
            )
        db.rollback()


def test_ledger_pagination_has_no_gaps_or_duplicates(app: FastAPI, user: uuid.UUID):
    for i in range(7):
        _commit_credit(app, user, 1, f"admin_adjust:p{i}")
    seen: list[int] = []
    cursor = None
    with app.state.session_factory() as db:
        while True:
            page, cursor = points.ledger_page(db, user_id=user, cursor=cursor, limit=3)
            seen.extend(e.seq for e in page)
            if cursor is None:
                break
        assert seen == sorted(seen, reverse=True)
        assert len(seen) == len(set(seen)) == 8  # 欢迎 + 7 笔
        assert seen[-1] == 1
        with pytest.raises(AppError) as exc:
            points.ledger_page(db, user_id=user, cursor="!!!", limit=3)
        assert exc.value.params == {"field": "cursor"}


def test_totals_by_user_orders_by_sum_then_id(app: FastAPI, user: uuid.UUID):
    _commit_credit(app, user, 40, "admin_adjust:t1")
    with app.state.session_factory() as db:
        rows = points.totals_by_user(db, reasons=["admin_adjust", "welcome"])
        assert rows[0] == (user, points.WELCOME_POINTS + 40)
        since = utcnow().replace(year=2000)
        assert points.sum_since(db, user_id=user, reasons=["admin_adjust"], since=since) == 40


def test_delete_save_keeps_ledger_with_null_save_id(
    registered_client: TestClient, app: FastAPI, user: uuid.UUID
):
    resp = registered_client.post("/api/v1/saves", json={"name": "s1"})
    assert resp.status_code == 201, resp.text
    sid = uuid.UUID(resp.json()["id"])
    with app.state.session_factory() as db:
        points.credit(
            db,
            user_id=user,
            delta=3,
            reason="admin_adjust",
            ref="t:s",
            idempotency_key="admin_adjust:s",
            save_id=sid,
        )
        db.commit()
    assert registered_client.delete(f"/api/v1/saves/{sid}").status_code == 204
    with app.state.session_factory() as db:
        entry = db.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == "admin_adjust:s")
        )
        assert entry is not None and entry.save_id is None
        assert points.balance(db, user_id=user) == points.WELCOME_POINTS + 3


def test_delete_user_cascades_account_and_ledger(
    registered_client: TestClient, app: FastAPI, user: uuid.UUID
):
    _commit_credit(app, user, 1, "admin_adjust:cascade")
    assert registered_client.delete("/api/v1/me").status_code == 204
    with app.state.session_factory() as db:
        assert db.get(PointAccount, user) is None
        assert db.scalars(select(LedgerEntry).where(LedgerEntry.user_id == user)).all() == []
