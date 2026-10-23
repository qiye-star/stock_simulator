"""存档相关：saves（主表，乐观锁）、save_stats（1:1）、save_sectors、save_achievements。"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import Money, UTCDateTime


class Save(Base):
    __tablename__ = "saves"
    __table_args__ = (
        CheckConstraint("trade_unit IN (1, 100)", name="trade_unit_valid"),
        CheckConstraint("clock_minute >= 0 AND clock_minute < 1440", name="clock_minute_range"),
        CheckConstraint("tick >= 0", name="tick_non_negative"),
        CheckConstraint("market_seed >= 0", name="seed_non_negative"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(20), default="", server_default="")
    mode: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    initial_fund_cents: Mapped[int] = mapped_column(Money)
    cash_cents: Mapped[int] = mapped_column(Money)
    buy_fee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.0003"))
    sell_fee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.0013"))
    t0_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    trade_unit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # 行情种子，取值 [0, 2^63-1]，splitmix64 计数器 RNG 的 seed
    market_seed: Mapped[int] = mapped_column(BigInteger)
    tick: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    trade_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    trading_day: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    clock_minute: Mapped[int] = mapped_column(Integer, default=570, server_default="570")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    last_tick_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    auto_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    auto_max_total_trades: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    # 乐观锁：必须是 Column 对象而非字符串（SQLAlchemy 2 对字符串不做解析，flush 时报错）
    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


class SaveStats(Base):
    """存档统计（1:1，以 save_id 为主键）。"""

    __tablename__ = "save_stats"

    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True
    )
    trade_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    profit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    loss_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_holdings: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    auto_total_trades: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    auto_success_trades: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    auto_failed_trades: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    auto_total_pnl_cents: Mapped[int] = mapped_column(Money, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class SaveSector(Base):
    """存档交易过的行业（对应 legacy gameStats.sectorsTraded）。"""

    __tablename__ = "save_sectors"
    __table_args__ = (UniqueConstraint("save_id", "sector"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    sector: Mapped[str] = mapped_column(String(16))


class SaveAchievement(Base):
    """存档已解锁成就（achievement_id 为 achievements.js 中的 id）。"""

    __tablename__ = "save_achievements"
    __table_args__ = (UniqueConstraint("save_id", "achievement_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    achievement_id: Mapped[str] = mapped_column(String(64))
    unlocked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
