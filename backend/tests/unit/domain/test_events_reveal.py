"""情报提示、传闻状态与事件阶段（01 §1.3、§1.7）。"""

import pytest

from stocksim.domain.events import event_phase, generate_day, rumor_hint, rumor_status

SEED = 2024


@pytest.fixture(scope="module")
def events(event_ruleset, event_params):
    return [e for d in range(0, 1500) for e in generate_day(SEED, d, event_ruleset, event_params)]


def test_rumor_hint_is_about_eighty_percent_accurate(events):
    rumors = [e for e in events if e.rumor]
    assert len(rumors) > 800
    right = sum(1 for e in rumors if (rumor_hint(SEED, e) == "likely_true") == e.rumor.truth)
    assert 0.75 <= right / len(rumors) <= 0.85
    assert rumor_hint(SEED, rumors[0]) == rumor_hint(SEED, rumors[0])


def test_rumor_hint_rejects_non_rumor(events):
    plain = next(e for e in events if e.rumor is None)
    with pytest.raises(ValueError):
        rumor_hint(SEED, plain)


def test_rumor_status_flips_at_resolve_tick(events):
    e = next(e for e in events if e.rumor)
    t = e.rumor.resolve_trading_tick
    assert rumor_status(e, t - 1) == "unresolved"
    assert rumor_status(e, t) == ("confirmed" if e.rumor.truth else "denied")
    assert rumor_status(next(x for x in events if x.rumor is None), t) is None


def test_event_phase_progression(events):
    e = next(x for x in events if x.expectation == "priced_in")
    assert event_phase(e, e.publish_trading_tick - 1) == "expected"
    assert event_phase(e, e.publish_trading_tick) == "active"
    assert event_phase(e, e.lifetime_end_tick - 1) == "active"
    assert event_phase(e, e.lifetime_end_tick) == "settled"
