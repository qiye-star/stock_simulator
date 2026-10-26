"""情报卡（02 §7）：边揭示按用户（intel_edge_reveals），传闻提示按存档（intel_rumor_hints）。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import UTCDateTime


class IntelEdgeReveal(Base):
    __tablename__ = "intel_edge_reveals"
    __table_args__ = (
        UniqueConstraint("user_id", "edge_id"),
        CheckConstraint("level IN (1, 2)", name="level_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    edge_id: Mapped[str] = mapped_column(String(40))
    level: Mapped[int] = mapped_column(Integer)
    points_spent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class IntelRumorHint(Base):
    __tablename__ = "intel_rumor_hints"
    __table_args__ = (UniqueConstraint("save_id", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("saves.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(16))
    points_spent: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
