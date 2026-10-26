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


def test_prediction_error_codes_are_registered_with_status() -> None:
    """预测卡 / 积分 / 情报 / 称号的 6 个新码（02 §1.4）：存在于枚举，并给出契约中的 HTTP 状态。"""
    from stocksim.core.errors import ERROR_STATUS, ErrorCode

    expected = {
        "PREDICTION_NOT_FOUND": 404,
        "PREDICTION_CLOSED": 409,
        "POINTS_INSUFFICIENT": 422,
        "INTEL_LIMIT_REACHED": 409,
        "INTEL_UNAVAILABLE": 409,
        "TITLE_NOT_UNLOCKED": 409,
    }
    for code, status in expected.items():
        assert ErrorCode(code).value == code
        assert ERROR_STATUS[ErrorCode(code)] == status


def test_challenge_error_codes_are_registered_with_status() -> None:
    """每日挑战的 10 个新码（03 §10.3）：存在于枚举，并给出契约中的 HTTP 状态。"""
    from stocksim.core.errors import ERROR_STATUS, ErrorCode

    expected = {
        "CHALLENGE_NOT_FOUND": 404,
        "CHALLENGE_NOT_STARTED": 409,
        "CHALLENGE_ENTRY_CLOSED": 409,
        "CHALLENGE_ENDED": 409,
        "CHALLENGE_NOT_ENTERED": 409,
        "CHALLENGE_ROUND_NOT_FOUND": 404,
        "CHALLENGE_ROUND_CLOSED": 409,
        "CHALLENGE_ANSWER_LIMIT": 409,
        "CHALLENGE_NOT_SETTLED": 409,
        "CHALLENGE_UNSUPPORTED": 409,
    }
    for code, status in expected.items():
        assert ErrorCode(code).value == code
        assert ERROR_STATUS[ErrorCode(code)] == status


def test_every_challenge_error_code_is_registered() -> None:
    """所有 CHALLENGE_* 码（03 §10.3）都必须在 ERROR_STATUS 登记 HTTP 状态，不得遗漏。"""
    from stocksim.core.errors import ERROR_STATUS, ErrorCode

    challenge_codes = [c for c in ErrorCode if c.value.startswith("CHALLENGE_")]
    assert len(challenge_codes) == 10
    for code in challenge_codes:
        assert code in ERROR_STATUS, code.value
        assert 400 <= ERROR_STATUS[code] < 600
