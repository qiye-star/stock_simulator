"""集成测试夹具：每个用例一个临时 sqlite 库（先用 Alembic 迁移到 head），再挂 TestClient。"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stocksim.core.config import Settings
from stocksim.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_SECRET = "test-secret-key-0123456789abcdef"
PASSWORD = "secret1"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # 不读取开发者本地的 .env
        DATABASE_URL=f"sqlite:///{tmp_path / 'test.db'}",
        SECRET_KEY=TEST_SECRET,
        COOKIE_SECURE=False,
        PM_BACKGROUND_ENABLED=False,  # 预测市场后台 Hub 关闭，用例直接调用生命周期
    )


@pytest.fixture
def migrated(settings: Settings) -> str:
    """用真实迁移脚本建表，保证测试覆盖的 schema 与线上一致。"""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy.url"] = settings.DATABASE_URL
    command.upgrade(cfg, "head")
    return settings.DATABASE_URL


@pytest.fixture
def app(settings: Settings, migrated: str) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def registered_client(client: TestClient) -> TestClient:
    """已注册并登录 alice 的客户端（Cookie 保存在该 client 中）。"""
    resp = client.post("/api/v1/auth/register", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return client
