"""每日挑战（模式 C，03 §6.2）：challenges、challenge_rounds、challenge_entries、challenge_answers。

seed 与盐（market_seed、seed_salt）只在服务端落库，结算前由 API 层保密（03 §5）。
JSON 列用 db.types.json_column_type；日期列 challenge_date 为 UTC+8 日历日。
"""

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import Money, UTCDateTime, json_column_type


class Challenge(Base):
    """一天一个挑战（唯一键 challenge_date）。生成后大部分字段冻结，只改 status 与结算字段。"""

    __tablename__ = "challenges"
    __table_args__ = (
        UniqueConstraint("challenge_date"),
        CheckConstraint(
            "status IN ('scheduled', 'running', 'settled', 'void')", name="status_valid"
        ),
        CheckConstraint("schedule_mode IN ('daily', 'compact')", name="schedule_mode_valid"),
        CheckConstraint("clock_rules = 2", name="clock_rules_v2"),
        CheckConstraint("market_seed >= 0", name="seed_non_negative"),
        CheckConstraint("end_tt >= 0", name="end_tt_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    challenge_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="scheduled", server_default="scheduled")
    schedule_mode: Mapped[str] = mapped_column(String(8), default="daily", server_default="daily")
    format_version: Mapped[int] = mapped_column(Integer)
    events_ruleset: Mapped[int] = mapped_column(Integer)
    # 挑战冻结的时钟规则（03 §6.2，固定 2）
    clock_rules: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    seed_attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 保密：结算前不得外发（03 §5）
    market_seed: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    seed_salt: Mapped[str] = mapped_column(String(32), default="", server_default="")
    seed_commitment: Mapped[str] = mapped_column(String(64), default="", server_default="")
    master_save_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="SET NULL"), nullable=True
    )
    start_minute: Mapped[int] = mapped_column(Integer, default=570, server_default="570")
    tick_ms: Mapped[int] = mapped_column(Integer)
    # 保密：最后一题判定 tick、结束时刻（03 §5 #8）
    end_tt: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    entry_closes_at: Mapped[datetime] = mapped_column(UTCDateTime())
    final_resume_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    settle_expected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    eligible_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    void_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


class ChallengeRound(Base):
    """回合（一个回合事件 = 一张预测卡）。hold_tt 停顿点；resolve_tts 为 {qid: tt}（生成时写）。"""

    __tablename__ = "challenge_rounds"
    __table_args__ = (
        UniqueConstraint("challenge_id", "round_index"),
        UniqueConstraint("challenge_id", "event_id"),
        CheckConstraint("round_index >= 1", name="round_index_positive"),
        CheckConstraint("answer_count >= 0", name="answer_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    round_index: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(String(16))
    from_tt: Mapped[int] = mapped_column(BigInteger)
    hold_tt: Mapped[int] = mapped_column(BigInteger)
    resume_at: Mapped[datetime] = mapped_column(UTCDateTime())
    hold_at: Mapped[datetime] = mapped_column(UTCDateTime())
    closes_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resolve_tts: Mapped[Any] = mapped_column(json_column_type())
    questions: Mapped[Any | None] = mapped_column(json_column_type(), nullable=True)
    outcomes: Mapped[Any] = mapped_column(json_column_type())
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    closed_hooked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    answer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ChallengeEntry(Base):
    """报名（每人每挑战一份）。save_id 指向玩家挑战存档；存档清理后置空，成绩保留。"""

    __tablename__ = "challenge_entries"
    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id"),
        UniqueConstraint("save_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    save_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="SET NULL"), nullable=True
    )
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime())
    joined_tt: Mapped[int] = mapped_column(BigInteger)
    answered_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_equity_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    return_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forecast_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    trade_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ChallengeAnswer(Base):
    """回合作答（每人每回合一份，revision 计修改次数）。results 为逐题判定结果（生成后补齐）。"""

    __tablename__ = "challenge_answers"
    __table_args__ = (
        UniqueConstraint("round_id", "entry_id"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenge_rounds.id", ondelete="CASCADE")
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenge_entries.id", ondelete="CASCADE"), index=True
    )
    answers: Mapped[Any] = mapped_column(json_column_type())
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_submitted_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    submitted_tt: Mapped[int] = mapped_column(BigInteger)
    results: Mapped[Any] = mapped_column(json_column_type())
    round_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


__all__ = ["Challenge", "ChallengeAnswer", "ChallengeEntry", "ChallengeRound"]
