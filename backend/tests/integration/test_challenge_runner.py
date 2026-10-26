"""每日挑战 runner（C8）：run_due 幂等、并发只生成/结算一次、清理保留期、CHALLENGE_ENABLED 空转、
调试平移可推到结算、懒触发节流、CLI 的 show 结算前不出 seed。

时间由 fake_clock 控制（monkeypatch timeutil.now）；run_due 的 now 参数显式传入。
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from stocksim import cli_challenge
from stocksim.models import Challenge, ChallengeEntry, LedgerEntry, Save
from stocksim.services.challenges import generate, runner
from stocksim.services.challenges.registry import challenge_for_date

DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)
PASSWORD = "secret1"


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def count_challenges(db) -> int:
    return int(db.scalar(select(func.count()).select_from(Challenge)) or 0)


@pytest.fixture
def ended(challenge_app, db, fake_clock, make_user, challenge_play):
    """一场已打完回合、尚未结算的挑战（3 个合格玩家）。时钟停在终局之前。"""
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    users = [make_user(f"runner{i}") for i in range(3)]
    rows = challenge_play.join(ch, users)
    challenge_play.play_rounds(ch, rows)
    return ch, users


# ---------------------------------------------------------------- run_due


def test_run_due_twice_gives_same_state(challenge_app, db, fake_clock):
    factory = challenge_app.state.session_factory
    first = runner.run_due(factory, CHALLENGE_NOW)
    assert first.generated == 1 and first.errors == 0
    second = runner.run_due(factory, CHALLENGE_NOW)
    assert second.errors == 0
    assert (second.generated, second.promoted, second.advanced, second.settled) == (0, 0, 0, 0)
    assert count_challenges(db) == 1
    ch = challenge_for_date(db, DAY)
    assert ch.status == "scheduled"

    start = aware(ch.starts_at) + timedelta(seconds=1)
    assert runner.run_due(factory, start).promoted == 1
    assert runner.run_due(factory, start).promoted == 0
    db.refresh(ch)
    assert ch.status == "running" and ch.version >= 2


def test_concurrent_run_due_generates_one_challenge(challenge_app, db, fake_clock):
    factory = challenge_app.state.session_factory
    results: list[runner.RunReport] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(runner.run_due(factory, CHALLENGE_NOW))
        except BaseException as exc:  # pragma: no cover - 失败时收集，断言里报告
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors
    assert count_challenges(db) == 1  # 唯一键保证只落一行
    assert all(r.errors <= 1 for r in results)


def test_concurrent_run_due_settles_once(ended, challenge_app, db, fake_clock):
    ch, users = ended
    factory = challenge_app.state.session_factory
    fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
    threads = [
        threading.Thread(target=runner.run_due, args=(factory, fake_clock.value))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    db.expire_all()
    ch = db.get(Challenge, ch.id)
    assert ch.status == "settled"
    for user in users:
        n = db.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.user_id == user.id,
                LedgerEntry.idempotency_key == f"challenge:{ch.id}:{user.id}",
            )
        )
        assert n == 1


def test_run_due_is_noop_when_disabled(challenge_app_factory, fake_clock):
    app = challenge_app_factory("off", CHALLENGE_ENABLED=False)
    report = runner.run_due(app.state.session_factory, CHALLENGE_NOW)
    assert report == runner.RunReport()
    with app.state.session_factory() as db:
        assert count_challenges(db) == 0


def test_compact_without_debug_api_refuses_to_start(tmp_path) -> None:
    from stocksim.core.config import Settings
    from stocksim.main import create_app

    settings = Settings(
        _env_file=None,
        DATABASE_URL=f"sqlite:///{tmp_path / 'x.db'}",
        CHALLENGE_SCHEDULE="compact",
        ENABLE_DEBUG_API=False,
    )
    with pytest.raises(RuntimeError):
        create_app(settings)


# ---------------------------------------------------------------- 清理（03 §6.3）


def test_cleanup_deletes_player_saves_then_master(ended, challenge_app, db, fake_clock):
    ch, users = ended
    factory = challenge_app.state.session_factory
    fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
    assert runner.run_due(factory, fake_clock.value).settled == 1
    db.expire_all()
    ch = db.get(Challenge, ch.id)
    settled_at = aware(ch.settled_at)
    entries_before = db.scalar(select(func.count(ChallengeEntry.id)))
    master_id = ch.master_save_id
    assert master_id is not None

    # 保留期内：什么都不删
    fake_clock.value = settled_at + timedelta(days=13)
    assert runner.run_due(factory, fake_clock.value).cleaned_saves == 0

    # 玩家存档超过 14 天：先删玩家存档，成绩保留、save_id 置空，master 仍在
    fake_clock.value = settled_at + timedelta(days=15)
    report = runner.run_due(factory, fake_clock.value)
    assert report.cleaned_saves == len(users) and report.errors == 0
    db.expire_all()
    assert db.scalar(select(func.count(Save.id)).where(Save.mode == "challenge")) == 0
    assert db.scalar(select(func.count(ChallengeEntry.id))) == entries_before
    assert db.scalar(
        select(func.count(ChallengeEntry.id)).where(ChallengeEntry.save_id.is_not(None))
    ) == 0
    assert db.get(Save, master_id) is not None

    # 玩家存档清理后，复盘的 save_available 为 false（HTTP）
    client = TestClient(challenge_app)
    login = client.post(
        "/api/v1/auth/login", json={"username": users[0].username, "password": PASSWORD}
    )
    assert login.status_code == 200
    review = client.get(f"/api/v1/challenges/{ch.id}/review")
    assert review.status_code == 200, review.text
    assert review.json()["save_available"] is False
    assert review.json()["entry"]["save_id"] is None

    # master 超过 30 天：删除，challenges.master_save_id 置空
    fake_clock.value = settled_at + timedelta(days=31)
    report = runner.run_due(factory, fake_clock.value)
    assert report.cleaned_saves >= 1 and report.errors == 0
    db.expire_all()
    assert db.get(Save, master_id) is None
    assert db.get(Challenge, ch.id).master_save_id is None


# ---------------------------------------------------------------- 调试平移（03 §10.1）


def test_debug_shift_drives_challenge_to_settlement(challenge_app, make_user, fake_clock, db):
    make_user("shifter")
    make_user("shiftee")
    organizer = TestClient(challenge_app)
    assert organizer.post(
        "/api/v1/auth/login", json={"username": "shifter", "password": PASSWORD}
    ).status_code == 200
    ensured = organizer.post("/api/v1/debug/challenges/ensure")
    assert ensured.status_code == 200, ensured.text
    cid = ensured.json()["id"]
    assert ensured.json()["status"] == "scheduled"

    ch = challenge_for_date(db, DAY)
    fake_clock.value = aware(ch.starts_at) + timedelta(seconds=1)
    running = organizer.get("/api/v1/challenges/today")
    assert running.json()["status"] == "running"

    shifted = organizer.post(f"/api/v1/debug/challenges/{cid}/shift", json={"seconds": 86400})
    assert shifted.status_code == 200, shifted.text
    assert shifted.json()["status"] == "settled"
    assert shifted.json()["phase"] == "ended"

    again = organizer.post(f"/api/v1/debug/challenges/{cid}/shift", json={"seconds": 60})
    assert again.status_code == 409 and again.json()["code"] == "CHALLENGE_ENDED"
    bad = organizer.post(f"/api/v1/debug/challenges/{cid}/shift", json={"seconds": 0})
    assert bad.status_code == 422
    reveal = organizer.get(f"/api/v1/challenges/{cid}/reveal")
    assert reveal.status_code == 200 and reveal.json()["status"] == "settled"


# ---------------------------------------------------------------- 懒触发节流（03 §11.2）


def test_maybe_run_due_is_throttled(challenge_app, db, monkeypatch):
    runner.reset_throttle()
    clock = {"mono": 1000.0}
    monkeypatch.setattr(runner, "_monotonic", lambda: clock["mono"])
    calls: list[datetime] = []
    monkeypatch.setattr(
        runner, "run_due", lambda factory, now: calls.append(now) or runner.RunReport()
    )
    assert runner.maybe_run_due(db, CHALLENGE_NOW) is True
    clock["mono"] += 5.0
    assert runner.maybe_run_due(db, CHALLENGE_NOW) is False  # 10 s 内跳过
    clock["mono"] += 5.5
    assert runner.maybe_run_due(db, CHALLENGE_NOW) is True
    assert len(calls) == 2


def test_maybe_run_due_logs_failure_and_does_not_raise(challenge_app, db, monkeypatch, caplog):
    runner.reset_throttle()

    def boom(factory, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "run_due", boom)
    assert runner.maybe_run_due(db, CHALLENGE_NOW) is False
    assert "lazy run_due failed" in caplog.text


# ---------------------------------------------------------------- CLI（03 §11.2）


def test_cli_show_hides_seed_until_settled_and_void_works(
    challenge_app, db, fake_clock, monkeypatch, capsys
):
    monkeypatch.setattr(cli_challenge, "get_settings", lambda: challenge_app.state.settings)
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    seed, salt, commitment = str(ch.market_seed), ch.seed_salt, ch.seed_commitment

    assert cli_challenge.main(["show", "--date", DAY.isoformat()]) == 0
    out = capsys.readouterr().out
    assert commitment in out
    assert seed not in out and salt not in out

    assert cli_challenge.main(["void", "--date", DAY.isoformat(), "--reason", "运维作废"]) == 0
    capsys.readouterr()
    assert cli_challenge.main(["show", "--date", DAY.isoformat()]) == 0
    shown = capsys.readouterr().out
    assert seed in shown and salt in shown  # 作废后公开 seed（03 §1.4）

    with pytest.raises(SystemExit):  # argparse 对超长 reason 报错退出
        cli_challenge.main(["void", "--date", DAY.isoformat(), "--reason", "x" * 33])
    assert cli_challenge.main(["show", "--date", "2030-01-01"]) == 1
    capsys.readouterr()


def test_cli_run_due_returns_zero_when_healthy(challenge_app, monkeypatch, capsys):
    monkeypatch.setattr(cli_challenge, "get_settings", lambda: challenge_app.state.settings)
    monkeypatch.setattr(cli_challenge.timeutil, "now", lambda: CHALLENGE_NOW)
    assert cli_challenge.main(["run-due"]) == 0
    assert '"generated": 1' in capsys.readouterr().out
