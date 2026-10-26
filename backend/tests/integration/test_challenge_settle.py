"""每日挑战结算的生命周期（C6）：到期前不结算、幂等、奖励账本恰一条、
批次与 status 顺序、reveal、日志保密。"""

import hashlib
import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.commit import commitment_input
from stocksim.models import Challenge, ChallengeEntry, LedgerEntry, Save
from stocksim.services.challenges import generate, hooks, settle, views

DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest.fixture
def played(challenge_app, db, fake_clock, make_user, challenge_play):
    """打完一场挑战（未结算）：3 个合格者与 1 个不合格者，时钟停在终局之前。"""
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    starts = aware(ch.starts_at)
    users = [make_user(f"player{i}") for i in range(3)]
    late = make_user("latecomer")
    late.created_at = starts + timedelta(hours=1)
    db.commit()
    users.append(late)
    rows = challenge_play.join(ch, users)
    challenge_play.play_rounds(ch, rows)
    fake_clock.value = aware(ch.ends_at) - timedelta(seconds=1)
    return ch


def test_settle_before_end_returns_false_and_keeps_running(played, db, fake_clock):
    assert settle.settle_if_due(db, played, fake_clock.value) is False
    db.refresh(played)
    assert played.status == "running" and played.settled_at is None


def test_reveal_and_entry_result_require_settlement(played, db):
    with pytest.raises(AppError) as exc:
        views.reveal_out(db, played)
    assert exc.value.code == ErrorCode.CHALLENGE_NOT_SETTLED
    entry = db.scalars(
        select(ChallengeEntry).where(ChallengeEntry.challenge_id == played.id)
    ).first()
    assert views.entry_result_out(entry, 0) is None


def test_settle_once_credits_each_reward_exactly_once(played, challenge_play, db, fake_clock):
    assert challenge_play.settle(played) is True
    db.refresh(played)
    assert played.status == "settled" and played.settled_at is not None
    assert played.revealed_at == played.settled_at
    assert played.eligible_count == 3

    entries = list(
        db.scalars(select(ChallengeEntry).where(ChallengeEntry.challenge_id == played.id))
    )
    assert all(e.settled_at is not None for e in entries)
    rewarded = [e for e in entries if e.points_awarded > 0]
    assert len(rewarded) == 3 and all(e.eligible for e in rewarded)
    for e in rewarded:
        rows = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.idempotency_key == f"challenge:{played.id}:{e.user_id}"
            )
        ).all()
        assert len(rows) == 1 and rows[0].delta == e.points_awarded
    ledger_total = db.scalar(
        select(func.count(LedgerEntry.seq)).where(LedgerEntry.reason == "challenge")
    )
    assert ledger_total == 3

    # 再次结算：返回 False，账本与成绩不变
    before = [(e.id, e.points_awarded, e.total_score, e.rank) for e in entries]
    assert challenge_play.settle(played) is False
    assert settle.settle_if_due(db, played, fake_clock.value) is False
    assert (
        db.scalar(select(func.count(LedgerEntry.seq)).where(LedgerEntry.reason == "challenge")) == 3
    )
    after = [
        (e.id, e.points_awarded, e.total_score, e.rank)
        for e in db.scalars(select(ChallengeEntry).where(ChallengeEntry.challenge_id == played.id))
    ]
    assert sorted(before) == sorted(after)


def test_settle_batches_give_same_result(played, challenge_play, db, monkeypatch):
    monkeypatch.setattr(settle, "SETTLE_BATCH", 1)
    assert challenge_play.settle(played) is True
    db.refresh(played)
    assert played.status == "settled"
    assert (
        db.scalar(select(func.count(LedgerEntry.seq)).where(LedgerEntry.reason == "challenge")) == 3
    )


def test_settled_hook_runs_before_status_changes(played, challenge_play, db):
    seen: list[str] = []

    def on_settled(session, ch):
        seen.append(ch.status)

    hooks.register_settled_hook(on_settled)
    try:
        assert challenge_play.settle(played) is True
    finally:
        hooks.clear_hooks()
    assert seen == ["running"]
    db.refresh(played)
    assert played.status == "settled"


def test_reveal_matches_commitment_and_master_seed(played, challenge_play, db):
    challenge_play.settle(played)
    db.refresh(played)
    master = db.get(Save, played.master_save_id)
    out = views.reveal_out(db, played)
    assert out["market_seed"] == str(master.market_seed) == str(played.market_seed)
    assert out["seed_salt"] == played.seed_salt
    assert out["seed_commitment"] == played.seed_commitment
    digest = hashlib.sha256(out["commitment_input"].encode()).hexdigest()
    assert digest == out["seed_commitment"]
    assert out["commitment_input"] == commitment_input(
        date_iso=DAY.isoformat(),
        events_ruleset=played.events_ruleset,
        clock_rules=2,
        seed=played.market_seed,
        salt_hex=played.seed_salt,
    )
    assert out["clock_rules"] == "v2" and out["review_available"] is True
    assert [r["round_index"] for r in out["rounds"]] == [1, 2, 3, 4]
    for r in out["rounds"]:
        assert set(r["resolve_tts"]) and all(tt > r["hold_tt"] for tt in r["resolve_tts"].values())
    assert out["end_tt"] == played.end_tt


def test_settle_log_has_no_seed_or_salt(played, challenge_play, db, caplog):
    caplog.set_level(logging.DEBUG)
    challenge_play.settle(played)
    assert "challenge settled" in caplog.text
    assert str(played.market_seed) not in caplog.text
    assert played.seed_salt not in caplog.text


def test_entry_result_out_after_settlement(played, challenge_play, db):
    challenge_play.settle(played)
    entry = db.scalars(
        select(ChallengeEntry)
        .where(ChallengeEntry.challenge_id == played.id, ChallengeEntry.eligible.is_(True))
        .order_by(ChallengeEntry.total_score.desc())
    ).first()
    out = views.entry_result_out(entry, played.eligible_count)
    assert out is not None
    assert out["total_score"] == entry.forecast_score + entry.trade_score
    assert out["rank"] == entry.rank and out["eligible_count"] == 3
    assert out["points_awarded"] == entry.points_awarded
    assert set(out) == {
        "final_equity_cents",
        "return_bp",
        "forecast_score",
        "trade_score",
        "total_score",
        "rank",
        "eligible_count",
        "points_awarded",
    }
    row = db.get(Challenge, played.id)
    assert row.status == "settled"
