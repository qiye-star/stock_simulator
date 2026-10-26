"""每日挑战的隔离与保密（C3、C4）：行情读取点静态检查、GET /saves 不列挑战与 master、守卫、导出。"""

import ast
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from stocksim.core.errors import AppError, ErrorCode
from stocksim.models import Save
from stocksim.services import auto_trade as auto_service
from stocksim.services import debug as debug_service
from stocksim.services import intel as intel_service
from stocksim.services import saves as saves_service
from stocksim.services.challenges import entries, generate

SRC = Path(__file__).resolve().parents[2] / "src" / "stocksim"
DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)
PASSWORD = "secret1"
FORBIDDEN = [
    re.compile(r"db\.get\(\s*MarketState\s*,\s*save\.id\s*\)"),
    re.compile(r"Candle\.save_id\s*==\s*save\.id\b"),
]
# market.py 中允许直接按 save.id 读行情的函数（03 §7.2）；debug.py 整体允许（调试入口，挑战已拒绝）
MARKET_WHITELIST = {
    "market_key",
    "_market_row",
    "_run_ticks",
    "_prior_windows",
    "_persist_closed_day",
    "init_market_for_save",
}
ALLOWED_FILES = {"debug.py"}


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(SRC))
    except ValueError:
        return path.name


def _violations_in(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    if path.name in ALLOWED_FILES:
        return []
    if path.name != "market.py":
        return [f"{_label(path)}: {p.pattern}" for p in FORBIDDEN if p.search(source)]
    tree = ast.parse(source)
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name not in MARKET_WHITELIST:
            segment = ast.get_source_segment(source, node) or ""
            for pattern in FORBIDDEN:
                if pattern.search(segment):
                    found.append(f"market.py::{node.name}: {pattern.pattern}")
    return found


def test_no_direct_market_reads() -> None:
    """服务层与 API 层不得绕过 market_key 直接读 market_states / candles（03 §7.2 静态检查）。"""
    files = [
        p
        for sub in ("services", "api")
        for p in (SRC / sub).rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    violations = [v for p in files for v in _violations_in(p)]
    assert violations == []


def test_static_check_detects_a_direct_read(tmp_path: Path) -> None:
    """自检：静态扫描确实能发现违规写法（防止检查形同虚设）。"""
    bad = tmp_path / "bad.py"
    bad.write_text("def f(db, save):\n    return db.get(MarketState, save.id)\n", encoding="utf-8")
    assert _violations_in(bad) == [f"bad.py: {FORBIDDEN[0].pattern}"]
    market_like = tmp_path / "market.py"
    market_like.write_text(
        "def stock_market(db, save):\n    return db.scalars(Candle.save_id == save.id)\n",
        encoding="utf-8",
    )
    assert _violations_in(market_like) == [f"market.py::stock_market: {FORBIDDEN[1].pattern}"]


def test_get_saves_and_export_hide_challenge_saves(challenge_app, db, fake_clock, make_user):
    user = make_user("alice")
    normal = saves_service.create_save(
        db,
        user,
        name="普通",
        initial_fund_cents=100_000_000,
        buy_fee_rate=Decimal("0.0003"),
        sell_fee_rate=Decimal("0.0013"),
        t0_mode=False,
        trade_unit=100,
    )
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    master_id = ch.master_save_id

    with TestClient(challenge_app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        assert login.status_code == 200, login.text
        listed = client.get("/api/v1/saves")
        assert listed.status_code == 200
        assert [s["id"] for s in listed.json()] == [str(normal.id)]

        delete = client.delete(f"/api/v1/saves/{entry.save_id}")
        assert delete.status_code == 409
        assert delete.json() == {"code": "CHALLENGE_UNSUPPORTED", "params": {"feature": "delete"}}

        export = client.get(f"/api/v1/saves/{entry.save_id}/export")
        assert export.status_code == 200
        body = export.json()["save"]
        assert body["market_seed"] is None
        assert body["mode"] == "challenge"
        assert export.json()["challenge"] == {
            "challenge_id": str(ch.id),
            "challenge_date": DAY.isoformat(),
        }

        assert client.get(f"/api/v1/saves/{master_id}").status_code == 404
        assert client.get(f"/api/v1/saves/{master_id}/market").status_code == 404


def test_master_is_not_reachable_by_any_user(challenge_app, db, fake_clock, make_user):
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    master = db.get(Save, ch.master_save_id)
    with pytest.raises(AppError) as exc:
        saves_service.open_save(db, user, master.id)
    assert exc.value.code == ErrorCode.SAVE_NOT_FOUND


def test_challenge_saves_reject_debug_auto_trade_and_intel(
    challenge_app, db, fake_clock, make_user
):
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    save = db.get(Save, entry.save_id)

    with pytest.raises(AppError) as exc:
        debug_service.set_cash(db, save, 1)
    assert exc.value.code == ErrorCode.CHALLENGE_UNSUPPORTED and exc.value.params == {
        "feature": "debug"
    }
    with pytest.raises(AppError) as exc:
        debug_service.reset_market(db, save)
    assert exc.value.params == {"feature": "debug"}
    with pytest.raises(AppError) as exc:
        auto_service.run_action(db, save, "start")
    assert exc.value.params == {"feature": "auto_trade"}
    with pytest.raises(AppError) as exc:
        intel_service.buy_edge_reveal(db, save, edge_id="x", level=1)
    assert exc.value.code == ErrorCode.INTEL_UNAVAILABLE


def test_challenge_saves_do_not_count_toward_the_save_limit(
    challenge_app, db, fake_clock, make_user
):
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entries.join(db, ch, user, fake_clock.value)
    rows = db.scalars(select(Save).where(Save.user_id == user.id)).all()
    assert [r.mode for r in rows] == ["challenge"]
    assert saves_service.list_saves(db, user) == []


def test_static_scan_covers_day_summary_and_api() -> None:
    """静态检查的扫描范围须含收盘小结（services/day_summary.py）与全部 api/ 文件（03 §5 #4）。"""
    files = {p.relative_to(SRC).as_posix() for p in (SRC / "services").rglob("*.py")}
    api = {p.relative_to(SRC).as_posix() for p in (SRC / "api").rglob("*.py")}
    assert "services/day_summary.py" in files
    assert "api/ws.py" in api and "api/routers/market.py" in api


def test_other_users_challenge_entry_is_404_over_http_and_ws(
    challenge_app, db, fake_clock, make_user
) -> None:
    alice = make_user("alice")
    make_user("bob")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entry, _ = entries.join(db, ch, alice, fake_clock.value)
    sid = str(entry.save_id)
    with TestClient(challenge_app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD})
        assert login.status_code == 200, login.text
        for path in (
            f"/api/v1/saves/{sid}",
            f"/api/v1/saves/{sid}/market",
            f"/api/v1/saves/{sid}/portfolio",
            f"/api/v1/saves/{sid}/trades",
            f"/api/v1/saves/{sid}/export",
        ):
            resp = client.get(path)
            assert resp.status_code == 404, path
            assert resp.json()["code"] == "SAVE_NOT_FOUND", path
        with client.websocket_connect(f"/api/v1/ws/saves/{sid}") as ws:
            assert ws.receive_json() == {"t": "error", "code": "SAVE_NOT_FOUND"}


def test_challenge_entry_rejects_clock_debug_and_auto_trade_over_http(
    challenge_app, db, fake_clock, make_user
) -> None:
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    sid = str(entry.save_id)
    with TestClient(challenge_app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        assert login.status_code == 200, login.text
        cases = [
            (f"/api/v1/saves/{sid}/clock/pause", None, {"feature": "clock"}),
            (f"/api/v1/saves/{sid}/clock/skip", None, {"feature": "clock"}),
            (f"/api/v1/saves/{sid}/debug/fund", {"cash_cents": 1}, {"feature": "debug"}),
            (f"/api/v1/saves/{sid}/auto-trade/start", None, {"feature": "auto_trade"}),
        ]
        for path, body, params in cases:
            resp = client.post(path, json=body) if body is not None else client.post(path)
            assert resp.status_code == 409, path
            assert resp.json() == {"code": "CHALLENGE_UNSUPPORTED", "params": params}, path


def test_intel_is_disabled_for_challenge_entries_over_http(
    challenge_app, db, fake_clock, make_user
) -> None:
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    sid = str(entry.save_id)
    with TestClient(challenge_app) as client:
        client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        resp = client.post(
            f"/api/v1/saves/{sid}/intel/rumor-hints", json={"event_id": "e1-1"}
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["code"] == "INTEL_UNAVAILABLE"
        assert body["params"]["reason"] == "disabled"


def test_ten_normal_saves_fit_beside_a_challenge_entry(
    challenge_app, db, fake_clock, make_user
) -> None:
    """挑战存档不占 MAX_SAVES_PER_USER：普通存档可建满 10 个，第 11 个才被拒。"""
    from stocksim.services.saves import MAX_SAVES_PER_USER

    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entries.join(db, ch, user, fake_clock.value)
    for i in range(MAX_SAVES_PER_USER):
        saves_service.create_save(
            db,
            user,
            name=f"普通{i}",
            initial_fund_cents=100_000_000,
            buy_fee_rate=Decimal("0.0003"),
            sell_fee_rate=Decimal("0.0013"),
            t0_mode=False,
            trade_unit=100,
        )
    with pytest.raises(AppError) as exc:
        saves_service.create_save(
            db,
            user,
            name="第11个",
            initial_fund_cents=100_000_000,
            buy_fee_rate=Decimal("0.0003"),
            sell_fee_rate=Decimal("0.0013"),
            t0_mode=False,
            trade_unit=100,
        )
    assert exc.value.code == ErrorCode.SAVE_LIMIT_REACHED
    assert len(saves_service.list_saves(db, user)) == MAX_SAVES_PER_USER


def test_master_id_is_not_reachable_over_ws(challenge_app, db, fake_clock, make_user) -> None:
    """master（无主人）经 WS 与 HTTP 对任何用户都是 SAVE_NOT_FOUND / 4404（03 §5 #3）。"""
    user = make_user("alice")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = ch.starts_at.replace(tzinfo=UTC)
    entries.join(db, ch, user, fake_clock.value)
    master_id = str(ch.master_save_id)
    with TestClient(challenge_app) as client:
        client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        assert client.get(f"/api/v1/saves/{master_id}/market").status_code == 404
        with client.websocket_connect(f"/api/v1/ws/saves/{master_id}") as ws:
            assert ws.receive_json() == {"t": "error", "code": "SAVE_NOT_FOUND"}
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4404
