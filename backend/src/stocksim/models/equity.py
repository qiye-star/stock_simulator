"""权益快照：每存档每交易日收盘一行（资产曲线数据源）。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from stocksim.db.base import Base, utcnow
from stocksim.db.types import Money, UTCDateTime


class EquitySnapshot(Base):
    """交易日 trading_day 收盘时的权益快照。

    由 `services/equity.py` 在交易日切换时按 (save_id, trading_day) 幂等写入（覆盖而非重复）。
    equity_cents = cash_cents + market_value_cents，市值按该日收盘价。
    """

    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("save_id", "trading_day"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    save_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("saves.id", ondelete="CASCADE"), index=True
    )
    trading_day: Mapped[int] = mapped_column(Integer)
    equity_cents: Mapped[int] = mapped_column(Money)
    cash_cents: Mapped[int] = mapped_column(Money)
    market_value_cents: Mapped[int] = mapped_column(Money)
    tick: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
