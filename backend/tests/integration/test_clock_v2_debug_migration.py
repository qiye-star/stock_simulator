"""时钟 v2：调试接口（只前进、重置回开盘）与迁移（存量存档为 v1，用户节奏默认 normal）。"""

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.db.session import make_engine
from stocksim.main import create_app
from stocksim.models import MarketState, Save
from stocksim.services.seed import seed_stock_table

PASSWORD = "secret1"
BACKEND_DIR = Path(__file__).resolve().parents[2]
PRE_CLOCK_REVISION = "f1c260b097ed"


@pytest.fixture
def debug_v2(settings, migrated: str) -> tuple[TestClient, FastAPI, str]:
    app = create_app(settings.model_copy(update={"ENABLE_DEBUG_API": True}))
    with app.state.session_factory() as db:
        seed_stock_table(db)
    client = TestClient(app)
    client.__enter__()
    try:
        assert (
            client.post(
                "/api/v1/auth/register", json={"username": "carol", "password": PASSWORD}
            ).status_code
            == 201
        )
        resp = client.post("/api/v1/saves", json={"clock_rules": 2})
        assert resp.status_code == 201, resp.text
        yield client, app, resp.json()["id"]
    finally:
        client.__exit__(None, None, None)


def _time(client: TestClient, sid: str, minute: int) -> dict:
    resp = client.post(f"/api/v1/saves/{sid}/debug/time", json={"minute_of_day": minute})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_debug_time_only_moves_forward_and_keeps_alignment(debug_v2) -> None:
    client, app, sid = debug_v2
    out = _time(client, sid, 600)  # 9:30 -> 10:00：30 个分钟
    assert out["changed"] == 30 and out["clock_minute"] == 600
    market = client.get(f"/api/v1/saves/{sid}/market/600036/intraday").json()
    assert market["exact"] is True and len(market["points"]) == 30

    back = _time(client, sid, 580)  # 向后：沿午夜前进到次日 9:40（不回退）
    assert back["changed"] == (580 - 600) % 1440 and back["clock_minute"] == 580
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        assert save.trading_day == 1
    assert client.get(f"/api/v1/saves/{sid}/market/600036/intraday").json()["exact"] is True


def test_debug_reset_market_returns_v2_clock_to_open(debug_v2) -> None:
    client, app, sid = debug_v2
    _time(client, sid, 840)
    resp = client.post(f"/api/v1/saves/{sid}/debug/reset-market")
    assert resp.status_code == 200, resp.text
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        assert save.clock_minute == 570 and save.tick == 0 and save.trading_day == 0
        assert save.last_tick_at is not None
        payload = db.get(MarketState, uuid.UUID(sid)).payload
        assert payload["_meta"]["rules"] == 2 and payload["_meta"]["trading_tick"] == 0


def test_pre_clock_saves_migrate_to_v1_and_users_get_normal_speed(settings) -> None:
    """迁移前存在的存档：clock_rules 取 server_default 1（v1）；用户 clock_speed 为 normal。

    同时守住一个回归：迁移引擎开启 foreign_keys，SQLite 上不得因重建 users/saves
    而级联删除子表数据。
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy.url"] = settings.DATABASE_URL
    command.upgrade(cfg, PRE_CLOCK_REVISION)

    engine = make_engine(settings.DATABASE_URL)  # 与迁移环境一致（foreign_keys=ON）
    meta = sa.MetaData()
    users = sa.Table("users", meta, autoload_with=engine)
    saves = sa.Table("saves", meta, autoload_with=engine)
    stats = sa.Table("save_stats", meta, autoload_with=engine)
    user_id = uuid.uuid4().hex
    save_id = uuid.uuid4().hex
    now = datetime(2026, 10, 20, 8, 0, 0)
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=user_id, username="legacy", password_hash="x", theme="dark",
                lang="zh-CN", refresh_rate_ms=3000, tutorial_completed=False,
                created_at=now, updated_at=now,
            )
        )  # fmt: skip
        conn.execute(
            saves.insert().values(
                id=save_id, user_id=user_id, name="old", mode="normal",
                initial_fund_cents=100_000_000, cash_cents=100_000_000,
                buy_fee_rate=Decimal("0.0003"), sell_fee_rate=Decimal("0.0013"),
                t0_mode=False, trade_unit=1, market_seed=12345, tick=0, trade_seq=0,
                trading_day=0, clock_minute=570, paused=False, auto_enabled=False,
                auto_paused=False, auto_max_total_trades=100, version=1,
                created_at=now, updated_at=now,
            )
        )  # fmt: skip
        conn.execute(stats.insert().values(save_id=save_id, trade_count=7, updated_at=now))

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        rules = conn.execute(
            sa.text("SELECT clock_rules FROM saves WHERE id = :i"), {"i": save_id}
        ).scalar()
        speed = conn.execute(
            sa.text("SELECT clock_speed FROM users WHERE id = :i"), {"i": user_id}
        ).scalar()
        kept = conn.execute(
            sa.text("SELECT trade_count FROM save_stats WHERE save_id = :i"), {"i": save_id}
        ).scalar()
    engine.dispose()
    assert rules == 1
    assert speed == "normal"
    assert kept == 7  # 子表数据未被级联删除
