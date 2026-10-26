"""每日挑战生成与配置（C4）：生成、幂等、日志不含 seed、作废、B 的 CardPolicy、compact 启动检查。

用例名含 `generate` 的即 03 §13.2 的 `-k generate` 子集。
"""

import hashlib
import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim.core.config import Settings
from stocksim.main import create_app
from stocksim.models import Challenge, ChallengeRound, LedgerEntry, Save, User
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import generate, registry, runner

DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)


def test_generate_creates_master_and_rounds_once(challenge_app, db, fake_clock) -> None:
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    again = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    assert again.id == ch.id
    assert db.scalar(select(func.count()).select_from(Challenge)) == 1

    assert ch.status == "scheduled" and ch.clock_rules == 2 and ch.schedule_mode == "compact"
    master = db.get(Save, ch.master_save_id)
    assert master.user_id is None and master.mode == "challenge_market"
    assert master.clock_minute == 570 and master.clock_rules == 2 and master.paused
    assert master.tick == 0 and master.trading_day == 0 and master.last_tick_at is None
    assert master.initial_fund_cents == 0 and master.cash_cents == 0
    assert master.market_seed == ch.market_seed and master.events_ruleset == ch.events_ruleset
    assert master.events_enabled is True


def test_generate_rounds_are_consistent_with_timeline(challenge_app, db, fake_clock) -> None:
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    rounds = registry.rounds_of(db, ch)
    assert [r.round_index for r in rounds] == [1, 2, 3, 4]
    holds = [r.hold_tt for r in rounds]
    assert holds == sorted(set(holds)) and holds[0] > 0
    for r in rounds:
        assert r.resume_at < r.hold_at < r.closes_at
        assert r.questions is None and r.outcomes == {} and r.opened_at is None
        assert r.resolve_tts and all(tt > r.hold_tt for tt in r.resolve_tts.values())
    assert rounds[-1].closes_at < ch.final_resume_at <= ch.ends_at
    assert ch.end_tt == max(tt for r in rounds for tt in r.resolve_tts.values())
    assert ch.starts_at == rounds[0].resume_at
    assert ch.entry_closes_at == rounds[-1].closes_at


def test_generate_log_has_no_seed(challenge_app, db, fake_clock, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    text = caplog.text
    assert "challenge generated" in text
    assert str(ch.market_seed) not in text
    assert ch.seed_salt not in text
    assert ch.seed_commitment in text


def test_generate_master_gets_no_prediction_card(challenge_app, db, fake_clock) -> None:
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    master = db.get(Save, ch.master_save_id)
    policy = predictions_service.card_policy(db, master)
    assert policy.enabled is False
    assert policy.points_reason is None
    assert policy.intel_allowed is False


def test_generate_void_when_screening_fails(
    challenge_app, db, fake_clock, caplog, monkeypatch
) -> None:
    monkeypatch.setattr(generate, "_screen", lambda seed: None)
    caplog.set_level(logging.ERROR)
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    assert ch.status == "void" and ch.void_reason == "screening_failed"
    assert ch.master_save_id is None
    assert db.scalar(select(func.count()).select_from(ChallengeRound)) == 0
    assert "challenge screening failed" in caplog.text
    assert str(ch.market_seed) not in caplog.text


def test_generate_void_challenge_refuses_entry(challenge_app, db, fake_clock, make_user) -> None:
    from stocksim.core.errors import AppError, ErrorCode
    from stocksim.services.challenges import entries

    user = make_user("voiduser")
    ch = generate.void_challenge(
        db, generate.ensure_challenge(db, DAY, now=fake_clock.value), "manual"
    )
    assert ch.status == "void"
    with pytest.raises(AppError) as exc:
        entries.join(db, ch, user, fake_clock.value)
    assert exc.value.code == ErrorCode.CHALLENGE_ENTRY_CLOSED


def test_compact_refuses_to_start_without_debug_api(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL=f"sqlite:///{tmp_path / 'x.db'}",
        CHALLENGE_SCHEDULE="compact",
        ENABLE_DEBUG_API=False,
    )
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_slots_must_match_round_count(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_URL=f"sqlite:///{tmp_path / 'x.db'}",
        CHALLENGE_SLOTS="07:00,12:00,17:00",
    )
    with pytest.raises(ValueError):
        create_app(settings)


# ---------------------------------------------------------------- HTTP 全流程（C9，03 §13.2）

PASSWORD = "secret1"
API = "/api/v1"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _login(app, username: str) -> TestClient:
    client = TestClient(app)
    resp = client.post(f"{API}/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return client


def _answers(questions: list[dict], idx: int) -> dict:
    """与 conftest.answers_for 同口径：bucket/binary 加权分布（合计 100），rank 轮转后取前三。"""
    out: dict = {}
    for q in questions:
        if q["kind"] in ("bucket", "binary"):
            k = len(q["edges_bp"]) + 1 if q["kind"] == "bucket" else 2
            weights = [1 + ((j + idx) % k) for j in range(k)]
            total = sum(weights)
            probs = [w * 100 // total for w in weights]
            probs[-1] += 100 - sum(probs)
            out[q["qid"]] = {"probs": probs}
        else:
            cands = list(q["candidates"])
            r = idx % len(cands)
            out[q["qid"]] = {"order": (cands[r:] + cands[:r])[:3]}
    return {"answers": out}


def _assert_no_secret(text: str, ch: Challenge) -> None:
    assert str(ch.market_seed) not in text
    assert ch.seed_salt not in text
    assert "commitment_input" not in text
    assert '"end_tt"' not in text and '"ends_at"' not in text


def _round(db, ch, k: int) -> ChallengeRound:
    db.expire_all()
    return registry.round_by_index(db, ch, k)


def test_http_full_lifecycle(challenge_app, db, fake_clock, make_user):
    factory = challenge_app.state.session_factory
    make_user("alice")
    make_user("bob")
    alice = _login(challenge_app, "alice")
    bob = _login(challenge_app, "bob")

    # 生成（调试入口）→ scheduled；承诺可见，seed 与 end_tt 不可见
    created = alice.post(f"{API}/debug/challenges/ensure")
    assert created.status_code == 200, created.text
    body = created.json()
    cid = body["id"]
    ch = registry.challenge_for_date(db, DAY)
    assert body["status"] == "scheduled" and body["phase"] == "before"
    assert body["seed_commitment"] == ch.seed_commitment
    assert body["commitment_scheme"] == "sha256/stocksim-challenge|v1"
    assert all(r["hold_at"] is None and r["event_id"] is None for r in body["rounds"])
    _assert_no_secret(created.text, ch)
    assert alice.get(f"{API}/challenges/{cid}/reveal").json()["code"] == "CHALLENGE_NOT_SETTLED"
    not_entered = alice.put(f"{API}/challenges/{cid}/rounds/1/answer", json=_answers([], 0))
    assert not_entered.status_code == 409
    assert not_entered.json()["code"] == "CHALLENGE_NOT_ENTERED"  # 报名先于回合可见性判断

    # 开始：懒迁移为 running；第一段快放中
    fake_clock.value = _aware(ch.starts_at) + timedelta(seconds=1)
    today = alice.get(f"{API}/challenges/today")
    assert today.status_code == 200
    assert today.json()["status"] == "running" and today.json()["phase"] == "burst"
    assert today.json()["round_index"] == 1
    _assert_no_secret(today.text, ch)

    # 报名：新建 201，重复 200 且同一条
    first = alice.post(f"{API}/challenges/{cid}/entry")
    assert first.status_code == 201, first.text
    again = alice.post(f"{API}/challenges/{cid}/entry")
    assert again.status_code == 200 and again.json()["entry_id"] == first.json()["entry_id"]
    entry_id = first.json()["entry_id"]
    assert bob.post(f"{API}/challenges/{cid}/entry").status_code == 201
    assert alice.get(f"{API}/challenges/{cid}/rounds").json()["items"] == []

    # 第 1 回合停顿：卡片与 event_id 出现，题目出现
    hold1 = _aware(_round(db, ch, 1).hold_at)
    fake_clock.value = hold1 + timedelta(seconds=1)
    items = alice.get(f"{API}/challenges/{cid}/rounds").json()["items"]
    assert len(items) == 1
    card = items[0]
    assert card["round_index"] == 1 and card["state"] == "open"
    assert card["event"] is not None and card["questions"] and card["crowd"] is None
    assert card["my_answers"] == [] and card["my_revision"] == 0 and card["results"] == []
    assert len(alice.get(f"{API}/challenges/{cid}/rounds").json()["items"]) == 1

    # 作答：校验失败 422；成功 200；修改计数递增
    url = f"{API}/challenges/{cid}/rounds/1/answer"
    bad = alice.put(url, json={"answers": {}})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    put1 = alice.put(url, json=_answers(card["questions"], 0))
    assert put1.status_code == 200, put1.text
    assert put1.json()["my_revision"] == 1
    assert len(put1.json()["my_answers"]) == len(card["questions"])
    assert alice.put(url, json=_answers(card["questions"], 1)).json()["my_revision"] == 2
    assert bob.put(url, json=_answers(card["questions"], 2)).status_code == 200
    # 未到回合（第 3 回合）：与不存在相同的 404
    assert alice.put(
        f"{API}/challenges/{cid}/rounds/3/answer", json=_answers(card["questions"], 0)
    ).json()["code"] == "CHALLENGE_ROUND_NOT_FOUND"

    # 修改次数上限 20：已有 2 次，再改 18 次到 20，第 21 次被拒
    for i in range(3, 21):
        assert alice.put(url, json=_answers(card["questions"], i)).status_code == 200
    limit = alice.put(url, json=_answers(card["questions"], 0))
    assert limit.status_code == 409 and limit.json()["code"] == "CHALLENGE_ANSWER_LIMIT"

    # 截止后：拒绝作答；群体分布出现（只含合格报名：两人都合格）
    closes1 = _aware(_round(db, ch, 1).closes_at)
    fake_clock.value = closes1 + timedelta(seconds=1)
    closed = alice.get(f"{API}/challenges/{cid}/rounds").json()["items"][0]
    assert closed["state"] == "closed" and closed["crowd"] is not None
    assert closed["crowd"]["n"] == 2
    late = alice.put(url, json=_answers(card["questions"], 0))
    assert late.status_code == 409 and late.json()["code"] == "CHALLENGE_ROUND_CLOSED"

    # 终局之前：未结算，报名与排行 409；本人复盘 409
    ends = _aware(ch.ends_at)
    fake_clock.value = ends - timedelta(seconds=1)
    not_settled = alice.get(f"{API}/challenges/{cid}/leaderboard")
    assert not_settled.json()["code"] == "CHALLENGE_NOT_SETTLED"
    assert alice.get(f"{API}/challenges/{cid}/review").json()["code"] == "CHALLENGE_NOT_SETTLED"

    # 结算：runner 推到终局并结算；判定写入 outcomes 与分数
    fake_clock.value = ends + timedelta(seconds=1)
    report = runner.run_due(factory, fake_clock.value)
    assert report.settled == 1 and report.errors == 0
    db.expire_all()
    ch = db.get(Challenge, ch.id)
    assert ch.status == "settled"
    rounds_now = alice.get(f"{API}/challenges/{cid}/rounds").json()["items"]
    assert len(rounds_now) == 4
    assert all(r["state"] == "resolved" for r in rounds_now)
    assert all(r["results"] for r in rounds_now)  # 判定真值对所有人公开
    # alice 只答了第 1 回合：只有该回合有本人分数
    assert rounds_now[0]["my_round_score"] is not None
    assert all(r["my_round_score"] is None for r in rounds_now[1:])
    assert all(q["used"] in ("peer", "baseline") for q in rounds_now[0]["results"])
    answer_after = alice.put(url, json=_answers(card["questions"], 0))
    assert answer_after.status_code == 409  # 结算后不可再答（回合已截止）

    # 排行与报名结果
    board = alice.get(f"{API}/challenges/{cid}/leaderboard")
    assert board.status_code == 200, board.text
    assert board.json()["eligible_count"] == 2 and len(board.json()["items"]) == 2
    assert board.json()["me"]["is_me"] is True
    assert alice.get(f"{API}/challenges/{cid}/leaderboard?board=trade").status_code == 200
    assert alice.get(f"{API}/challenges/{cid}/leaderboard?limit=0").status_code == 422
    week = alice.get(f"{API}/challenge-leaderboard?scope=all")
    assert week.status_code == 200 and len(week.json()["items"]) == 2
    assert alice.get(f"{API}/challenge-leaderboard?sort=bogus").status_code == 422
    today_after = alice.get(f"{API}/challenges/today").json()
    assert today_after["status"] == "settled" and today_after["my_entry"]["result"]["rank"]
    assert alice.post(f"{API}/challenges/{cid}/entry").status_code == 200  # 已报名，原样返回

    # 复盘与 reveal：承诺可本地校验，seed 等于 master 的 seed
    reveal = alice.get(f"{API}/challenges/{cid}/reveal").json()
    assert reveal["status"] == "settled"
    assert hashlib.sha256(reveal["commitment_input"].encode("utf-8")).hexdigest() == (
        reveal["seed_commitment"]
    )
    master = db.get(Save, ch.master_save_id)
    assert reveal["market_seed"] == str(master.market_seed) == str(ch.market_seed)
    assert reveal["review_available"] is True and len(reveal["rounds"]) == 4
    review = alice.get(f"{API}/challenges/{cid}/review").json()
    assert review["save_available"] is True and review["entry"]["entry_id"] == entry_id
    assert review["entry"]["result"] is not None and len(review["rounds"]) == 4

    # 账本：每人恰一条挑战奖励；再跑 run_due 不重复入账
    for username in ("alice", "bob"):
        user = db.scalar(select(User).where(User.username == username))
        n = db.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.user_id == user.id, LedgerEntry.reason == "challenge"
            )
        )
        assert n == 1
    runner.run_due(factory, fake_clock.value + timedelta(hours=1))
    db.expire_all()
    assert db.scalar(
        select(func.count(LedgerEntry.id)).where(LedgerEntry.reason == "challenge")
    ) == 2



def test_http_entry_after_settlement_is_refused(challenge_app, db, fake_clock, make_user):
    factory = challenge_app.state.session_factory
    make_user("latecomer")
    client = _login(challenge_app, "latecomer")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = _aware(ch.ends_at) + timedelta(seconds=1)
    runner.run_due(factory, fake_clock.value)
    resp = client.post(f"{API}/challenges/{ch.id}/entry")
    assert resp.status_code == 409 and resp.json()["code"] == "CHALLENGE_ENDED"


def test_http_void_reveal_available_without_settlement(challenge_app, db, fake_clock, make_user):
    make_user("voider")
    client = _login(challenge_app, "voider")
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    generate.void_challenge(db, ch, "manual")
    board = client.get(f"{API}/challenges/{ch.id}")
    assert board.status_code == 200 and board.json()["status"] == "void"
    assert board.json()["phase"] == "ended" and board.json()["rounds"] == []
    _assert_no_secret(board.text, ch)

    reveal = client.get(f"{API}/challenges/{ch.id}/reveal")
    assert reveal.status_code == 200, reveal.text
    body = reveal.json()
    assert body["status"] == "void" and body["rounds"] == [] and body["end_tt"] is None
    assert body["review_available"] is False
    assert body["market_seed"] == str(ch.market_seed)
    assert hashlib.sha256(body["commitment_input"].encode("utf-8")).hexdigest() == (
        body["seed_commitment"]
    )


def test_http_list_pagination_and_cursor_errors(challenge_app, db, fake_clock, make_user):
    make_user("lister")
    client = _login(challenge_app, "lister")
    for offset in (0, 1, 2):
        generate.ensure_challenge(
            db, DAY - timedelta(days=offset), now=CHALLENGE_NOW - timedelta(days=offset)
        )
    page1 = client.get(f"{API}/challenges?limit=2")
    assert page1.status_code == 200, page1.text
    dates1 = [item["challenge_date"] for item in page1.json()["items"]]
    assert dates1 == ["2026-10-26", "2026-10-25"]
    cursor = page1.json()["next_cursor"]
    assert cursor == "2026-10-25"
    page2 = client.get(f"{API}/challenges?limit=2&cursor={cursor}")
    assert [item["challenge_date"] for item in page2.json()["items"]] == ["2026-10-24"]
    assert page2.json()["next_cursor"] is None
    bad = client.get(f"{API}/challenges?cursor=not-a-date")
    assert bad.status_code == 422 and bad.json()["params"]["field"] == "cursor"
    assert client.get(f"{API}/challenges?limit=51").status_code == 422


def test_http_disabled_returns_404(challenge_app_factory, fake_clock):
    from stocksim.services import auth as auth_service

    app = challenge_app_factory("disabled", CHALLENGE_ENABLED=False)
    with app.state.session_factory() as session:  # 用户须建在本应用的库里
        auth_service.register(session, "offline", PASSWORD)
    client = _login(app, "offline")
    for path in ("/challenges/today", "/challenges", "/challenge-leaderboard"):
        resp = client.get(f"{API}{path}")
        assert resp.status_code == 404 and resp.json()["code"] == "CHALLENGE_NOT_FOUND", path
    assert client.post(f"{API}/debug/challenges/ensure").status_code == 404


def test_http_requires_login(challenge_app):
    client = TestClient(challenge_app)
    resp = client.get(f"{API}/challenges/today")
    assert resp.status_code == 401 and resp.json()["code"] == "AUTH_REQUIRED"
