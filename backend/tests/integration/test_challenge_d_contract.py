"""03 §1.7 给 D 的契约函数的边界（C7）：时间换算互逆、参考涨跌幅口径、超前抛错、已知 tick 不超前、
回合事件、ChallengeInfo 字段、预计人数，以及挑战生成/作废时钩子确实被调用。"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from stocksim.domain.challenge.timeline import target_tt
from stocksim.domain.clock import timebase
from stocksim.models import Challenge
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import (
    entries,
    expected_participants,
    generate,
    hooks,
    public_event,
    registry,
    rounds,
    sync,
)
from stocksim.services.challenges.registry import (
    get_challenge,
    knowledge_trading_tick,
    live_challenges,
    public_trading_tick,
    real_time_of,
    reference_change_bp,
    round_event_ids,
)
from stocksim.services.challenges.timeutil import to_ms

DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)
TB = timebase(2)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest.fixture
def running(challenge_app, db, fake_clock, make_user):
    """生成挑战，一人报名，时钟拨到开局（running）。"""
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    user = make_user("dcontract")
    fake_clock.value = aware(ch.starts_at)
    entries.join(db, ch, user, fake_clock.value)
    return ch, user


def test_info_fields_and_clock_rules(running, db, fake_clock):
    ch, _ = running
    info = get_challenge(db, ch.id)
    assert info is not None and info.clock_rules == 2
    assert info.first_tt == 1 and info.last_tt == ch.end_tt
    assert info.status == "live"
    assert info.id == ch.id and info.events_ruleset == ch.events_ruleset
    assert get_challenge(db, uuid.uuid4()) is None
    assert [i.id for i in live_challenges(db, fake_clock.value)] == [ch.id]


def test_public_tick_and_real_time_are_inverse(running, db):
    ch, _ = running
    info = get_challenge(db, ch.id)
    prev = -1
    for tt in range(0, ch.end_tt + 1):
        t = real_time_of(info, tt)
        assert public_trading_tick(info, t) == tt
        assert tt > prev
        prev = tt
        if tt > 0:
            assert public_trading_tick(info, t - timedelta(milliseconds=1)) < tt
    assert real_time_of(info, -5) == aware(ch.starts_at)
    with pytest.raises(ValueError):
        real_time_of(info, ch.end_tt + 1)


def test_public_tick_is_monotone_and_matches_domain(running, db):
    ch, _ = running
    info = get_challenge(db, ch.id)
    values = []
    t = aware(ch.starts_at) - timedelta(seconds=5)
    end = aware(ch.ends_at) + timedelta(seconds=5)
    while t <= end:
        tt = public_trading_tick(info, t)
        assert tt == target_tt(info.timeline, to_ms(t))
        values.append(tt)
        t += timedelta(seconds=1)
    assert values == sorted(values)
    assert values[0] == 0 and values[-1] == ch.end_tt


def _play_to_end(db, fake_clock, ch):
    """把 master 推到终局（用于参考涨跌幅与超前检查）。"""
    fake_clock.value = aware(ch.ends_at) + timedelta(seconds=1)
    sync.advance_master(db, ch, fake_clock.value)
    return registry.market_save_for(db, ch)


def test_reference_change_bp_at_roll_tick_and_current_tick(running, db, fake_clock):
    ch, _ = running
    info = get_challenge(db, ch.id)
    # master 只推到公共 tt（end_tt − 1，非换日 tick），与生产中 master 永不超前一致
    cur = ch.end_tt - 1
    assert cur % TB.ticks_per_day != 0
    fake_clock.value = real_time_of(info, cur)
    assert public_trading_tick(info, fake_clock.value) == cur
    sync.advance_master(db, ch, fake_clock.value)
    master = registry.market_save_for(db, ch)

    # 当前公共 tick：取现价，to_day = day_of(cur)
    assert reference_change_bp(db, ch, "market", None, 1, cur) == (
        predictions_service.change_bp_for(
            db,
            master,
            target_kind="market",
            target=None,
            from_day=1,
            to_day=TB.day_of(cur),
        )
    )
    # 换日 tick（upto = 242·2）：取第 1 日收盘
    roll = TB.ticks_per_day * 2
    assert roll <= cur
    assert reference_change_bp(db, ch, "market", None, 1, roll) == (
        predictions_service.change_bp_for(
            db, master, target_kind="market", target=None, from_day=1, to_day=1
        )
    )
    # 尚未到达的 end_tt 不能取
    with pytest.raises(ValueError):
        reference_change_bp(db, ch, "market", None, 1, ch.end_tt)


def test_reference_change_bp_rejects_future_and_mid_day_ticks(running, db, fake_clock):
    ch, _ = running
    _play_to_end(db, fake_clock, ch)
    cur = ch.end_tt
    with pytest.raises(ValueError):
        reference_change_bp(db, ch, "market", None, 0, cur + 1)
    mid = cur - 1  # 非换日、且不是当前 tick：只有日收盘可取
    assert mid % TB.ticks_per_day != 0
    with pytest.raises(ValueError):
        reference_change_bp(db, ch, "market", None, 0, mid)


def test_knowledge_tick_none_without_entry_and_never_ahead(running, db, fake_clock, make_user):
    ch, user = running
    stranger = make_user("stranger")
    assert knowledge_trading_tick(db, stranger.id, ch) is None
    info = get_challenge(db, ch.id)
    for minutes in (0, 3, 9, 20):
        fake_clock.value = aware(ch.starts_at) + timedelta(minutes=minutes)
        kt = knowledge_trading_tick(db, user.id, ch)
        assert kt is not None and kt <= public_trading_tick(info, fake_clock.value)


def test_round_event_ids_are_n_major_events(running, db):
    ch, _ = running
    ids = round_event_ids(db, ch)
    assert len(ids) == 4 and len(set(ids)) == 4
    master = registry.market_save_for(db, ch)
    for event_id, rnd in zip(ids, registry.rounds_of(db, ch), strict=True):
        assert event_id == rnd.event_id
        assert rounds.event_of(master.market_seed, ch.events_ruleset, event_id).major is True


def test_public_event_future_tick_raises_and_hides_internals(running, db, fake_clock):
    ch, _ = running
    info = get_challenge(db, ch.id)
    cur = public_trading_tick(info, fake_clock.value)
    first = round_event_ids(db, ch)[0]
    with pytest.raises(ValueError):
        public_event(db, ch, first, "zh-CN", cur + 1)
    ev = public_event(db, ch, first, "zh-CN", cur)
    if ev is not None:
        assert ev["event_id"] == first
        text = json.dumps(ev, ensure_ascii=False)
        for hidden in ("magnitude_ppm", "knots", "expectation", "channel"):
            assert hidden not in text


def test_expected_participants_is_max_of_this_and_previous(
    challenge_app, db, fake_clock, make_user
):
    prev = generate.ensure_challenge(db, date(2026, 10, 25), now=CHALLENGE_NOW)
    fake_clock.value = aware(prev.starts_at)
    entries.join(db, prev, make_user("p1"), fake_clock.value)
    entries.join(db, prev, make_user("p2"), fake_clock.value)
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    assert expected_participants(db, ch) == 2  # 本场 0，上一场 2
    fake_clock.value = aware(ch.starts_at)
    for i in range(3):
        entries.join(db, ch, make_user(f"n{i}"), fake_clock.value)
    assert expected_participants(db, ch) == 3  # 本场 3 ≥ 上一场 2


def test_hooks_fire_on_generation_and_on_void(challenge_app, db, fake_clock, monkeypatch):
    created: list[tuple[uuid.UUID, int, bool]] = []
    revoked: list[tuple[str, str]] = []

    def on_created(_db, info):
        created.append((info.id, info.clock_rules, info.timeline is not None))

    def on_revoked(_db, info, reason):
        revoked.append((str(info.id), reason))

    hooks.register_challenge_hooks(on_created, on_revoked)
    try:
        ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
        assert created == [(ch.id, 2, True)]
        generate.void_challenge(db, ch, "manual")
        assert revoked == [(str(ch.id), "manual")]

        monkeypatch.setattr(generate, "_screen", lambda seed: None)
        void = generate.ensure_challenge(db, date(2026, 10, 27), now=CHALLENGE_NOW)
        assert void.status == "void"
        assert revoked[-1] == (str(void.id), "screening_failed")
        assert len(created) == 1  # 作废的挑战不触发 created
    finally:
        hooks.clear_hooks()


def test_live_listing_drops_settled_after_24_hours(challenge_app, db, fake_clock):
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    row = db.get(Challenge, ch.id)
    row.status = "settled"
    row.settled_at = aware(ch.ends_at)
    db.commit()
    assert ch.id in [i.id for i in live_challenges(db, aware(ch.ends_at) + timedelta(hours=1))]
    assert ch.id not in [i.id for i in live_challenges(db, aware(ch.ends_at) + timedelta(hours=25))]
