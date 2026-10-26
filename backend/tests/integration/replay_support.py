"""真实复盘集成测试的公共支持：临时库（迁移到 head）、夹具关卡包导入、登录与推进辅助。

夹具关卡包 `tests/fixtures/replay/pack_min.json`（slug=fixture-min，3 只股票）；
回看 15 + 游戏 6 + 揭示 4 日。复制到 `<tmp>/packs/fixture-min/v1.json` 后，
应用启动时导入；全程不联网。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from stocksim.core.config import Settings
from stocksim.main import create_app
from stocksim.models import User

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE_PACK = BACKEND_DIR / "tests" / "fixtures" / "replay" / "pack_min.json"
TEST_SECRET = "test-secret-key-0123456789abcdef"
PASSWORD = "secret1"
SLUG = "fixture-min"
# 夹具关卡的会话内代码（别名）与真实代码
ALIAS = {"s1": "990001", "s2": "990002", "s3": "990003"}
REAL = {"s1": "600001", "s2": "300001", "s3": "000001"}
REAL_NAMES = ("测试甲", "测试乙", "测试丙")


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PACK.read_text(encoding="utf-8"))


def write_pack(directory: Path, raw: dict[str, Any], *, folder: str | None = None) -> Path:
    slug = folder or raw["slug"]
    target = directory / slug / f"v{raw['version']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return target


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url
    command.upgrade(cfg, "head")


def build_app(directory: Path, *, packs: Path | None = None, **overrides: Any) -> FastAPI:
    """建应用：迁移临时库，并把 packs 目录（默认仅夹具关卡）设为 REPLAY_PACKS_DIR。"""
    directory.mkdir(parents=True, exist_ok=True)
    packs_dir = packs or directory / "packs"
    if packs is None:
        write_pack(packs_dir, load_fixture())
    values: dict[str, Any] = {
        "_env_file": None,
        "DATABASE_URL": f"sqlite:///{directory / 'replay.db'}",
        "SECRET_KEY": TEST_SECRET,
        "COOKIE_SECURE": False,
        "REPLAY_PACKS_DIR": str(packs_dir),
    }
    values.update(overrides)
    settings = Settings(**values)  # type: ignore[arg-type]
    migrate(settings.DATABASE_URL)
    return create_app(settings)


def register(client: TestClient, username: str = "alice") -> None:
    resp = client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    # 关闭墙钟补推：复盘不依赖它，普通存档的对照也保持确定
    assert client.patch("/api/v1/me", json={"refresh_rate_ms": 60_000}).status_code == 200


def user_id(app: FastAPI, username: str) -> uuid.UUID:
    with app.state.session_factory() as db:
        return db.scalar(select(User.id).where(User.username == username))


def create_session(client: TestClient, *, masked: bool = True, slug: str = SLUG) -> dict[str, Any]:
    resp = client.post("/api/v1/replay/sessions", json={"level_slug": slug, "masked": masked})
    assert resp.status_code == 201, resp.text
    return resp.json()


def advance(
    client: TestClient,
    sid: str,
    *,
    expected_tick: int,
    to: str = "next_phase",
    skip_pending: bool = False,
) -> Any:
    return client.post(
        f"/api/v1/replay/sessions/{sid}/advance",
        json={"to": to, "expected_tick": expected_tick, "skip_pending": skip_pending},
    )


def answer(client: TestClient, sid: str, qid: str, body: dict[str, Any]) -> Any:
    return client.put(f"/api/v1/replay/sessions/{sid}/questions/{qid}/answer", json=body)


def session_state(client: TestClient, sid: str) -> dict[str, Any]:
    resp = client.get(f"/api/v1/replay/sessions/{sid}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def error_code(resp: Any) -> str:
    return resp.json()["code"]


AppFactory = Callable[..., FastAPI]
