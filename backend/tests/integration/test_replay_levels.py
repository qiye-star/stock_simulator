"""真实复盘：关卡导入（幂等、版本不可变）、包校验、列表与详情防剧透（05 §3.3、§8.2 第 1–2 点）。"""

import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

# importlib 导入模式下同目录模块不可见：显式加入本目录（replay_support 为复盘测试共用）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_support import (
    REAL,
    REAL_NAMES,
    SLUG,
    build_app,
    load_fixture,
    register,
    write_pack,
)

from stocksim.db.session import make_engine, make_session_factory
from stocksim.models import ReplayLevel, ReplayLevelVersion
from stocksim.services.replay import levels
from stocksim.services.replay.pack import pack_sha256, parse_pack

API = "/api/v1/replay"


@pytest.fixture
def app(tmp_path: Path) -> Iterator[FastAPI]:
    """进入 lifespan（启动导入夹具关卡包）后再交给用例。"""
    application = build_app(tmp_path / "app")
    with TestClient(application):
        yield application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        register(test_client)
        yield test_client


def test_startup_imports_bundled_fixture(app: FastAPI) -> None:
    with app.state.session_factory() as db:
        level = db.query(ReplayLevel).filter_by(slug=SLUG).one()
        assert level.status == "published"
        assert level.masked_allowed is True
        assert level.stock_count == 3
        assert db.query(ReplayLevelVersion).count() == 1


def test_reimport_same_content_is_idempotent(app: FastAPI) -> None:
    raw = load_fixture()
    with app.state.session_factory() as db:
        result = levels.import_pack(db, raw)
        db.commit()
        assert result.status == "skipped"
        assert db.query(ReplayLevelVersion).count() == 1


def test_same_version_different_content_is_rejected(app: FastAPI) -> None:
    raw = copy.deepcopy(load_fixture())
    raw["commentary"] = "改了内容但版本号没变"
    with app.state.session_factory() as db, pytest.raises(levels.PackConflict):
        levels.import_pack(db, raw)
        db.commit()


def test_new_version_becomes_current(app: FastAPI) -> None:
    raw = copy.deepcopy(load_fixture())
    raw["version"] = 2
    raw["commentary"] = "第二版讲解"
    with app.state.session_factory() as db:
        result = levels.import_pack(db, raw)
        db.commit()
        assert (result.status, result.version) == ("imported", 2)
        level = db.query(ReplayLevel).filter_by(slug=SLUG).one()
        current = db.get(ReplayLevelVersion, level.current_version_id)
        assert current.version == 2


def test_pack_rejects_unknown_fields_and_inconsistent_calendar() -> None:
    raw = load_fixture()
    with pytest.raises(ValidationError):
        parse_pack({**raw, "unexpected": 1})
    broken = copy.deepcopy(raw)
    broken["calendar"] = broken["calendar"][:-1]
    with pytest.raises(ValueError, match="calendar"):
        parse_pack(broken)


def test_pack_sha256_is_key_order_independent() -> None:
    raw = load_fixture()
    shuffled = json.loads(json.dumps(raw, sort_keys=False))
    assert pack_sha256(raw) == pack_sha256(shuffled)


def test_list_levels_is_masked(client: TestClient) -> None:
    resp = client.get(f"{API}/levels")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == [SLUG]
    item = body["items"][0]
    assert item["title"] == "某个周末的监管政策"  # title_masked，不是真实标题
    assert item["title_real"] is None
    assert item["my_best"] is None
    text = resp.text
    for leaked in (*REAL.values(), *REAL_NAMES, "answer", "real_code", "real_name"):
        assert leaked not in text, leaked


def test_list_filters(client: TestClient) -> None:
    assert len(client.get(f"{API}/levels", params={"tag": "券商"}).json()["items"]) == 1
    assert client.get(f"{API}/levels", params={"tag": "无此标签"}).json()["items"] == []
    assert client.get(f"{API}/levels", params={"difficulty": 2}).json()["items"]
    assert client.get(f"{API}/levels", params={"difficulty": 1}).json()["items"] == []


def test_detail_and_not_found(client: TestClient) -> None:
    resp = client.get(f"{API}/levels/{SLUG}")
    assert resp.status_code == 200
    assert resp.json()["play_days"] == 6
    missing = client.get(f"{API}/levels/no-such-level")
    assert missing.status_code == 404
    assert missing.json()["code"] == "REPLAY_LEVEL_NOT_FOUND"


def test_retired_level_is_hidden_and_cannot_start(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as db:
        db.query(ReplayLevel).filter_by(slug=SLUG).one().status = "retired"
        db.commit()
    assert client.get(f"{API}/levels/{SLUG}").status_code == 404
    assert client.get(f"{API}/levels").json()["items"] == []
    resp = client.post(f"{API}/sessions", json={"level_slug": SLUG, "masked": True})
    assert resp.status_code == 404
    assert resp.json()["code"] == "REPLAY_LEVEL_NOT_FOUND"


def test_real_only_level_serves_real_title(tmp_path: Path) -> None:
    raw = load_fixture()
    real_only = copy.deepcopy(raw)
    real_only["slug"] = "real-only"
    real_only["masked_allowed"] = False
    packs = tmp_path / "packs"
    write_pack(packs, raw)
    write_pack(packs, real_only)
    app = build_app(tmp_path / "app", packs=packs)
    with TestClient(app) as client:
        register(client)
        item = client.get(f"{API}/levels/real-only").json()
        assert item["title"] == raw["title"]
        assert item["title_real"] == raw["title"]
        assert (
            client.post(f"{API}/sessions", json={"level_slug": "real-only", "masked": True}).json()[
                "code"
            ]
            == "VALIDATION_ERROR"
        )


def test_bad_pack_file_is_skipped_at_startup(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    write_pack(packs, load_fixture())
    bad = packs / "broken" / "v1.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json", encoding="utf-8")
    app = build_app(tmp_path / "app", packs=packs)
    with TestClient(app), app.state.session_factory() as db:
        assert db.query(ReplayLevel).filter_by(slug=SLUG).count() == 1
        assert db.query(ReplayLevel).filter_by(slug="broken").count() == 0


def test_cli_style_import_uses_same_idempotency(app: FastAPI, tmp_path: Path) -> None:
    """手动导入（CLI）与启动导入共用 import_pack：独立引擎导入同一内容 → skipped。"""
    engine = make_engine(f"sqlite:///{tmp_path / 'app' / 'replay.db'}")
    try:
        factory = make_session_factory(engine)
        with factory() as db:
            assert levels.import_pack(db, load_fixture()).status == "skipped"
            db.commit()
    finally:
        engine.dispose()
