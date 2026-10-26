# ruff: noqa: E501  (手写 SQLite DDL 与迁移说明，行长不适用)
"""daily challenge

给 saves 增加 market_source_id（挑战玩家存档 → master 行情），user_id 改为可空（挑战 master 无主人），
并新建 challenges / challenge_rounds / challenge_entries / challenge_answers 四张表（03 §6.1、§6.2）。

SQLite 注意：不能用 batch_alter_table 重建 saves。迁移引擎开启了 foreign_keys=ON，DROP TABLE saves
会按 ON DELETE CASCADE 删除全部子表（trades、holdings、equity_snapshots …）。因此 SQLite 路径用
autocommit_block 先关闭外键，在手写的 BEGIN/COMMIT 事务内做"建新表 → 拷贝 → 删旧表 → 改名"，
并在提交前 PRAGMA foreign_key_check；最后恢复 foreign_keys=ON。PostgreSQL 直接用 ALTER。

Revision ID: f5aae30ea648
Revises: 8ed22ae1e201
Create Date: 2026-10-26 16:30:41.351736

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import stocksim.db.types

# revision identifiers, used by Alembic.
revision: str = "f5aae30ea648"
down_revision: str | Sequence[str] | None = "8ed22ae1e201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CK_USER_OR_MARKET = "ck_saves_user_or_market"
CK_MARKET_SOURCE_MODE = "ck_saves_market_source_mode"
FK_MARKET_SOURCE = "fk_saves_market_source_id_saves"
IX_MARKET_SOURCE = "ix_saves_market_source_id"
IX_USER_ID = "ix_saves_user_id"

# 旧 saves 的全部列（不含本迁移新增的 market_source_id），拷贝时按此顺序
_OLD_SAVES_COLUMNS = (
    "id, user_id, name, mode, initial_fund_cents, cash_cents, buy_fee_rate, sell_fee_rate, "
    "t0_mode, trade_unit, market_seed, tick, trade_seq, trading_day, clock_minute, paused, "
    "last_tick_at, auto_enabled, auto_paused, auto_max_total_trades, version, created_at, "
    "updated_at, clock_rules, events_enabled, events_ruleset"
)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _saves_ddl(name: str, *, user_nullable: bool, with_market: bool) -> str:
    """SQLite 下 saves 的完整建表语句（与 ORM 约束一致，名称按命名约定展开）。"""
    user_null = "" if user_nullable else " NOT NULL"
    market_col = ",\n    market_source_id CHAR(32)" if with_market else ""
    market_checks = (
        f",\n    CONSTRAINT {CK_USER_OR_MARKET} CHECK (user_id IS NOT NULL OR mode = 'challenge_market'),"
        f"\n    CONSTRAINT {CK_MARKET_SOURCE_MODE} CHECK (market_source_id IS NULL OR mode = 'challenge')"
        if with_market and user_nullable
        else ""
    )
    market_fk = (
        f",\n    CONSTRAINT {FK_MARKET_SOURCE} FOREIGN KEY(market_source_id) "
        "REFERENCES saves (id) ON DELETE SET NULL"
        if with_market
        else ""
    )
    return f"""
CREATE TABLE {name} (
    id CHAR(32) NOT NULL,
    user_id CHAR(32){user_null},
    name VARCHAR(20) DEFAULT '' NOT NULL,
    mode VARCHAR(16) DEFAULT 'normal' NOT NULL,
    initial_fund_cents BIGINT NOT NULL,
    cash_cents BIGINT NOT NULL,
    buy_fee_rate NUMERIC(8, 6) NOT NULL,
    sell_fee_rate NUMERIC(8, 6) NOT NULL,
    t0_mode BOOLEAN DEFAULT '0' NOT NULL,
    trade_unit INTEGER DEFAULT '1' NOT NULL,
    market_seed BIGINT NOT NULL,
    tick BIGINT DEFAULT '0' NOT NULL,
    trade_seq BIGINT DEFAULT '0' NOT NULL,
    trading_day INTEGER DEFAULT '1' NOT NULL,
    clock_minute INTEGER DEFAULT '570' NOT NULL,
    paused BOOLEAN DEFAULT '0' NOT NULL,
    last_tick_at DATETIME,
    auto_enabled BOOLEAN DEFAULT '0' NOT NULL,
    auto_paused BOOLEAN DEFAULT '0' NOT NULL,
    auto_max_total_trades INTEGER DEFAULT '100' NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    clock_rules INTEGER NOT NULL DEFAULT 1 CONSTRAINT ck_saves_clock_rules_valid CHECK (clock_rules IN (1, 2)),
    events_enabled BOOLEAN NOT NULL DEFAULT 0,
    events_ruleset INTEGER NOT NULL DEFAULT 0 CONSTRAINT ck_saves_events_ruleset_non_negative CHECK (events_ruleset >= 0){market_col},
    CONSTRAINT pk_saves PRIMARY KEY (id),
    CONSTRAINT ck_saves_clock_minute_range CHECK (clock_minute >= 0 AND clock_minute < 1440),
    CONSTRAINT ck_saves_seed_non_negative CHECK (market_seed >= 0),
    CONSTRAINT ck_saves_tick_non_negative CHECK (tick >= 0),
    CONSTRAINT ck_saves_trade_unit_valid CHECK (trade_unit IN (1, 100)){market_checks},
    CONSTRAINT fk_saves_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE{market_fk}
)
"""


def _rebuild_saves_sqlite(*, up: bool) -> None:
    """SQLite：不经 batch，关闭外键后重建 saves（保留全部行与子表）。"""
    conn = op.get_bind()
    with op.get_context().autocommit_block():
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("BEGIN")
        try:
            conn.exec_driver_sql(_saves_ddl("saves_new", user_nullable=up, with_market=up))
            conn.exec_driver_sql(
                f"INSERT INTO saves_new ({_OLD_SAVES_COLUMNS}) SELECT {_OLD_SAVES_COLUMNS} FROM saves"
            )
            conn.exec_driver_sql("DROP TABLE saves")
            conn.exec_driver_sql("ALTER TABLE saves_new RENAME TO saves")
            conn.exec_driver_sql(f"CREATE INDEX {IX_USER_ID} ON saves (user_id)")
            if up:
                conn.exec_driver_sql(f"CREATE INDEX {IX_MARKET_SOURCE} ON saves (market_source_id)")
            violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"saves 重建后外键不一致：{len(violations)} 行")
            conn.exec_driver_sql("COMMIT")
        except BaseException:
            conn.exec_driver_sql("ROLLBACK")
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _create_challenge_tables() -> None:
    op.create_table(
        "challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="scheduled", nullable=False),
        sa.Column("schedule_mode", sa.String(length=8), server_default="daily", nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("events_ruleset", sa.Integer(), nullable=False),
        sa.Column("clock_rules", sa.Integer(), server_default="2", nullable=False),
        sa.Column("seed_attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("market_seed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("seed_salt", sa.String(length=32), server_default="", nullable=False),
        sa.Column("seed_commitment", sa.String(length=64), server_default="", nullable=False),
        sa.Column("master_save_id", sa.Uuid(), nullable=True),
        sa.Column("start_minute", sa.Integer(), server_default="570", nullable=False),
        sa.Column("tick_ms", sa.Integer(), nullable=False),
        sa.Column("end_tt", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("starts_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("entry_closes_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("final_resume_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("ends_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column(
            "settle_expected_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("eligible_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("void_reason", sa.String(length=32), nullable=True),
        sa.Column("settled_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("revealed_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schedule_mode IN ('daily', 'compact')",
            name=op.f("ck_challenges_schedule_mode_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'running', 'settled', 'void')",
            name=op.f("ck_challenges_status_valid"),
        ),
        sa.CheckConstraint("clock_rules = 2", name=op.f("ck_challenges_clock_rules_v2")),
        sa.CheckConstraint("end_tt >= 0", name=op.f("ck_challenges_end_tt_non_negative")),
        sa.CheckConstraint("market_seed >= 0", name=op.f("ck_challenges_seed_non_negative")),
        sa.ForeignKeyConstraint(
            ["master_save_id"],
            ["saves.id"],
            name=op.f("fk_challenges_master_save_id_saves"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challenges")),
        sa.UniqueConstraint("challenge_date", name=op.f("uq_challenges_challenge_date")),
    )

    op.create_table(
        "challenge_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("save_id", sa.Uuid(), nullable=True),
        sa.Column("eligible", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("joined_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("joined_tt", sa.BigInteger(), nullable=False),
        sa.Column("answered_rounds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("final_equity_cents", stocksim.db.types.Money(), nullable=True),
        sa.Column("return_bp", sa.Integer(), nullable=True),
        sa.Column("forecast_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("trade_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("points_awarded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("settled_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenges.id"],
            name=op.f("fk_challenge_entries_challenge_id_challenges"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["save_id"],
            ["saves.id"],
            name=op.f("fk_challenge_entries_save_id_saves"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_challenge_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challenge_entries")),
        sa.UniqueConstraint(
            "challenge_id", "user_id", name=op.f("uq_challenge_entries_challenge_id_user_id")
        ),
        sa.UniqueConstraint("save_id", name=op.f("uq_challenge_entries_save_id")),
    )
    op.create_index(
        op.f("ix_challenge_entries_challenge_id"), "challenge_entries", ["challenge_id"]
    )
    op.create_index(op.f("ix_challenge_entries_user_id"), "challenge_entries", ["user_id"])

    op.create_table(
        "challenge_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=16), nullable=False),
        sa.Column("from_tt", sa.BigInteger(), nullable=False),
        sa.Column("hold_tt", sa.BigInteger(), nullable=False),
        sa.Column("resume_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("hold_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("closes_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column(
            "resolve_tts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "questions",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "outcomes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("opened_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("closed_hooked_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("answer_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "answer_count >= 0", name=op.f("ck_challenge_rounds_answer_count_non_negative")
        ),
        sa.CheckConstraint(
            "round_index >= 1", name=op.f("ck_challenge_rounds_round_index_positive")
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenges.id"],
            name=op.f("fk_challenge_rounds_challenge_id_challenges"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challenge_rounds")),
        sa.UniqueConstraint(
            "challenge_id", "event_id", name=op.f("uq_challenge_rounds_challenge_id_event_id")
        ),
        sa.UniqueConstraint(
            "challenge_id",
            "round_index",
            name=op.f("uq_challenge_rounds_challenge_id_round_index"),
        ),
    )
    op.create_index(op.f("ix_challenge_rounds_challenge_id"), "challenge_rounds", ["challenge_id"])

    op.create_table(
        "challenge_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column(
            "answers",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "first_submitted_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("updated_at", stocksim.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("submitted_tt", sa.BigInteger(), nullable=False),
        sa.Column(
            "results",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("round_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_challenge_answers_revision_positive")),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["challenge_entries.id"],
            name=op.f("fk_challenge_answers_entry_id_challenge_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["challenge_rounds.id"],
            name=op.f("fk_challenge_answers_round_id_challenge_rounds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challenge_answers")),
        sa.UniqueConstraint(
            "round_id", "entry_id", name=op.f("uq_challenge_answers_round_id_entry_id")
        ),
    )
    op.create_index(op.f("ix_challenge_answers_entry_id"), "challenge_answers", ["entry_id"])


def upgrade() -> None:
    """Upgrade schema."""
    _create_challenge_tables()

    if _is_sqlite():
        _rebuild_saves_sqlite(up=True)
        return

    op.add_column("saves", sa.Column("market_source_id", sa.Uuid(), nullable=True))
    op.alter_column("saves", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.create_index(op.f(IX_MARKET_SOURCE), "saves", ["market_source_id"])
    op.create_foreign_key(
        FK_MARKET_SOURCE, "saves", "saves", ["market_source_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        CK_USER_OR_MARKET, "saves", "user_id IS NOT NULL OR mode = 'challenge_market'"
    )
    op.create_check_constraint(
        CK_MARKET_SOURCE_MODE, "saves", "market_source_id IS NULL OR mode = 'challenge'"
    )


def downgrade() -> None:
    """Downgrade schema。先删挑战存档（子表级联），再恢复 user_id 非空、删除 market_source_id。"""
    op.drop_index(op.f("ix_challenge_answers_entry_id"), table_name="challenge_answers")
    op.drop_table("challenge_answers")
    op.drop_index(op.f("ix_challenge_rounds_challenge_id"), table_name="challenge_rounds")
    op.drop_table("challenge_rounds")
    op.drop_index(op.f("ix_challenge_entries_user_id"), table_name="challenge_entries")
    op.drop_index(op.f("ix_challenge_entries_challenge_id"), table_name="challenge_entries")
    op.drop_table("challenge_entries")
    op.drop_table("challenges")

    # 挑战存档（玩家与 master）在旧版本中不存在；外键开启时 DELETE 会级联清掉它们的成交与持仓
    op.execute("DELETE FROM saves WHERE mode IN ('challenge', 'challenge_market')")

    if _is_sqlite():
        _rebuild_saves_sqlite(up=False)
        return

    op.drop_constraint(CK_MARKET_SOURCE_MODE, "saves", type_="check")
    op.drop_constraint(CK_USER_OR_MARKET, "saves", type_="check")
    op.drop_constraint(FK_MARKET_SOURCE, "saves", type_="foreignkey")
    op.drop_index(op.f(IX_MARKET_SOURCE), table_name="saves")
    op.alter_column("saves", "user_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("saves", "market_source_id")
