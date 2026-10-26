"""预测市场（模式 D，04 §6）：prediction_markets、prediction_market_outcomes、prediction_positions、
prediction_trades、prediction_settlements。

积分列用 BigInteger（积分不是钱，不用 Money）。市场行带 version 乐观锁
（SQLite 无 FOR UPDATE 时靠它）。
市场只挂在挑战上：challenge_id 级联删除；用户删除时持仓、成交、结算级联删除，q 不回退（04 §6）。
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


class PredictionMarket(Base):
    """一个预测市场（分档或传闻）。status 由生命周期服务按公共 tt 迁移（04 §3.6）。"""

    __tablename__ = "prediction_markets"
    __table_args__ = (
        UniqueConstraint("challenge_id", "event_id", "kind"),
        Index("ix_prediction_markets_challenge_status", "challenge_id", "status"),
        CheckConstraint("kind IN ('bucket', 'rumor')", name="kind_valid"),
        CheckConstraint(
            "status IN ('scheduled', 'open', 'closed', 'resolved', 'voided')",
            name="status_valid",
        ),
        CheckConstraint("n_outcomes BETWEEN 2 AND 8", name="n_outcomes_range"),
        CheckConstraint("pool_points >= 0", name="pool_non_negative"),
        CheckConstraint("liquidity_b_milli >= 0", name="liquidity_b_non_negative"),
        CheckConstraint("subsidy_points >= 0", name="subsidy_non_negative"),
        CheckConstraint("trade_seq >= 0", name="trade_seq_non_negative"),
        CheckConstraint("volume_shares >= 0", name="volume_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenges.id", ondelete="CASCADE")
    )
    event_id: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="scheduled", server_default="scheduled")
    # 服务端问题定义（PmQuestionOut 的来源）：scope/industry/code/from_day/to_day/edges_bp
    question: Mapped[Any] = mapped_column(json_column_type())
    n_outcomes: Mapped[int] = mapped_column(Integer)
    prior_ppm: Mapped[Any] = mapped_column(json_column_type())
    events_ruleset: Mapped[int] = mapped_column(Integer)
    # 保密：sha256 指纹，永不外发（04 §3.5 event_mismatch 对比用）
    event_fingerprint: Mapped[str] = mapped_column(String(64))
    open_tt: Mapped[int] = mapped_column(BigInteger)
    close_tt: Mapped[int] = mapped_column(BigInteger)
    resolve_tt: Mapped[int] = mapped_column(BigInteger)
    close_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # 开市时写入（scheduled→open 的条件迁移，只写一次）
    liquidity_b_milli: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    subsidy_points: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # 结算/作废时写入，可为负（04 §3.5）
    subsidy_returned_points: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pool_points: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    prices_ppm: Mapped[Any | None] = mapped_column(json_column_type(), nullable=True)
    trade_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    volume_shares: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    traders: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    winning_outcome: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_value_bp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": version}


class PredictionMarketOutcome(Base):
    """市场的选项（每个选项一行）。q0 为虚拟先验份额，q 为当前累计份额（含 q0）。"""

    __tablename__ = "prediction_market_outcomes"
    __table_args__ = (
        UniqueConstraint("market_id", "idx"),
        CheckConstraint("q0_shares >= 0", name="q0_non_negative"),
        CheckConstraint("q_shares >= q0_shares", name="q_not_below_q0"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prediction_markets.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(16))
    q0_shares: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    q_shares: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class PredictionPosition(Base):
    """用户在某选项上的持仓。cost_points 为剩余份额的平均成本（卖出按比例扣减）。"""

    __tablename__ = "prediction_positions"
    __table_args__ = (
        UniqueConstraint("market_id", "user_id", "outcome_idx"),
        Index("ix_prediction_positions_user", "user_id"),
        CheckConstraint("shares >= 0", name="shares_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prediction_markets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    outcome_idx: Mapped[int] = mapped_column(Integer)
    shares: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    bought_points: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    sold_points: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cost_points: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class PredictionTrade(Base):
    """成交流水。seq 为市场内连续序号（等于成交行数）；idempotency_key 按用户唯一（04 §5.3）。"""

    __tablename__ = "prediction_trades"
    __table_args__ = (
        UniqueConstraint("market_id", "seq"),
        UniqueConstraint("user_id", "idempotency_key"),
        Index("ix_prediction_trades_user_created", "user_id", "created_at"),
        CheckConstraint("side IN ('buy', 'sell')", name="side_valid"),
        CheckConstraint("shares > 0", name="shares_positive"),
        CheckConstraint("points > 0", name="points_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prediction_markets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    side: Mapped[str] = mapped_column(String(4))
    outcome_idx: Mapped[int] = mapped_column(Integer)
    shares: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(BigInteger)
    price_before_ppm: Mapped[int] = mapped_column(Integer)
    prices_after_ppm: Mapped[Any] = mapped_column(json_column_type())
    public_tt: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PredictionSettlement(Base):
    """结算或作废时每个有持仓用户一行（UQ market_id+user_id 保证只生效一次，04 §5.3）。"""

    __tablename__ = "prediction_settlements"
    __table_args__ = (
        UniqueConstraint("market_id", "user_id"),
        Index("ix_prediction_settlements_user_created", "user_id", "created_at"),
        CheckConstraint("kind IN ('resolved', 'voided')", name="kind_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prediction_markets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8))
    winning_shares: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    payout_points: Mapped[int] = mapped_column(BigInteger)
    net_cost_points: Mapped[int] = mapped_column(BigInteger)
    pnl_points: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
