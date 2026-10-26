"""账号相关：users、sessions、legacy_imports。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import UTCDateTime


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("theme IN ('dark','light','festival')", name="theme_valid"),
        CheckConstraint("lang IN ('zh-CN','en-US')", name="lang_valid"),
        CheckConstraint("refresh_rate_ms > 0", name="refresh_positive"),
        CheckConstraint("clock_speed IN ('fast','normal','slow')", name="clock_speed_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    theme: Mapped[str] = mapped_column(String(16), default="dark", server_default="dark")
    lang: Mapped[str] = mapped_column(String(8), default="zh-CN", server_default="zh-CN")
    refresh_rate_ms: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    tutorial_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # v2 存档的节奏档（每游戏分钟毫秒数由 domain.clock.SPEED_MS_PER_MINUTE 决定）；v1 存档不用
    clock_speed: Mapped[str] = mapped_column(String(8), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    """登录会话。库内只存 token 的 HMAC，不存明文 token。"""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class LegacyImport(Base):
    """旧版（legacy）导出文本导入记录，不保存原始明文数据。"""

    __tablename__ = "legacy_imports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    save_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="SET NULL"), nullable=True
    )
    source_format: Mapped[str] = mapped_column(String(16), default="legacy-xor")
    source_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # imported | failed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
