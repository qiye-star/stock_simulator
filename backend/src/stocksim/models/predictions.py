"""预测卡（02 §1、§3、§9）：prediction_settings（存档级模式）、prediction_cards（卡片）、
prediction_answers（逐题作答与结算结果）。卡片随存档级联删除；已入账的流水保留。
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class PredictionSetting(Base):
    """存档级预测模式（pause = 出卡并暂停；off = 不出卡）。"""

    __tablename__ = "prediction_settings"
    __table_args__ = (CheckConstraint("mode IN ('pause','off')", name="mode_valid"),)

    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(8), default="pause", server_default="pause")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PredictionCard(Base):
    __tablename__ = "prediction_cards"
    __table_args__ = (
        UniqueConstraint("save_id", "event_id"),
        CheckConstraint(
            "status IN ('open','answered','settled','expired','void')", name="status_valid"
        ),
        Index("ix_prediction_cards_save_status", "save_id", "status"),
        Index("ix_prediction_cards_user_settled", "user_id", "settled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("saves.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(16))
    events_ruleset: Mapped[int] = mapped_column(Integer)
    rules_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    opened_trading_tick: Mapped[int] = mapped_column(BigInteger)
    opened_tick: Mapped[int] = mapped_column(BigInteger)
    opened_trading_day: Mapped[int] = mapped_column(Integer)
    deadline_trading_tick: Mapped[int] = mapped_column(BigInteger)
    window_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    paused_by_card: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(json_column_type())
    outcomes: Mapped[dict[str, Any] | None] = mapped_column(json_column_type(), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    answered_trading_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_capped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("point_ledger.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


class PredictionAnswer(Base):
    __tablename__ = "prediction_answers"
    __table_args__ = (
        UniqueConstraint("card_id", "qid"),
        CheckConstraint("kind IN ('bucket','rank','binary')", name="kind_valid"),
        CheckConstraint("qid IN ('dir','rank','rumor')", name="qid_valid"),
        Index("ix_prediction_answers_user_scored", "user_id", "scored_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    card_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prediction_cards.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    qid: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(8))
    answer: Mapped[dict[str, Any]] = mapped_column(json_column_type())
    pick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p_outcome_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uniform_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
