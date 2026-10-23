"""行情相关：stocks（股票池目录）、market_states（每存档行情快照）、candles（日 K）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import Money, UTCDateTime, json_column_type


class Stock(Base):
    """股票池目录，与 `backend/src/stocksim/domain` 的静态数据同步（由种子脚本写入）。"""

    __tablename__ = "stocks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(6), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    industry: Mapped[str] = mapped_column(String(16))


class MarketState(Base):
    """每个存档一行的行情快照（1:1，以 save_id 为主键）。

    payload: {code: [price, prev_close, open, high, low,
                     daily_vol, prev_daily_vol, avg_vol, cb_cooldown]}
    价格均为整数分；成交量为股数；cb_cooldown 为剩余冷却 tick 数。
    """

    __tablename__ = "market_states"

    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_column_type(), default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Candle(Base):
    """日 K 线，每个存档、股票、交易日一根。"""

    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("save_id", "stock_code", "trading_day"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    trading_day: Mapped[int] = mapped_column(Integer)
    open_cents: Mapped[int] = mapped_column(Money)
    high_cents: Mapped[int] = mapped_column(Money)
    low_cents: Mapped[int] = mapped_column(Money)
    close_cents: Mapped[int] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
