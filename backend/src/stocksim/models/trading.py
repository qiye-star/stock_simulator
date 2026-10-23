"""交易相关：holdings（持仓）、trades（成交流水，T+1 从此表推导）、watchlist_items（自选）。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import Money, UTCDateTime


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        UniqueConstraint("save_id", "stock_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_price_cents: Mapped[int] = mapped_column(Money)
    total_cost_cents: Mapped[int] = mapped_column(Money)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Trade(Base):
    """成交流水。seq 为存档内单调递增序号（游标分页用），由 services 在存档乐观锁内分配。"""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="side_valid"),
        CheckConstraint("source IN ('manual','auto')", name="source_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        UniqueConstraint("save_id", "seq"),
        UniqueConstraint("save_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("saves.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    stock_code: Mapped[str] = mapped_column(String(6))
    side: Mapped[str] = mapped_column(String(4))
    source: Mapped[str] = mapped_column(String(8))
    price_type: Mapped[str] = mapped_column(String(8), default="market")
    limit_price_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    price_cents: Mapped[int] = mapped_column(Money)
    quantity: Mapped[int] = mapped_column(Integer)
    gross_cents: Mapped[int] = mapped_column(Money)
    fee_cents: Mapped[int] = mapped_column(Money, default=0)
    # 资金变动：买入为负，卖出为正（已扣费）
    cash_delta_cents: Mapped[int] = mapped_column(Money)
    realized_pnl_cents: Mapped[int] = mapped_column(Money, default=0)
    prev_close_cents: Mapped[int] = mapped_column(Money)
    # trade-time 快照：成交前资金（成就 ALL_IN 依赖；由服务层写入）
    fund_before_cents: Mapped[int] = mapped_column(Money, default=0, server_default="0")
    # 客户端 Idempotency-Key（可空；同一存档内唯一，NULL 不参与唯一性）
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tick: Mapped[int] = mapped_column(BigInteger)
    trading_day: Mapped[int] = mapped_column(Integer)
    clock_minute: Mapped[int] = mapped_column(Integer)
    auto_config_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auto_trade_configs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("save_id", "stock_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
