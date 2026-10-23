"""错误契约：所有错误体均为 {"code", "params"}。"""

from fastapi.testclient import TestClient


def test_validation_error_uses_contract_envelope(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/register", json={"username": "alice"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["params"]["errors"], list)
    assert any("password" in err["loc"] for err in body["params"]["errors"])


def test_malformed_json_uses_contract_envelope(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_unknown_route_uses_contract_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "HTTP_404"
