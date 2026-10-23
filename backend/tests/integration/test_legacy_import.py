"""旧版存档导入：XOR+Base64 解码、严格结构校验、映射为当前用户的新存档、审计行。

样例由 tests/fixtures/make_legacy_export.py 生成（legacy/crypto.js 同款编码）。
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.models import Holding, LegacyImport, Save, SaveAchievement, Trade, WatchlistItem
from stocksim.services.seed import seed_stock_table

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
API = "/api/v1/import/legacy"
PASSWORD = "secret1"

sys.path.insert(0, str(FIXTURES))
from make_legacy_export import encode_legacy  # noqa: E402

SAMPLE_JSON = (FIXTURES / "legacy_sample.json").read_text(encoding="utf-8")
SAMPLE_EXPORT = (FIXTURES / "legacy_export.txt").read_text(encoding="ascii")


@pytest.fixture
def client(registered_client: TestClient, app: FastAPI) -> TestClient:
    with app.state.session_factory() as db:
        seed_stock_table(db)
    return registered_client


def _post(client: TestClient, content: str):
    return client.post(API, json={"content": content})


def test_fixture_is_in_sync_with_generator() -> None:
    """样例文件必须等于生成器输出，避免手改后失真。"""
    assert (
        encode_legacy(json.dumps(json.loads(SAMPLE_JSON), ensure_ascii=False))
        == SAMPLE_EXPORT.strip()
    )


def test_import_export_text_creates_save_for_current_user(client: TestClient, app: FastAPI) -> None:
    resp = _post(client, SAMPLE_EXPORT)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["imported"]) == 1
    assert body["skipped_achievements"] == 1  # not_a_real_achievement 被丢弃
    item = body["imported"][0]
    assert item["name"] == "旧存档一"
    assert item["cash_cents"] == 92_980_098  # 929800.98 元
    assert item["holdings"] == 1 and item["trades"] == 2
    assert item["watchlist"] == 1 and item["achievements"] == 2

    saves = client.get("/api/v1/saves").json()
    assert [s["id"] for s in saves] == [item["save_id"]]  # 挂到当前用户名下

    with app.state.session_factory() as db:
        save_id = item["save_id"]
        import uuid

        sid = uuid.UUID(save_id)
        save = db.get(Save, sid)
        assert save.initial_fund_cents == 100_000_000
        assert save.trade_seq == 2
        trades = list(db.scalars(select(Trade).where(Trade.save_id == sid).order_by(Trade.seq)))
        assert [(t.side, t.quantity, t.price_cents) for t in trades] == [
            ("buy", 100, 150_050),
            ("sell", 50, 160_000),
        ]
        # 手续费由 legacy 金额反推：买入 45.02 元（150050 * 0.0003 四舍五入）
        assert trades[0].fee_cents == 4_502
        assert trades[0].cash_delta_cents == -15_009_502
        assert trades[1].realized_pnl_cents == 487_100
        holding = db.scalar(select(Holding).where(Holding.save_id == sid))
        assert holding.quantity == 50 and holding.avg_price_cents == 150_050
        assert (
            db.scalar(select(WatchlistItem.stock_code).where(WatchlistItem.save_id == sid))
            == "600036"
        )
        unlocked = set(
            db.scalars(select(SaveAchievement.achievement_id).where(SaveAchievement.save_id == sid))
        )
        assert unlocked == {"first_trade", "first_profit"}


def test_plain_json_is_accepted(client: TestClient) -> None:
    resp = _post(client, SAMPLE_JSON)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["imported"]) == 1


def test_whole_localstorage_blob_imports_every_user_save(client: TestClient) -> None:
    """旧版 localStorage `stock_simulator_users` 是 {username: userData} 映射，整包可直接上传。"""
    sample = json.loads(SAMPLE_JSON)
    other = json.loads(SAMPLE_JSON)
    other["username"] = "legacy_carol"
    blob = json.dumps({sample["username"]: sample, other["username"]: other}, ensure_ascii=False)
    from make_legacy_export import encode_legacy as enc

    resp = _post(client, enc(blob))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["imported"]) == 2
    assert resp.json()["skipped_achievements"] == 2


def test_users_map_with_non_object_value_is_schema_error(client: TestClient) -> None:
    from make_legacy_export import encode_legacy as enc

    blob = json.dumps({"alice": {"username": "alice", "saves": []}, "bob": "oops"})
    _assert_invalid(_post(client, enc(blob)), "schema")


def test_password_hash_and_username_are_ignored(client: TestClient, app: FastAPI) -> None:
    assert _post(client, SAMPLE_EXPORT).status_code == 200
    # 不创建旧用户；当前用户的密码不变
    with app.state.session_factory() as db:
        from stocksim.models import User

        assert db.scalar(select(func.count()).select_from(User)) == 1
    fresh = TestClient(app)
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_audit_row_records_sha256(client: TestClient, app: FastAPI) -> None:
    assert _post(client, SAMPLE_EXPORT).status_code == 200
    digest = hashlib.sha256(SAMPLE_EXPORT.encode("utf-8")).hexdigest()
    with app.state.session_factory() as db:
        row = db.scalar(select(LegacyImport).where(LegacyImport.status == "imported"))
        assert row.source_sha256 == digest
        assert row.source_format == "legacy-xor"
        assert row.save_id is not None


def _assert_invalid(resp, reason: str) -> None:
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "LEGACY_IMPORT_INVALID"
    assert body["params"]["reason"] == reason


def test_invalid_base64_is_rejected_and_audited(client: TestClient, app: FastAPI) -> None:
    _assert_invalid(_post(client, "%%%not-base64%%%"), "base64")
    with app.state.session_factory() as db:
        assert (
            db.scalar(select(LegacyImport.status).where(LegacyImport.status == "failed"))
            == "failed"
        )


def test_wrong_key_decodes_to_invalid_json(client: TestClient) -> None:
    text = encode_legacy(SAMPLE_JSON, key="not-the-key")
    _assert_invalid(_post(client, text), "json")


def test_schema_violations_are_rejected(client: TestClient) -> None:
    data = json.loads(SAMPLE_JSON)
    data["saves"][0]["settings"]["buyFee"] = 0.5  # 费率超过 0.01
    resp = _post(client, json.dumps(data))
    _assert_invalid(resp, "schema")
    assert resp.json()["params"]["errors"]


def test_strict_types_reject_string_numbers(client: TestClient) -> None:
    data = json.loads(SAMPLE_JSON)
    data["saves"][0]["holdings"]["600519"]["quantity"] = "50"
    _assert_invalid(_post(client, json.dumps(data)), "schema")


def test_unknown_stock_is_rejected(client: TestClient) -> None:
    data = json.loads(SAMPLE_JSON)
    data["saves"][0]["holdings"]["999998"] = {
        "name": "x",
        "quantity": 1,
        "avgPrice": 1,
        "totalCost": 1,
    }
    resp = _post(client, json.dumps(data))
    _assert_invalid(resp, "unknown_stock")
    assert "999998" in resp.json()["params"]["codes"]


def test_inconsistent_record_is_rejected(client: TestClient) -> None:
    data = json.loads(SAMPLE_JSON)
    data["saves"][0]["records"][1]["amount"] = -1.0  # 买入金额小于成交额
    _assert_invalid(_post(client, json.dumps(data)), "record_mismatch")


def test_oversized_content_is_rejected(client: TestClient) -> None:
    _assert_invalid(_post(client, "A" * (8 * 1024 * 1024 + 1)), "too_large")


def test_missing_content_is_validation_error(client: TestClient) -> None:
    resp = client.post(API, json={})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_requires_login(app: FastAPI, client: TestClient) -> None:
    resp = TestClient(app).post(API, json={"content": SAMPLE_EXPORT})
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"
