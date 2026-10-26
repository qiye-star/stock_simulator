"""每日挑战迁移（f5aae30ea648）：saves 重建不丢存量数据与子表；新约束生效；降级恢复。

SQLite 下 saves 通过手写重建（关闭外键），这里用真实老库（8ed22ae1e201）灌数据后升降级验证。
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from stocksim.db.session import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
PRE_REVISION = "8ed22ae1e201"
HEAD_REVISION = "f5aae30ea648"
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url
    return cfg


def _hex() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'mig.db'}"


def _insert_legacy(url: str) -> dict[str, str]:
    """在旧 head 上灌一个用户、一个普通存档及其子表。返回各表主键，供升降级后核对。"""
    ids = {"user": _hex(), "save": _hex()}
    engine = make_engine(url)
    try:
        with engine.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO users (id, username, password_hash, theme, lang, refresh_rate_ms, "
                "tutorial_completed, clock_speed, created_at, updated_at) VALUES "
                "(?, 'legacy', 'x', 'dark', 'zh-CN', 3000, 0, 'normal', ?, ?)",
                (ids["user"], NOW, NOW),
            )
            c.exec_driver_sql(
                "INSERT INTO saves (id, user_id, name, mode, initial_fund_cents, cash_cents, "
                "buy_fee_rate, sell_fee_rate, t0_mode, trade_unit, market_seed, tick, trade_seq, "
                "trading_day, clock_minute, paused, auto_enabled, auto_paused, "
                "auto_max_total_trades, version, created_at, updated_at, clock_rules, "
                "events_enabled, events_ruleset) VALUES "
                "(?, ?, 'old', 'normal', 100000000, 99000000, 0.0003, 0.0013, 0, 100, 12345, 7, 1, "
                "1, 580, 0, 0, 0, 100, 1, ?, ?, 1, 0, 0)",
                (ids["save"], ids["user"], NOW, NOW),
            )
            c.exec_driver_sql(
                "INSERT INTO save_stats (save_id, trade_count, profit_count, loss_count, "
                "max_holdings, auto_total_trades, auto_success_trades, auto_failed_trades, "
                "auto_total_pnl_cents, updated_at) VALUES (?, 3, 1, 1, 2, 0, 0, 0, 0, ?)",
                (ids["save"], NOW),
            )
            c.exec_driver_sql(
                "INSERT INTO holdings (id, save_id, stock_code, quantity, avg_price_cents, "
                "total_cost_cents, updated_at) VALUES (?, ?, '600036', 200, 1000, 200000, ?)",
                (_hex(), ids["save"], NOW),
            )
            c.exec_driver_sql(
                "INSERT INTO equity_snapshots (id, save_id, trading_day, equity_cents, cash_cents, "
                "market_value_cents, tick, created_at) VALUES (?, ?, 1, 100000000, 99000000, "
                "1000000, 7, ?)",
                (_hex(), ids["save"], NOW),
            )
    finally:
        engine.dispose()
    return ids


def _count(url: str, sql: str, params: tuple = ()) -> int:
    engine = make_engine(url)
    try:
        with engine.connect() as c:
            return int(c.exec_driver_sql(sql, params).scalar_one())
    finally:
        engine.dispose()


def test_upgrade_keeps_legacy_rows_and_children(db_url: str) -> None:
    command.upgrade(_cfg(db_url), PRE_REVISION)
    ids = _insert_legacy(db_url)

    command.upgrade(_cfg(db_url), HEAD_REVISION)

    assert _count(db_url, "SELECT COUNT(*) FROM saves WHERE id = ?", (ids["save"],)) == 1
    assert _count(db_url, "SELECT COUNT(*) FROM save_stats WHERE save_id = ?", (ids["save"],)) == 1
    assert _count(db_url, "SELECT COUNT(*) FROM holdings WHERE save_id = ?", (ids["save"],)) == 1
    assert (
        _count(db_url, "SELECT COUNT(*) FROM equity_snapshots WHERE save_id = ?", (ids["save"],))
        == 1
    )
    assert _count(db_url, "SELECT COUNT(*) FROM saves WHERE user_id IS NULL") == 0


def test_new_constraints_after_upgrade(db_url: str) -> None:
    command.upgrade(_cfg(db_url), HEAD_REVISION)
    ids = _insert_legacy(db_url)
    engine = make_engine(db_url)
    try:
        # master（无主）与玩家挑战存档合法
        with engine.begin() as c:
            master = _hex()
            c.exec_driver_sql(
                "INSERT INTO saves (id, user_id, mode, initial_fund_cents, cash_cents, "
                "buy_fee_rate, sell_fee_rate, t0_mode, trade_unit, market_seed, tick, trade_seq, "
                "trading_day, clock_minute, paused, auto_enabled, auto_paused, "
                "auto_max_total_trades, version, created_at, updated_at, clock_rules, "
                "events_enabled, events_ruleset) VALUES "
                "(?, NULL, 'challenge_market', 0, 0, 0.0003, 0.0013, 0, 100, 1, 0, 0, 1, 570, 1, "
                "0, 0, 100, 1, ?, ?, 2, 1, 1)",
                (master, NOW, NOW),
            )
            c.exec_driver_sql(
                "INSERT INTO saves (id, user_id, mode, initial_fund_cents, cash_cents, "
                "buy_fee_rate, sell_fee_rate, t0_mode, trade_unit, market_seed, tick, trade_seq, "
                "trading_day, clock_minute, paused, auto_enabled, auto_paused, "
                "auto_max_total_trades, version, created_at, updated_at, clock_rules, "
                "events_enabled, events_ruleset, market_source_id) VALUES "
                "(?, ?, 'challenge', 100, 100, 0.0003, 0.0013, 0, 100, 1, 0, 0, 1, 570, 0, "
                "0, 0, 100, 1, ?, ?, 2, 1, 1, ?)",
                (_hex(), ids["user"], NOW, NOW, master),
            )
        # 无主的普通存档被拒绝
        with pytest.raises(IntegrityError), engine.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO saves (id, user_id, mode, initial_fund_cents, cash_cents, "
                "buy_fee_rate, sell_fee_rate, t0_mode, trade_unit, market_seed, tick, trade_seq, "
                "trading_day, clock_minute, paused, auto_enabled, auto_paused, "
                "auto_max_total_trades, version, created_at, updated_at, clock_rules, "
                "events_enabled, events_ruleset) VALUES "
                "(?, NULL, 'normal', 1, 1, 0.0003, 0.0013, 0, 100, 1, 0, 0, 1, 570, 0, 0, 0, 100, "
                "1, ?, ?, 2, 0, 0)",
                (_hex(), NOW, NOW),
            )
        # 普通存档不能引用 master 行情
        with pytest.raises(IntegrityError), engine.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO saves (id, user_id, mode, initial_fund_cents, cash_cents, "
                "buy_fee_rate, sell_fee_rate, t0_mode, trade_unit, market_seed, tick, trade_seq, "
                "trading_day, clock_minute, paused, auto_enabled, auto_paused, "
                "auto_max_total_trades, version, created_at, updated_at, clock_rules, "
                "events_enabled, events_ruleset, market_source_id) VALUES "
                "(?, ?, 'normal', 1, 1, 0.0003, 0.0013, 0, 100, 1, 0, 0, 1, 570, 0, 0, 0, 100, "
                "1, ?, ?, 2, 0, 0, ?)",
                (_hex(), ids["user"], NOW, NOW, _hex()),
            )
        # 外键级联仍然生效（删用户带走存档与子表）
        with engine.begin() as c:
            c.exec_driver_sql("DELETE FROM users WHERE id = ?", (ids["user"],))
        assert _count(db_url, "SELECT COUNT(*) FROM holdings") == 0
    finally:
        engine.dispose()


def test_downgrade_restores_legacy_shape_and_keeps_rows(db_url: str) -> None:
    command.upgrade(_cfg(db_url), PRE_REVISION)
    ids = _insert_legacy(db_url)
    command.upgrade(_cfg(db_url), HEAD_REVISION)
    command.downgrade(_cfg(db_url), PRE_REVISION)

    assert _count(db_url, "SELECT COUNT(*) FROM saves WHERE id = ?", (ids["save"],)) == 1
    assert _count(db_url, "SELECT COUNT(*) FROM holdings WHERE save_id = ?", (ids["save"],)) == 1
    assert _count(db_url, "SELECT COUNT(*) FROM save_stats WHERE save_id = ?", (ids["save"],)) == 1
    engine = make_engine(db_url)
    try:
        with engine.connect() as c:
            cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(saves)")}
            assert "market_source_id" not in cols
            notnull = {r[1]: r[3] for r in c.exec_driver_sql("PRAGMA table_info(saves)")}
            assert notnull["user_id"] == 1
    finally:
        engine.dispose()
