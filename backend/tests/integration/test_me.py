"""当前用户接口：读取、修改偏好、注销账号。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.models import AuthSession, User

ME = "/api/v1/me"
PASSWORD = "secret1"


def test_get_me_requires_login(client: TestClient) -> None:
    resp = client.get(ME)
    assert resp.status_code == 401
    assert resp.json() == {"code": "AUTH_REQUIRED", "params": {}}


def test_get_me_returns_defaults(registered_client: TestClient) -> None:
    body = registered_client.get(ME).json()
    assert body["username"] == "alice"
    assert body["theme"] == "dark"
    assert body["lang"] == "zh-CN"
    assert body["refresh_rate_ms"] == 3000
    assert body["tutorial_completed"] is False


def test_patch_me_updates_only_given_fields(registered_client: TestClient) -> None:
    resp = registered_client.patch(ME, json={"theme": "light"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"] == "light"
    assert body["lang"] == "zh-CN"
    assert body["refresh_rate_ms"] == 3000


def test_patch_me_persists_all_preferences(registered_client: TestClient) -> None:
    payload = {
        "theme": "festival",
        "lang": "en-US",
        "refresh_rate_ms": 1000,
        "tutorial_completed": True,
    }
    assert registered_client.patch(ME, json=payload).status_code == 200
    body = registered_client.get(ME).json()
    assert {k: body[k] for k in payload} == payload


def test_patch_me_rejects_unknown_theme(registered_client: TestClient) -> None:
    resp = registered_client.patch(ME, json={"theme": "neon"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_patch_me_rejects_out_of_range_refresh_rate(registered_client: TestClient) -> None:
    resp = registered_client.patch(ME, json={"refresh_rate_ms": 10})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_delete_me_requires_login(client: TestClient) -> None:
    assert client.delete(ME).status_code == 401


def test_delete_me_removes_account_and_sessions(
    app: FastAPI, registered_client: TestClient
) -> None:
    resp = registered_client.delete(ME)
    assert resp.status_code == 204
    # 响应应清除会话 cookie
    assert "session=" in resp.headers["set-cookie"]
    assert registered_client.get(ME).status_code == 401

    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0

    registered_client.cookies.clear()
    login = registered_client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert login.status_code == 401
