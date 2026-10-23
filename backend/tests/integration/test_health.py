"""健康检查：存活与就绪探针。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine


def test_healthz_is_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_checks_database(client: TestClient) -> None:
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "ok"}


def test_readyz_returns_503_when_database_unreachable(app: FastAPI, client: TestClient) -> None:
    # 指向不存在目录下的 sqlite 文件，连接必然失败；用 create_engine 而非 make_engine，避免创建目录
    app.state.engine = create_engine("sqlite:////nonexistent-stocksim-dir/unreachable.db")
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable", "database": "error"}
