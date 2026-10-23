"""资产曲线（权益快照）与当日盈亏。"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.models import Candle, EquitySnapshot, Save
from stocksim.services.market import advance_ticks

SAVES = "/api/v1/saves"
CODE = "600036"
INITIAL = 100_000_000


def _setup(client: TestClient, app: FastAPI) -> str:
    client.patch("/api/v1/me", json={"refresh_rate_ms": 60_000})
    sid = client.post(SAVES, json={}).json()["id"]
    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        save.clock_minute = 600
        db.commit()
    return sid


def _advance(app: FastAPI, sid: str, n: int) -> None:
    with app.state.session_factory() as db:
        advance_ticks(db, db.get(Save, uuid.UUID(sid)), n)


def _day(app: FastAPI, sid: str) -> int:
    with app.state.session_factory() as db:
        return db.get(Save, uuid.UUID(sid)).trading_day


def _curve(client: TestClient, sid: str, rng: str | None = None) -> dict:
    url = f"{SAVES}/{sid}/equity-curve" + (f"?range={rng}" if rng else "")
    resp = client.get(url)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _close(app: FastAPI, sid: str, day: int) -> int:
    with app.state.session_factory() as db:
        return db.scalar(
            select(func.sum(Candle.close_cents)).where(
                Candle.save_id == uuid.UUID(sid),
                Candle.stock_code == CODE,
                Candle.trading_day == day,
            )
        )


def test_fresh_save_has_initial_and_live_points(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    items = _curve(registered_client, sid)["items"]
    assert [p["kind"] for p in items] == ["initial", "live"]
    assert items[0]["trading_day"] == -1 and items[0]["equity_cents"] == INITIAL
    assert items[1]["equity_cents"] == INITIAL
    pf = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    assert pf["day_pnl_cents"] == 0 and pf["day_pnl_bp"] == 0
    assert pf["prev_equity_cents"] == INITIAL


def test_snapshot_written_on_rollover_with_close_prices(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    qty = registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": 100}
    ).json()
    cash = qty["cash_cents"]
    _advance(app, sid, 20)
    _advance(app, sid, 20)
    items = _curve(registered_client, sid)["items"]
    closes = [p for p in items if p["kind"] == "close"]
    assert [p["trading_day"] for p in closes] == [0, 1]
    for p in closes:
        mv = 100 * _close(app, sid, p["trading_day"])
        assert p["market_value_cents"] == mv
        assert p["cash_cents"] == cash
        assert p["equity_cents"] == cash + mv
    assert items[-1]["kind"] == "live" and items[-1]["trading_day"] == 2


def test_snapshot_idempotent_and_range_filter(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    _advance(app, sid, 400)
    day = _day(app, sid)
    assert day >= 8
    assert len(_curve(registered_client, sid, "7d")["items"]) == 7
    assert len(_curve(registered_client, sid, "30d")["items"]) == day + 2  # 初始+day 收盘+实时
    assert len(_curve(registered_client, sid, "all")["items"]) == day + 2
    assert _curve(registered_client, sid, "7d")["items"][-1]["kind"] == "live"

    # 重复写入同一交易日覆盖而不是新增
    from stocksim.services.equity import upsert_snapshot

    with app.state.session_factory() as db:
        save = db.get(Save, uuid.UUID(sid))
        before = db.scalar(select(func.count()).select_from(EquitySnapshot))
        upsert_snapshot(db, save, 3, 111, 222, 1)
        upsert_snapshot(db, save, 3, 333, 444, 2)
        db.commit()
        assert db.scalar(select(func.count()).select_from(EquitySnapshot)) == before
        row = db.scalar(select(EquitySnapshot).where(EquitySnapshot.trading_day == 3))
        assert row.equity_cents == 777 and row.tick == 2

    assert registered_client.get(f"{SAVES}/{sid}/equity-curve?range=1y").status_code == 422


def test_batch_skip_across_days_writes_each_day(
    registered_client: TestClient, app: FastAPI
) -> None:
    sid = _setup(registered_client, app)
    _advance(app, sid, 20 * 5)  # 单次批量推进跨多个交易日
    day = _day(app, sid)
    assert day >= 3
    items = _curve(registered_client, sid)["items"]
    assert [p["trading_day"] for p in items if p["kind"] == "close"] == list(range(day))


def test_equity_curve_scoped_to_owner(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    registered_client.post("/api/v1/auth/logout")
    assert registered_client.get(f"{SAVES}/{sid}/equity-curve").status_code == 401
    registered_client.post("/api/v1/auth/register", json={"username": "bob", "password": "secret1"})
    assert registered_client.get(f"{SAVES}/{sid}/equity-curve").status_code == 404


def test_day_pnl_uses_prev_close_equity(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    # 持仓过夜：次日按 昨日收盘权益 计算当日盈亏
    registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": 100}
    )
    _advance(app, sid, 20)
    _advance(app, sid, 3)
    pf = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    prev_snap = [p for p in _curve(registered_client, sid)["items"] if p["kind"] == "close"][-1]
    assert pf["prev_equity_cents"] == prev_snap["equity_cents"]
    assert pf["day_pnl_cents"] == pf["equity_cents"] - prev_snap["equity_cents"]
    # 当日卖出：卖出手续费计入当日盈亏，权益差仍自洽
    registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "sell", "quantity": 100}
    )
    pf2 = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    assert pf2["holdings"] == []
    assert pf2["prev_equity_cents"] == prev_snap["equity_cents"]
    assert pf2["day_pnl_cents"] == pf2["equity_cents"] - prev_snap["equity_cents"]
    bp = pf2["day_pnl_cents"] * 10000 / pf2["prev_equity_cents"]
    assert abs(pf2["day_pnl_bp"] - bp) <= 0.5 + 1e-9


def test_day_pnl_same_day_buy_only_loses_fee(registered_client: TestClient, app: FastAPI) -> None:
    sid = _setup(registered_client, app)
    buy = registered_client.post(
        f"{SAVES}/{sid}/orders", json={"code": CODE, "side": "buy", "quantity": 100}
    ).json()["trade"]
    pf = registered_client.get(f"{SAVES}/{sid}/portfolio").json()
    prev = pf["prev_equity_cents"]
    # 昨日权益 = 初始资金（无持仓），当日盈亏 = 现价市值 - 成交额 - 手续费
    assert prev == INITIAL
    assert pf["day_pnl_cents"] == pf["equity_cents"] - INITIAL
    assert pf["day_pnl_cents"] == (
        pf["market_value_cents"] - buy["gross_cents"] - buy["fee_cents"]
    )
