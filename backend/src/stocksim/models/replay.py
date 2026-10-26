"""真实复盘（模式 E，05 §5.2）：replay_levels、replay_level_versions、replay_sessions、
replay_predictions。

关卡包（JSON）不可变地按版本入库；会话固定引用版本 ID。复盘会话本体是 `saves.mode='replay'` 的存档，
replay_sessions 以 save_id 为主键，与 saves 1:1。
replay_levels.current_version_id 与 replay_level_versions.level_id 互相引用，前者 use_alter=True。
"""

import uuid
from datetime import datetime
from typing import Any

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
from stocksim.db.types import Money, UTCDateTime, json_column_type


class ReplayLevel(Base):
    """关卡（稳定的 slug）。标题与导语取自当前版本；匿名标题在 *_masked 列。"""

    __tablename__ = "replay_levels"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="status_valid"),
        CheckConstraint("kind IN ('curated', 'generated', 'custom')", name="kind_valid"),
        CheckConstraint("difficulty BETWEEN 1 AND 3", name="difficulty_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    title_masked: Mapped[str] = mapped_column(String(64))
    teaser: Mapped[str] = mapped_column(String(500))
    teaser_masked: Mapped[str] = mapped_column(String(500))
    tags: Mapped[list[str]] = mapped_column(json_column_type(), default=list)
    difficulty: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="curated", server_default="curated")
    status: Mapped[str] = mapped_column(String(16), default="published", server_default="published")
    masked_allowed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    play_days: Mapped[int] = mapped_column(Integer)
    stock_count: Mapped[int] = mapped_column(Integer)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "replay_level_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_replay_levels_current_version_id",
        ),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ReplayLevelVersion(Base):
    """关卡包的一个不可变版本。同一 (level, version) 的内容 sha256 不得变化。"""

    __tablename__ = "replay_level_versions"
    __table_args__ = (UniqueConstraint("level_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    level_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("replay_levels.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    format_version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    pack: Mapped[dict[str, Any]] = mapped_column(json_column_type())
    builder_version: Mapped[str] = mapped_column(String(32), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ReplaySession(Base):
    """复盘会话（1:1 于 saves，save_id 为主键）。积分、结算指标在结算时写入。"""

    __tablename__ = "replay_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'settled')", name="status_valid"),
        Index("ix_replay_sessions_level_version", "level_version_id"),
    )

    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True
    )
    # 冗余列，便于按用户列出会话（与 saves.user_id 同值）
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    level_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("replay_level_versions.id", ondelete="RESTRICT")
    )
    masked: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    final_equity_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    return_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    benchmark_return_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excess_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_total: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # 创建时判定：该用户此前没有同一关卡的会话。只有首次会话的预测才入账（05 §1.5）
    is_first_attempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)



class ReplayPrediction(Base):
    """复盘题的作答与计分（05 §5.6）。answer 为本会话可见代码（匿名时为别名）。"""

    __tablename__ = "replay_predictions"
    __table_args__ = (
        UniqueConstraint("save_id", "question_id"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("points IS NULL OR points >= 0", name="points_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(String(16))
    answer: Mapped[dict[str, Any] | None] = mapped_column(json_column_type(), nullable=True)
    submitted_tick: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ledger_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
