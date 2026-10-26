"""积分账本（02 §1.1、§6）：point_accounts（余额，乐观锁）、point_ledger（流水）、
user_titles（称号）。

积分属于用户，不属于存档：删存档不影响余额与流水（流水 save_id 置 NULL），删用户级联删除。
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import UTCDateTime, json_column_type


class PointAccount(Base):
    __tablename__ = "point_accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_non_negative"),
        CheckConstraint("lifetime_earned >= 0", name="lifetime_earned_non_negative"),
        CheckConstraint("lifetime_spent >= 0", name="lifetime_spent_non_negative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    lifetime_earned: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    lifetime_spent: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    entry_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    equipped_title: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    # 乐观锁：credit/debit 每次改余额都带 version（与 saves 同一套机制，三种方言通用）
    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


class LedgerEntry(Base):
    __tablename__ = "point_ledger"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("user_id", "seq"),
        CheckConstraint("balance_after >= 0", name="balance_after_non_negative"),
        Index("ix_point_ledger_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    delta: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(24))
    ref: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(96))
    save_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="SET NULL"), index=True, nullable=True
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(json_column_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserTitle(Base):
    """用户级称号解锁记录（02 §8）。"""

    __tablename__ = "user_titles"
    __table_args__ = (UniqueConstraint("user_id", "title_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title_id: Mapped[str] = mapped_column(String(32))
    unlocked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
