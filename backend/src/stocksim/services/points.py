"""积分账本（02 §1.1）。积分属于用户。

所有函数 keyword-only，**都不 commit**，由调用方在自己的事务里提交（services/tx.py 包住）。
credit/debit 写完流水后立即 flush，乐观锁与唯一约束冲突原样上抛。

- 幂等：同 (user_id, idempotency_key) 且 (reason, 有符号 delta, save_id) 相同 → 返回已有流水；
  不同 → LedgerConflict。
- 余额不得为负：debit 修改前检查（POINTS_INSUFFICIENT）；DB 的 CHECK 是兜底。
- 开户：credit/debit 内部先 open_account，写入 welcome 流水（seq=1）。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.predictions.constants import WELCOME_POINTS
from stocksim.models import LedgerEntry, PointAccount

__all__ = [
    "REASONS",
    "WELCOME_POINTS",
    "LedgerConflict",
    "balance",
    "count_debits_since",
    "credit",
    "debit",
    "find_entry",
    "ledger_page",
    "open_account",
    "sum_since",
    "totals_by_user",
]

# 来源登记：reason → 允许的方向。新来源在此加一行即可（DB 不对 reason 做 CHECK，只限长度 ≤24）。
REASONS: dict[str, Literal["credit", "debit", "any"]] = {
    "welcome": "credit",  # 开户赠送（B）
    "prediction": "credit",  # 预测卡结算（B）
    "intel_card": "debit",  # 情报卡（B）
    "challenge": "credit",  # 每日挑战奖励（C）
    "market_buy": "debit",  # 预测市场买入（D）
    "market_sell": "credit",  # 预测市场卖出（D）
    "market_payout": "credit",  # 预测市场兑付（D）
    "market_refund": "credit",  # 预测市场作废退款（D）
    "replay_prediction": "credit",  # 真实复盘预测（E）
    "admin_adjust": "any",  # 运维调账（脚本用，不开放 HTTP）
}

MAX_REASON_LEN = 24
MAX_REF_LEN = 64
MAX_KEY_LEN = 96
_KEY_RE = re.compile(r"^[a-z_]+:\S+$")


class LedgerConflict(RuntimeError):
    """同一幂等键对应了不同的 (reason, delta, save_id)：编程错误，应为 500。"""


def _check_meta(reason: str, ref: str, key: str, want: Literal["credit", "debit"]) -> None:
    if reason not in REASONS:
        raise ValueError(f"unknown point reason: {reason}")
    if REASONS[reason] not in (want, "any"):
        raise ValueError(f"reason {reason} is not a {want}")
    if len(reason) > MAX_REASON_LEN or len(ref) > MAX_REF_LEN:
        raise ValueError("reason/ref too long")
    if len(key) > MAX_KEY_LEN or not _KEY_RE.match(key):
        raise ValueError(f"bad idempotency key: {key!r}")


def open_account(db: Session, user_id: uuid.UUID) -> PointAccount:
    """取账户；不存在则创建并写入 welcome 流水（seq=1）。

    并发创建撞主键 → IntegrityError，由调用方重试。
    """
    acct = db.get(PointAccount, user_id)
    if acct is not None:
        return acct
    acct = PointAccount(
        user_id=user_id,
        balance=WELCOME_POINTS,
        lifetime_earned=WELCOME_POINTS,
        lifetime_spent=0,
        entry_seq=1,
    )
    db.add(acct)
    db.add(
        LedgerEntry(
            user_id=user_id,
            seq=1,
            delta=WELCOME_POINTS,
            balance_after=WELCOME_POINTS,
            reason="welcome",
            ref=f"user:{user_id}",
            idempotency_key=f"welcome:{user_id}",
            save_id=None,
        )
    )
    db.flush()
    return acct


def find_entry(db: Session, *, user_id: uuid.UUID, idempotency_key: str) -> LedgerEntry | None:
    return db.scalar(
        select(LedgerEntry).where(
            LedgerEntry.user_id == user_id, LedgerEntry.idempotency_key == idempotency_key
        )
    )


def _apply(
    db: Session,
    *,
    user_id: uuid.UUID,
    signed: int,
    reason: str,
    ref: str,
    idempotency_key: str,
    save_id: uuid.UUID | None,
    meta: Mapping[str, Any] | None,
) -> LedgerEntry:
    existing = find_entry(db, user_id=user_id, idempotency_key=idempotency_key)
    if existing is not None:
        if (existing.reason, existing.delta, existing.save_id) == (reason, signed, save_id):
            return existing
        raise LedgerConflict(f"idempotency key reused with different payload: {idempotency_key}")
    acct = open_account(db, user_id)
    new_balance = acct.balance + signed
    if new_balance < 0:
        raise AppError(
            ErrorCode.POINTS_INSUFFICIENT, {"required": -signed, "balance": acct.balance}
        )
    acct.balance = new_balance
    if signed >= 0:
        acct.lifetime_earned += signed
    else:
        acct.lifetime_spent += -signed
    acct.entry_seq += 1
    entry = LedgerEntry(
        user_id=user_id,
        seq=acct.entry_seq,
        delta=signed,
        balance_after=new_balance,
        reason=reason,
        ref=ref,
        idempotency_key=idempotency_key,
        save_id=save_id,
        meta=dict(meta) if meta is not None else None,
    )
    db.add(entry)
    db.flush()
    return entry


def credit(
    db: Session,
    *,
    user_id: uuid.UUID,
    delta: int,
    reason: str,
    ref: str,
    idempotency_key: str,
    save_id: uuid.UUID | None = None,
    meta: Mapping[str, Any] | None = None,
) -> LedgerEntry:
    """入账 delta ≥ 0（允许 0，用于留痕）。"""
    if isinstance(delta, bool) or not isinstance(delta, int) or delta < 0:
        raise ValueError("credit delta must be a non-negative int")
    _check_meta(reason, ref, idempotency_key, "credit")
    return _apply(
        db,
        user_id=user_id,
        signed=delta,
        reason=reason,
        ref=ref,
        idempotency_key=idempotency_key,
        save_id=save_id,
        meta=meta,
    )


def debit(
    db: Session,
    *,
    user_id: uuid.UUID,
    amount: int,
    reason: str,
    ref: str,
    idempotency_key: str,
    save_id: uuid.UUID | None = None,
    meta: Mapping[str, Any] | None = None,
) -> LedgerEntry:
    """扣账 amount > 0，写入 delta = −amount。

    余额不足抛 POINTS_INSUFFICIENT {required, balance}。
    """
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("debit amount must be a positive int")
    _check_meta(reason, ref, idempotency_key, "debit")
    return _apply(
        db,
        user_id=user_id,
        signed=-amount,
        reason=reason,
        ref=ref,
        idempotency_key=idempotency_key,
        save_id=save_id,
        meta=meta,
    )


def balance(db: Session, *, user_id: uuid.UUID) -> int:
    """无账户返回 0，不建账户。"""
    acct = db.get(PointAccount, user_id)
    return acct.balance if acct is not None else 0


def _encode_cursor(seq: int) -> str:
    raw = json.dumps([seq], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        (seq,) = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise ValueError
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc
    return seq


def ledger_page(
    db: Session,
    *,
    user_id: uuid.UUID,
    cursor: str | None,
    limit: int,
    reasons: Collection[str] | None = None,
) -> tuple[list[LedgerEntry], str | None]:
    """按 seq 降序分页。游标 = base64url(JSON [seq])。"""
    stmt = select(LedgerEntry).where(LedgerEntry.user_id == user_id)
    if cursor is not None:
        stmt = stmt.where(LedgerEntry.seq < _decode_cursor(cursor))
    if reasons:
        stmt = stmt.where(LedgerEntry.reason.in_(sorted(reasons)))
    rows = list(db.scalars(stmt.order_by(LedgerEntry.seq.desc()).limit(limit + 1)))
    if len(rows) > limit:
        page = rows[:limit]
        return page, _encode_cursor(page[-1].seq)
    return rows, None


def totals_by_user(
    db: Session,
    *,
    reasons: Collection[str],
    since: datetime | None = None,
    until: datetime | None = None,
    user_ids: Collection[uuid.UUID] | None = None,
    limit: int = 100,
) -> list[tuple[uuid.UUID, int]]:
    """排行用：按 SUM(delta) 降序、user_id 升序。"""
    total = func.sum(LedgerEntry.delta).label("total")
    stmt = select(LedgerEntry.user_id, total).where(LedgerEntry.reason.in_(sorted(reasons)))
    if since is not None:
        stmt = stmt.where(LedgerEntry.created_at >= since)
    if until is not None:
        stmt = stmt.where(LedgerEntry.created_at < until)
    if user_ids is not None:
        stmt = stmt.where(LedgerEntry.user_id.in_(list(user_ids)))
    stmt = stmt.group_by(LedgerEntry.user_id).order_by(total.desc(), LedgerEntry.user_id.asc())
    return [(uid, int(t)) for uid, t in db.execute(stmt.limit(limit)).all()]


def sum_since(db: Session, *, user_id: uuid.UUID, reasons: Collection[str], since: datetime) -> int:
    """用户在 since 之后、指定来源的 delta 合计（日上限用）。"""
    stmt = select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
        LedgerEntry.user_id == user_id,
        LedgerEntry.reason.in_(sorted(reasons)),
        LedgerEntry.created_at >= since,
    )
    return int(db.scalar(stmt) or 0)


def count_debits_since(db: Session, *, user_id: uuid.UUID, reason: str, since: datetime) -> int:
    """用户在 since 之后、指定来源的扣账笔数（delta < 0；情报卡日限额用）。"""
    stmt = select(func.count()).where(
        LedgerEntry.user_id == user_id,
        LedgerEntry.reason == reason,
        LedgerEntry.delta < 0,
        LedgerEntry.created_at >= since,
    )
    return int(db.scalar(stmt) or 0)
