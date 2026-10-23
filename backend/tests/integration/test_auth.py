"""认证接口：注册、登录、登出、改密，以及会话的存储方式。"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from stocksim.core.config import Settings
from stocksim.models import AuthSession, User

API = "/api/v1/auth"
PASSWORD = "secret1"


def _register(client: TestClient, username: str = "alice", password: str = PASSWORD):
    return client.post(f"{API}/register", json={"username": username, "password": password})


def test_register_creates_user_and_logs_in(client: TestClient) -> None:
    resp = _register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert body["theme"] == "dark"
    assert "password_hash" not in body and "password" not in body
    cookie = resp.headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/v1/me").status_code == 200


@pytest.mark.parametrize("username", ["a", "constructor", "__proto__", "bad name", "x" * 21, "a@b"])
def test_register_rejects_invalid_username(client: TestClient, username: str) -> None:
    resp = _register(client, username=username)
    assert resp.status_code == 422
    assert resp.json()["code"] == "AUTH_USERNAME_INVALID"


def test_register_accepts_chinese_username(client: TestClient) -> None:
    assert _register(client, username="张三_01").status_code == 201


@pytest.mark.parametrize("password", ["12345", "x" * 21])
def test_register_rejects_weak_password(client: TestClient, password: str) -> None:
    resp = _register(client, password=password)
    assert resp.status_code == 422
    assert resp.json()["code"] == "AUTH_PASSWORD_WEAK"


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    assert _register(client).status_code == 201
    resp = _register(client)
    assert resp.status_code == 409
    assert resp.json() == {"code": "AUTH_USERNAME_TAKEN", "params": {"username": "alice"}}


def test_password_is_stored_as_argon2id_hash(app: FastAPI, client: TestClient) -> None:
    _register(client)
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash


def test_login_success_sets_session_cookie(client: TestClient) -> None:
    _register(client)
    client.cookies.clear()
    resp = client.post(f"{API}/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert "session" in client.cookies


@pytest.mark.parametrize(
    ("username", "password"),
    [("alice", "wrong-password"), ("nobody", PASSWORD)],
)
def test_login_failure_is_indistinguishable(
    client: TestClient, username: str, password: str
) -> None:
    _register(client)
    client.cookies.clear()
    resp = client.post(f"{API}/login", json={"username": username, "password": password})
    assert resp.status_code == 401
    assert resp.json() == {"code": "AUTH_INVALID_CREDENTIALS", "params": {}}


def test_session_token_is_stored_hashed(
    app: FastAPI, client: TestClient, settings: Settings
) -> None:
    _register(client)
    token = client.cookies.get("session")
    assert token
    expected = hmac.new(settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()
    with app.state.session_factory() as db:
        hashes = [row.token_hash for row in db.scalars(select(AuthSession))]
    assert expected in hashes
    assert token not in hashes


def test_logout_revokes_session(client: TestClient) -> None:
    _register(client)
    token = client.cookies.get("session")
    resp = client.post(f"{API}/logout")
    assert resp.status_code == 204
    assert client.get("/api/v1/me").status_code == 401

    # 即使把旧 cookie 重新塞回去，服务端也应拒绝
    client.cookies.set("session", token)
    assert client.get("/api/v1/me").json()["code"] == "AUTH_REQUIRED"


def test_logout_without_session_is_idempotent(client: TestClient) -> None:
    assert client.post(f"{API}/logout").status_code == 204


def test_expired_session_is_rejected(app: FastAPI, client: TestClient) -> None:
    _register(client)
    with app.state.session_factory() as db:
        db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


def test_change_password_requires_correct_current(client: TestClient) -> None:
    _register(client)
    resp = client.put(
        f"{API}/password", json={"current_password": "nope-nope", "new_password": "newpass1"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_change_password_rejects_same_or_weak(client: TestClient) -> None:
    _register(client)
    same = client.put(
        f"{API}/password", json={"current_password": PASSWORD, "new_password": PASSWORD}
    )
    assert same.status_code == 422 and same.json()["code"] == "AUTH_PASSWORD_WEAK"
    weak = client.put(f"{API}/password", json={"current_password": PASSWORD, "new_password": "123"})
    assert weak.status_code == 422 and weak.json()["code"] == "AUTH_PASSWORD_WEAK"


def test_change_password_swaps_credentials_and_revokes_other_sessions(client: TestClient) -> None:
    _register(client)
    other = TestClient(client.app)
    with other:
        other.post(f"{API}/login", json={"username": "alice", "password": PASSWORD})
        assert other.get("/api/v1/me").status_code == 200

        resp = client.put(
            f"{API}/password", json={"current_password": PASSWORD, "new_password": "newpass1"}
        )
        assert resp.status_code == 204

        # 当前会话保留，其他会话被吊销
        assert client.get("/api/v1/me").status_code == 200
        assert other.get("/api/v1/me").status_code == 401

    client.cookies.clear()
    assert (
        client.post(f"{API}/login", json={"username": "alice", "password": PASSWORD}).status_code
        == 401
    )
    assert (
        client.post(f"{API}/login", json={"username": "alice", "password": "newpass1"}).status_code
        == 200
    )
