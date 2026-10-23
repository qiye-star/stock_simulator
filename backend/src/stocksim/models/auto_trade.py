"""自动交易：auto_trade_configs（条件单）、auto_trade_events（执行记录）。"""

import uuid
from datetime import datetime

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
from stocksim.db.types import Money, UTCDateTime


class AutoTradeConfig(Base):
    """条件单。同一存档内 (stock_code, direction) 唯一，对应 AUTO_CONFIG_DUPLICATE。

    单位约定：price/profit 条件的阈值为整数分（condition_value_cents）；
    percentage 条件及止盈止损为百分比乘 100 的整数（如 2.5% -> 250，condition_pct100）。
    """

    __tablename__ = "auto_trade_configs"
    __table_args__ = (
        UniqueConstraint("save_id", "stock_code", "direction"),
        CheckConstraint("direction IN ('buy','sell')", name="direction_valid"),
        CheckConstraint(
            "condition_type IN ('price','percentage','profit','time')", name="condition_type_valid"
        ),
        CheckConstraint("condition_operator IN ('above','below','equal')", name="operator_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    direction: Mapped[str] = mapped_column(String(4))
    condition_type: Mapped[str] = mapped_column(String(12))
    condition_operator: Mapped[str] = mapped_column(String(8))
    condition_value_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    condition_pct100: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    price_type: Mapped[str] = mapped_column(String(8), default="market")
    limit_price_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    stop_loss_pct100: Mapped[int | None] = mapped_column(Integer, nullable=True)
    take_profit_pct100: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_trades: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_amount_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AutoTradeEvent(Base):
    """自动交易执行记录（legacy 保留最近 50 条，服务层负责裁剪）。"""

    __tablename__ = "auto_trade_events"
    __table_args__ = (Index("ix_auto_trade_events_save_created", "save_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("saves.id", ondelete="CASCADE"))
    config_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auto_trade_configs.id", ondelete="SET NULL"), nullable=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    direction: Mapped[str] = mapped_column(String(4))
    condition_type: Mapped[str] = mapped_column(String(12))
    success: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(String(255), default="")
    amount_cents: Mapped[int] = mapped_column(Money, default=0)
    pnl_cents: Mapped[int] = mapped_column(Money, default=0)
    pnl_pct100: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_price_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    sell_price_cents: Mapped[int | None] = mapped_column(Money, nullable=True)
    tick: Mapped[int] = mapped_column(BigInteger)
    trading_day: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
