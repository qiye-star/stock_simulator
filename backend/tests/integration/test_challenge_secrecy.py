"""每日挑战的保密（C11，03 §5）：进行中（running）玩家可达的 GET 与 WS 帧不泄露 seed、盐、承诺原文。

秘密值由 ORM 读出（challenges.market_seed / seed_salt、domain 复算的 commitment_input），
再与响应文本逐项比对；键名层面禁止 end_tt、ends_at、resolve_tts 等服务端专用字段出现非空值。
时间由 fake_clock 控制；compact 调度下开局即第 1 段快放。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from stocksim.domain.challenge.commit import commitment_input
from stocksim.models import Challenge
from stocksim.services.challenges import entries, generate, registry
from stocksim.services.stocks import stock_pool

CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)
CHALLENGE_DAY = date(2026, 10, 26)
PASSWORD = "secret1"
# 响应中出现即违规（值非空）：服务端专用字段（03 §5 #1、#5、#8）
SECRET_KEYS = {
    "end_tt",
    "ends_at",
    "seed",
    "market_seed",
    "seed_salt",
    "commitment_input",
    "hold_tt",
    "resolve_tt",
    "resolve_tts",
}
# 运行中可达的 GET：状态码只允许 200（可用）或 409（该功能在挑战玩家存档上不可用）
ALLOWED_STATUS = {200, 409}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _secrets(db, ch: Challenge) -> dict[str, str]:
    """ORM 读出的真实秘密值：十进制 seed、盐、承诺原文。"""
    row = db.get(Challenge, ch.id)
    text = commitment_input(
        date_iso=row.challenge_date.isoformat(),
        events_ruleset=row.events_ruleset,
        clock_rules=row.clock_rules,
        seed=row.market_seed,
        salt_hex=row.seed_salt,
    )
    return {"seed": str(row.market_seed), "salt": row.seed_salt, "commitment_input": text}


def _leaks(body: Any, secrets: dict[str, str]) -> list[str]:
    """返回所有违规描述：文本含秘密值，或服务端专用键带非空值。"""
    found: list[str] = []
    text = body if isinstance(body, str) else str(body)
    for name, value in secrets.items():
        if value and value in text:
            found.append(f"text contains {name}")

    def walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in SECRET_KEYS and val is not None:
                    found.append(f"{where}.{key}={val!r}"[:120])
                walk(val, f"{where}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{where}[{i}]")

    walk(body, "$")
    return found


def _iso(value: datetime) -> str:
    return _aware(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _setup(challenge_app, db, fake_clock, make_user):
    user = make_user("alice")
    ch = generate.ensure_challenge(db, CHALLENGE_DAY, now=CHALLENGE_NOW)
    fake_clock.value = _aware(ch.starts_at)
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    client = TestClient(challenge_app)
    resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client, ch, entry


def _sweep_paths(save_id: str, ch_id: str, code: str) -> list[str]:
    s = f"/api/v1/saves/{save_id}"
    c = f"/api/v1/challenges/{ch_id}"
    return [
        "/api/v1/saves",
        s,
        f"{s}/export",
        f"{s}/market",
        f"{s}/market/{code}",
        f"{s}/market/{code}/intraday",
        f"{s}/market/{code}/event-marks",
        f"{s}/portfolio",
        f"{s}/equity-curve",
        f"{s}/trades",
        f"{s}/day-summary",
        f"{s}/news",
        f"{s}/events",
        f"{s}/supply-chain",
        f"{s}/predictions",
        f"{s}/predictions/settings",
        f"{s}/intel",
        f"{s}/achievements",
        f"{s}/auto-trade/status",
        f"{s}/auto-trade/configs",
        f"{s}/auto-trade/events",
        "/api/v1/challenges/today",
        "/api/v1/challenges",
        c,
        f"{c}/rounds",
        f"{c}/leaderboard?board=total",
        "/api/v1/challenge-leaderboard?scope=week",
        f"{c}/reveal",
        f"{c}/review",
        "/api/v1/points",
        "/api/v1/points/ledger",
        "/api/v1/points/stats",
        "/api/v1/points/titles",
    ]


def _sweep(client: TestClient, ch: Challenge, entry, secrets: dict[str, str], code: str) -> None:
    failures: list[str] = []
    checked = 0
    for path in _sweep_paths(str(entry.save_id), str(ch.id), code):
        resp = client.get(path)
        if resp.status_code not in ALLOWED_STATUS:
            failures.append(f"{path} -> HTTP {resp.status_code}")
            continue
        checked += 1
        for leak in _leaks(resp.text, secrets):
            failures.append(f"{path}: {leak}")
    assert checked >= 25, checked
    assert failures == []


def test_running_get_endpoints_leak_no_seed_salt_or_commitment_input(
    challenge_app, db, fake_clock, make_user
) -> None:
    client, ch, entry = _setup(challenge_app, db, fake_clock, make_user)
    secrets = _secrets(db, ch)
    code = stock_pool()[0].code
    # 快放段（第 1 段）与停顿后（第 1 回合 open）各扫一遍
    _sweep(client, ch, entry, secrets, code)
    rnd1 = registry.round_by_index(db, ch, 1)
    fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
    _sweep(client, ch, entry, secrets, code)

    # 终局段：ends_at 永不输出，下一次变化为空
    fake_clock.value = _aware(ch.final_resume_at) + timedelta(seconds=1)
    final_card = client.get(f"/api/v1/challenges/{ch.id}")
    assert final_card.json()["phase"] == "final"
    assert final_card.json()["next_change_at"] is None
    assert _iso(ch.ends_at) not in final_card.text
    _sweep(client, ch, entry, secrets, code)

    exported = client.get(f"/api/v1/saves/{entry.save_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["save"]["market_seed"] is None
    assert exported.json()["challenge"]["challenge_id"] == str(ch.id)


def test_unrevealed_rounds_and_reveal_are_hidden_while_running(
    challenge_app, db, fake_clock, make_user
) -> None:
    client, ch, _entry = _setup(challenge_app, db, fake_clock, make_user)
    rnd1 = registry.round_by_index(db, ch, 1)
    cid = str(ch.id)

    card = client.get(f"/api/v1/challenges/{cid}")
    assert card.status_code == 200, card.text
    first_round = card.json()["rounds"][0]
    assert first_round["round_index"] == 1
    assert first_round["hold_at"] is None and first_round["event_id"] is None
    assert first_round["state"] in ("pending", "burst")
    assert client.get(f"/api/v1/challenges/{cid}/rounds").json() == {"items": []}
    # 下一次变化（hold_at）未到前既不输出字段值，也不输出时间串（03 §5 #8）
    assert card.json()["next_change_at"] is None
    assert _iso(rnd1.hold_at) not in card.text

    # 未到停顿的回合：作答与“不存在”同形（404 CHALLENGE_ROUND_NOT_FOUND）
    answer = client.put(
        f"/api/v1/challenges/{cid}/rounds/1/answer",
        json={"answers": {"dir": {"probs": [20, 20, 20, 20, 20]}}},
    )
    assert answer.status_code == 404, answer.text
    assert answer.json()["code"] == "CHALLENGE_ROUND_NOT_FOUND"

    reveal = client.get(f"/api/v1/challenges/{cid}/reveal")
    assert reveal.status_code == 409, reveal.text
    assert reveal.json()["code"] == "CHALLENGE_NOT_SETTLED"

    # 停顿后回合出现（event_id/hold_at 才有值），reveal 仍 409
    fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
    card = client.get(f"/api/v1/challenges/{cid}").json()
    assert card["rounds"][0]["hold_at"] is not None and card["rounds"][0]["event_id"]
    assert client.get(f"/api/v1/challenges/{cid}/reveal").status_code == 409


def test_ten_websocket_frames_while_running_leak_nothing(
    challenge_app, db, fake_clock, make_user
) -> None:
    client, ch, entry = _setup(challenge_app, db, fake_clock, make_user)
    secrets = _secrets(db, ch)
    rnd1 = registry.round_by_index(db, ch, 1)
    failures: list[str] = []
    with client.websocket_connect(f"/api/v1/ws/saves/{entry.save_id}") as ws:
        for i in range(10):
            if i == 5:  # 中途拨到停顿：后半段帧同样不得泄露
                fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
            frame = ws.receive_json()
            leaks = _leaks(frame, secrets)
            failures.extend(f"frame {i} {frame.get('t')}: {leak}" for leak in leaks)
    assert failures == []


def test_generation_and_advancing_log_no_seed_material(
    challenge_app, db, fake_clock, make_user, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    client, ch, entry = _setup(challenge_app, db, fake_clock, make_user)
    secrets = _secrets(db, ch)
    rnd1 = registry.round_by_index(db, ch, 1)
    fake_clock.value = _aware(rnd1.hold_at) + timedelta(seconds=1)
    client.get(f"/api/v1/saves/{entry.save_id}/market")  # 触发懒推进（含检查点）
    fake_clock.value = _aware(ch.ends_at) + timedelta(seconds=1)
    client.get(f"/api/v1/saves/{entry.save_id}/market")
    text = caplog.text
    assert secrets["seed"] not in text
    assert secrets["salt"] not in text
    assert secrets["commitment_input"] not in text
