"""事件生成：确定性、频率、ID、传闻辟谣率、priced_in 比例、文案可渲染（01 §4、§12.1）。"""

import re
from collections import Counter

from stocksim.domain.events import constants as c
from stocksim.domain.events import (
    day_slots,
    generate_day,
    major_days,
    minor_count,
    render_news_title,
    save_params,
)

SEED = 2024
EVENT_ID_RE = re.compile(r"^e\d{1,9}-\d{1,2}$")
_CACHE = {}


def _events(ruleset, params, seed, days):
    key = (id(ruleset), seed, days)
    if key not in _CACHE:
        _CACHE[key] = [e for d in range(days) for e in generate_day(seed, d, ruleset, params)]
    return _CACHE[key]


def test_generation_is_deterministic_and_seed_sensitive(event_ruleset, event_params):
    a = generate_day(SEED, 7, event_ruleset, event_params)
    b = generate_day(SEED, 7, event_ruleset, event_params)
    assert a == b and len(a) >= 2
    other = generate_day(SEED + 1, 7, event_ruleset, save_params(SEED + 1, event_ruleset))
    assert other != a


def test_major_periods_have_one_or_two_events_on_different_days():
    periods = 100  # 1200 个交易日
    twos = 0
    for p in range(periods):
        days = major_days(SEED, p)
        assert len(days) in (1, 2)
        assert all(12 * p <= d < 12 * p + 12 for d in days)
        if len(days) == 2:
            twos += 1
            assert days[0] != days[1]
    assert 0.30 <= twos / periods <= 0.50


def test_period_boundary_depends_only_on_trading_day():
    # d = 12p-1 与 d = 12p 分别归属相邻周期（只用 trading_day 即可算出，不依赖时钟）
    for p in range(1, 30):
        assert all(d < 12 * p for d in major_days(SEED, p - 1))
        assert all(d >= 12 * p for d in major_days(SEED, p))


def test_slots_major_only_on_assigned_days_and_minor_counts(event_ruleset, event_params):
    for d in range(1200):
        slots = day_slots(SEED, d)
        majors = [s for s, is_major in slots if is_major]
        minors = [s for s, is_major in slots if not is_major]
        assigned = major_days(SEED, d // 12)
        assert majors == [i for i, day in enumerate(assigned) if day == d]
        assert all(s in (0, 1) for s in majors)
        assert 2 <= minor_count(SEED, d) <= 5 and len(minors) == minor_count(SEED, d)
        assert minors == list(range(2, 2 + len(minors)))
    events = generate_day(SEED, 0, event_ruleset, event_params)
    assert [e.slot for e in events] == [s for s, _ in day_slots(SEED, 0)]


def test_ids_offsets_and_day_zero(event_ruleset, event_params):
    for e in _events(event_ruleset, event_params, SEED, 300):
        assert EVENT_ID_RE.match(e.event_id)
        assert e.event_id == f"e{e.trading_day}-{e.slot}"
        assert (e.slot < 2) == e.major
        assert 20 * e.trading_day <= e.publish_trading_tick < 20 * e.trading_day + 20
        assert e.first_seen_trading_tick >= (1 if e.trading_day == 0 else 0)
    for e in generate_day(SEED, 0, event_ruleset, event_params):
        assert e.publish_trading_tick >= 1 and e.first_seen_trading_tick >= 1


def test_rumor_denial_rate_is_about_thirty_percent(event_ruleset, event_params):
    events = _events(event_ruleset, event_params, SEED, 3600)
    rumors = [e for e in events if e.rumor is not None]
    assert len(rumors) >= 2000
    denied = sum(1 for e in rumors if not e.rumor.truth)
    assert 0.27 <= denied / len(rumors) <= 0.33
    for e in rumors[:200]:
        stages = [n.stage for n in e.news]
        assert stages == ["publish", "confirm" if e.rumor.truth else "deny"]
        assert e.news[1].trading_tick == e.rumor.resolve_trading_tick > e.publish_trading_tick


def test_priced_in_share_among_eligible_templates(event_ruleset, event_params):
    events = _events(event_ruleset, event_params, SEED, 3600)
    eligible = [
        e
        for e in events
        if event_ruleset.template_index[e.template_id].can_price_in and e.trading_day >= 3
    ]
    assert len(eligible) > 500
    share = sum(1 for e in eligible if e.expectation == "priced_in") / len(eligible)
    assert 0.15 <= share <= 0.25
    for e in eligible:
        if e.expectation == "priced_in":
            assert [n.stage for n in e.news] == ["precursor", "publish"]
            assert 20 <= e.publish_trading_tick - e.news[0].trading_tick <= 40


def test_same_day_events_rarely_share_source_industry(event_ruleset, event_params):
    clashes = days = 0
    for d in range(1200):
        sources = [
            e.source_industry
            for e in generate_day(SEED, d, event_ruleset, event_params)
            if e.source_industry
        ]
        days += 1
        clashes += len(sources) - len(set(sources))
    assert clashes / days < 0.05  # 重抽 4 次后基本不会重复


def test_every_kind_subtype_and_scope_appears(event_ruleset, event_params):
    events = _events(event_ruleset, event_params, SEED, 1200)
    assert {e.kind for e in events} == set(c.KINDS)
    assert {e.subtype for e in events if e.kind == "announcement"} == {
        t.subtype for t in event_ruleset.templates if t.kind == "announcement"
    }
    assert len({e.subtype for e in events if e.subtype}) == 13
    assert {e.scope for e in events} == {"stock", "industry", "market"}
    majors = Counter(e.kind for e in events if e.major)
    assert set(majors) == set(c.KINDS)


def test_event_fields_are_consistent(event_ruleset, event_params):
    for e in _events(event_ruleset, event_params, SEED, 600):
        tmpl = event_ruleset.template_index[e.template_id]
        assert e.sentiment in (1, -1) and (e.magnitude_ppm > 0) == (e.sentiment > 0)
        assert (e.scope == "stock") == (e.source_code is not None)
        assert (e.scope == "market") == (e.source_industry is None)
        if tmpl.industries is not None and e.source_industry:
            assert e.source_industry in tmpl.industries
        if e.source_code:
            stock = event_ruleset.stocks[event_ruleset.stock_index[e.source_code]]
            assert event_ruleset.industries[stock.industry] == e.source_industry
        hi = (c.MAJOR_MAG_PPM[e.scope] if e.major else c.MINOR_MAG_PPM)[1]
        assert abs(e.magnitude_ppm) <= hi
        assert e.impacts or (e.scope == "market" and not tmpl.tilts)
        if e.scope != "market":
            assert e.impacts[0].hop == 0 and e.impacts[0].industry == e.source_industry


def test_all_news_titles_render_in_both_languages(event_ruleset, event_params):
    for e in _events(event_ruleset, event_params, SEED, 400):
        for item in e.news:
            zh = render_news_title(event_ruleset, e, item, "zh-CN")
            en = render_news_title(event_ruleset, e, item, "en-US")  # en-US 缺失退回 zh-CN
            assert zh and "{" not in zh and en == zh


def test_deny_news_flips_sentiment(event_ruleset, event_params):
    for e in _events(event_ruleset, event_params, SEED, 600):
        if e.rumor and not e.rumor.truth:
            assert e.news[-1].sentiment == -e.sentiment
        elif e.rumor:
            assert e.news[-1].sentiment == e.sentiment


# ------------------------------------------------ 时钟 v2（每交易日 242 tick，01 §4.2–§4.3）


def test_v2_every_trading_day_has_one_or_two_major_events(event_ruleset_v2, event_params):
    """v2 周期为 1 日：每个交易日都有 slot 0 的重大事件，约 40% 的日子另有 slot 1。"""
    counts = []
    for day in range(300):
        majors = [e for e in generate_day(SEED, day, event_ruleset_v2, event_params) if e.major]
        assert 1 <= len(majors) <= 2, day
        counts.append(len(majors))
    two_share = counts.count(2) / len(counts)
    assert 0.30 <= two_share <= 0.50, two_share


def test_v2_same_day_majors_publish_at_different_ticks(event_ruleset_v2, event_params):
    for day in range(300):
        majors = [e for e in generate_day(SEED, day, event_ruleset_v2, event_params) if e.major]
        ticks = [e.publish_trading_tick for e in majors]
        assert len(ticks) == len(set(ticks)), day


def test_v2_publish_offsets_avoid_closing_auction_and_lunch_ticks(event_ruleset_v2, event_params):
    """11:30（偏移 120）与 15:00（偏移 241）两个不接单的 tick 不作为正式发布时刻（01 §4.2）。"""
    tpd = event_ruleset_v2.ticks_per_day
    for day in range(200):
        for e in generate_day(SEED, day, event_ruleset_v2, event_params):
            offset = e.publish_trading_tick - tpd * day
            assert offset not in (120, 241), (day, e.event_id)
            assert offset >= (1 if day == 0 else 0)
            if e.major:
                assert offset <= 230, (day, e.event_id)
            else:
                assert offset <= 239, (day, e.event_id)


def test_v2_minor_count_and_id_format(event_ruleset_v2, event_params):
    for day in range(60):
        slots = day_slots(SEED, day, event_ruleset_v2.ticks_per_day)
        minors = [s for s, major in slots if not major]
        assert 2 <= len(minors) <= 5
        for e in generate_day(SEED, day, event_ruleset_v2, event_params):
            assert EVENT_ID_RE.match(e.event_id) and e.event_id == f"e{day}-{e.slot}"


def test_v2_major_source_industries_differ_within_a_day(event_ruleset_v2, event_params):
    for day in range(300):
        majors = [e for e in generate_day(SEED, day, event_ruleset_v2, event_params) if e.major]
        if len(majors) == 2:
            a, b = (m.source_industry for m in majors)
            if a is not None and b is not None:
                assert a != b, day
