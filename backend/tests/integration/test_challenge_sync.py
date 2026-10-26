"""每日挑战的推进、镜像与报名（C5）：公共时间线、玩家只镜像 master、懒推进与逐步推进等价。

时间由 fake_clock 控制（monkeypatch timeutil.now）；compact 调度下每个回合停顿约 30 秒真实时间。
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.timeline import target_tt
from stocksim.models import (
    Candle,
    ChallengeRound,
    EquitySnapshot,
    MarketState,
    PredictionCard,
    Save,
)
from stocksim.services import market as market_service
from stocksim.services import trading as trading_service
from stocksim.services.challenges import clock, entries, generate, registry, sync
from stocksim.services.challenges.timeutil import to_ms
from stocksim.services.stocks import stock_pool

CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)  # 北京 09:00，compact 整 5 秒对齐
DAY = date(2026, 10, 26)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def start_challenge(db, fake_clock):
    """生成挑战并把时钟拨到开局（第一段快放的起点）。"""
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    fake_clock.value = aware(ch.starts_at)
    return ch


def first_round(db, ch) -> ChallengeRound:
    return registry.rounds_of(db, ch)[0]


def test_master_and_entry_share_v2_clock_and_open_at_570(challenge_app, db, fake_clock, make_user):
    ch = start_challenge(db, fake_clock)
    user = make_user("alice")
    entry, created = entries.join(db, ch, user, fake_clock.value)
    assert created is True
    master = registry.market_save_for(db, ch)
    save = db.get(Save, entry.save_id)
    assert master.clock_rules == 2 and save.clock_rules == 2
    assert master.clock_minute == 570 and save.clock_minute == 570
    assert save.tick == 0 and save.trading_day == 0
    assert save.mode == "challenge" and save.user_id == user.id
    assert save.market_source_id == master.id
    assert save.paused is False  # 开局即第一段快放
    assert db.get(MarketState, save.id) is None  # 玩家存档不持有行情
    assert save.cash_cents == save.initial_fund_cents == 100_000_000
    assert save.market_seed == master.market_seed


def test_two_users_read_identical_market(challenge_app, db, fake_clock, make_user):
    ch = start_challenge(db, fake_clock)
    a_entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
    b_entry, _ = entries.join(db, ch, make_user("bob"), fake_clock.value)
    fake_clock.value = fake_clock.value + timedelta(seconds=25)
    a = db.get(Save, a_entry.save_id)
    b = db.get(Save, b_entry.save_id)
    market_service.advance_to_now(db, a)
    market_service.advance_to_now(db, b)
    overview_a = market_service.market_overview(db, a)
    overview_b = market_service.market_overview(db, b)
    assert overview_a["stocks"] == overview_b["stocks"]
    assert overview_a["tick"] == overview_b["tick"] == a.tick == b.tick
    code = stock_pool()[0].code
    assert market_service.stock_market(db, a, code) == market_service.stock_market(db, b, code)


def test_mirror_follows_master_and_pauses_outside_bursts(challenge_app, db, fake_clock, make_user):
    ch = start_challenge(db, fake_clock)
    entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
    save = db.get(Save, entry.save_id)
    master = registry.market_save_for(db, ch)
    end = aware(ch.ends_at) + timedelta(seconds=1)
    phases: set[str] = set()
    t = fake_clock.value
    while True:
        fake_clock.value = t
        market_service.advance_to_now(db, save)
        phase = clock.phase_at(db, ch, t).phase
        phases.add(phase)
        assert save.tick <= master.tick, "player must never be ahead of master"
        assert save.tick == master.tick
        assert save.paused == (phase not in ("burst", "final"))
        if t >= end:
            break
        t = min(t + timedelta(seconds=7), end)
    assert phases >= {"burst", "hold", "final", "ended"}
    assert market_service.current_trading_tick(db, master) == ch.end_tt
    # 跨交易日时 master 为玩家写收盘快照（03 §7.2），master 自身不写
    assert ch.end_tt > 242
    snapshots = db.scalars(
        select(EquitySnapshot.trading_day).where(EquitySnapshot.save_id == save.id)
    )
    assert len(list(snapshots)) >= 1
    assert db.scalar(select(EquitySnapshot.id).where(EquitySnapshot.save_id == master.id)) is None


def test_hold_window_does_not_advance_the_market(challenge_app, db, fake_clock, make_user):
    ch = start_challenge(db, fake_clock)
    entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
    save = db.get(Save, entry.save_id)
    first = first_round(db, ch)
    fake_clock.value = aware(first.hold_at) + timedelta(seconds=1)
    market_service.advance_to_now(db, save)
    payload_before = dict(db.get(MarketState, save.market_source_id).payload)
    tick_before = save.tick
    fake_clock.value = aware(first.closes_at) - timedelta(seconds=1)
    market_service.advance_to_now(db, save)
    assert save.tick == tick_before
    assert db.get(MarketState, save.market_source_id).payload == payload_before
    assert save.paused is True


def test_rounds_open_and_resolve_and_no_cards_for_challenge(
    challenge_app, db, fake_clock, make_user
):
    ch = start_challenge(db, fake_clock)
    entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
    save = db.get(Save, entry.save_id)
    fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
    market_service.advance_to_now(db, save)
    rows = registry.rounds_of(db, ch)
    for r in rows:
        assert r.opened_at is not None and r.questions
        assert set(r.outcomes) == set(r.resolve_tts)
        assert r.resolved_at is not None
    cards = db.scalars(
        select(PredictionCard).where(PredictionCard.save_id.in_([save.id, save.market_source_id]))
    ).all()
    assert cards == []  # 挑战存档不出预测卡（B 的 CardPolicy）


def _run_to_end(name, app_factory, fake_clock, step_seconds):
    """在独立的库里生成同一挑战并推进到结束。step_seconds=None 表示一次懒推进。"""
    app = app_factory(name)
    session = app.state.session_factory()
    try:
        ch = generate.ensure_challenge(session, DAY, now=CHALLENGE_NOW)
        start = aware(ch.starts_at)
        end = aware(ch.ends_at) + timedelta(seconds=1)
        if step_seconds is not None:
            t = start
            while t < end:
                fake_clock.value = t
                sync.advance_master(session, ch, t)
                t += timedelta(seconds=step_seconds)
        fake_clock.value = end
        sync.advance_master(session, ch, end)
        master = registry.market_save_for(session, ch)
        candles = sorted(
            (
                c.stock_code,
                c.trading_day,
                c.open_cents,
                c.high_cents,
                c.low_cents,
                c.close_cents,
                c.volume,
            )
            for c in session.scalars(select(Candle).where(Candle.save_id == master.id))
        )
        rounds = [
            (r.round_index, r.hold_tt, dict(r.resolve_tts), dict(r.outcomes), r.questions)
            for r in registry.rounds_of(session, ch)
        ]
        return {
            "payload": dict(session.get(MarketState, master.id).payload),
            "candles": candles,
            "rounds": rounds,
            "tick": master.tick,
            "clock_minute": master.clock_minute,
            "trading_day": master.trading_day,
            "cards": session.scalar(
                select(PredictionCard.id).where(PredictionCard.save_id == master.id)
            ),
        }
    finally:
        session.close()


def test_lazy_advance_equals_stepwise_advance(challenge_app_factory, fake_clock):
    stepwise = _run_to_end("stepwise", challenge_app_factory, fake_clock, step_seconds=1)
    lazy = _run_to_end("lazy", challenge_app_factory, fake_clock, step_seconds=None)
    assert lazy["payload"] == stepwise["payload"]
    assert lazy["candles"] == stepwise["candles"]
    assert lazy["rounds"] == stepwise["rounds"]
    assert (lazy["tick"], lazy["clock_minute"], lazy["trading_day"]) == (
        stepwise["tick"],
        stepwise["clock_minute"],
        stepwise["trading_day"],
    )
    assert lazy["cards"] is None and stepwise["cards"] is None
    assert all(outcomes for _, _, _, outcomes, _ in lazy["rounds"])


def test_clock_controls_are_rejected_for_challenge_saves(challenge_app, db, fake_clock, make_user):
    ch = start_challenge(db, fake_clock)
    entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
    save = db.get(Save, entry.save_id)
    calls = (
        lambda: market_service.pause_clock(db, save),
        lambda: market_service.resume_clock(db, save),
        lambda: market_service.skip_clock(db, save),
        lambda: market_service.advance_ticks(db, save, 5),
    )
    for call in calls:
        with pytest.raises(AppError) as exc:
            call()
        assert exc.value.code == ErrorCode.CHALLENGE_UNSUPPORTED
        assert exc.value.params == {"feature": "clock"}


def test_late_joiner_sees_the_same_price_and_joins_at_current_tt(
    challenge_app, db, fake_clock, make_user
):
    ch = start_challenge(db, fake_clock)
    early_entry, _ = entries.join(db, ch, make_user("early"), fake_clock.value)
    first = first_round(db, ch)
    fake_clock.value = aware(first.hold_at) + timedelta(seconds=2)
    late_entry, created = entries.join(db, ch, make_user("late"), fake_clock.value)
    assert created is True
    early = db.get(Save, early_entry.save_id)
    late = db.get(Save, late_entry.save_id)
    market_service.advance_to_now(db, early)
    market_service.advance_to_now(db, late)
    assert (
        market_service.market_overview(db, early)["stocks"]
        == market_service.market_overview(db, late)["stocks"]
    )
    assert late_entry.joined_tt == market_service.current_trading_tick(
        db, registry.market_save_for(db, ch)
    )
    assert late.tick == registry.market_save_for(db, ch).tick


def test_trading_allowed_in_hold_window_and_rejected_after_the_end(
    challenge_app, db, fake_clock, make_user
):
    ch = start_challenge(db, fake_clock)
    user = make_user("alice")
    entry, _ = entries.join(db, ch, user, fake_clock.value)
    save = db.get(Save, entry.save_id)
    first = first_round(db, ch)
    fake_clock.value = aware(first.hold_at) + timedelta(seconds=1)
    code = stock_pool()[0].code
    trade = trading_service.place_order_detailed(
        db, save, user.id, code=code, side="buy", quantity=100, price_type="market"
    ).trade
    assert trade.quantity == 100 and trade.tick == save.tick
    fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
    with pytest.raises(AppError) as exc:
        trading_service.place_order_detailed(
            db, save, user.id, code=code, side="buy", quantity=100, price_type="market"
        )
    assert exc.value.code == ErrorCode.CHALLENGE_ENDED


def test_public_tt_matches_domain_target(challenge_app, db, fake_clock):
    """服务层的 tt 换算与 domain 的 target_tt 一致（不另写公式）。"""
    ch = generate.ensure_challenge(db, DAY, now=fake_clock.value)
    timeline = clock.timeline_of(db, ch)
    t = aware(ch.starts_at) + timedelta(seconds=3)
    assert clock.tt_at(db, ch, t) == target_tt(timeline, to_ms(t))
    assert clock.reached_at(db, ch, 0) == aware(ch.starts_at)


def test_round_hooks_fire_once_per_round_and_question(challenge_app, db, fake_clock, make_user):
    from stocksim.services.challenges import hooks

    opened: list[int] = []
    resolved: list[tuple[int, str]] = []
    hooks.register_round_open_hook(lambda _db, _ch, rnd: opened.append(rnd.round_index))
    hooks.register_question_resolved_hook(
        lambda _db, _ch, rnd, qid: resolved.append((rnd.round_index, qid))
    )
    try:
        ch = start_challenge(db, fake_clock)
        entry, _ = entries.join(db, ch, make_user("alice"), fake_clock.value)
        save = db.get(Save, entry.save_id)
        first = first_round(db, ch)
        fake_clock.value = aware(first.hold_at) + timedelta(seconds=1)
        market_service.advance_to_now(db, save)
        market_service.advance_to_now(db, save)
        assert opened == [1]
        fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
        market_service.advance_to_now(db, save)
        assert opened == [1, 2, 3, 4]
        expected = sorted(
            (r.round_index, q) for r in registry.rounds_of(db, ch) for q in r.resolve_tts
        )
        assert sorted(resolved) == expected
    finally:
        hooks.clear_hooks()
