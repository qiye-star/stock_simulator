"""预测市场合约生成与结算判定（04 §3.2–§3.4、§11.1）。v2 为主，另取 v1 对照。

手造 GameEvent；只保留 spec 需要的字段，其余（magnitude/knots/expectation/impacts/truth）随意填充，
用来验证 spec 不依赖隐藏字段。
"""

import pytest

from stocksim.domain.events.types import GameEvent, NewsItem, RumorInfo
from stocksim.domain.prediction_market import (
    ContractContext,
    contracts_for_challenge,
    contracts_for_event,
    resolve_bucket,
    resolve_rumor,
)
from stocksim.domain.prediction_market.constants import (
    BUCKET_PRIOR_PPM,
    MAX_MARKETS_PER_CHALLENGE,
    RUMOR_PRIOR_PPM,
)
from stocksim.domain.predictions import Structure

INDUSTRIES = ("有色", "电力", "化工", *(f"行业{i:02d}" for i in range(9)))


def _structure(**overrides) -> Structure:
    counts = {name: 5 for name in INDUSTRIES}
    counts.update(overrides)
    return Structure(
        industries=INDUSTRIES,
        stock_count=counts,
        neighbors={name: frozenset() for name in INDUSTRIES},
        stock_total=385,
    )


def _ctx(clock_rules=2, first=0, last=None, structure=None) -> ContractContext:
    if last is None:
        last = 242 * 8 - 1 if clock_rules == 2 else 20 * 40 - 1
    return ContractContext(
        clock_rules=clock_rules,
        first_tt=first,
        last_tt=last,
        structure=structure or _structure(),
    )


def _event(
    *,
    event_id="e3-0",
    scope="industry",
    industry="有色",
    code=None,
    kind="announcement",
    major=True,
    sentiment=1,
    ticks=(773,),
    stages=None,
    rumor=None,
    trading_day=3,
    expectation="surprise",
    magnitude_ppm=50_000,
    knots=((0, 1_000_000),),
) -> GameEvent:
    stages = stages or ("publish",) * len(ticks)
    news = tuple(
        NewsItem(stage=s, trading_tick=t, major=major, sentiment=sentiment)
        for s, t in zip(stages, ticks, strict=True)
    )
    return GameEvent(
        event_id=event_id,
        trading_day=trading_day,
        slot=0,
        kind=kind,
        subtype=None,
        scope=scope,
        source_industry=industry if scope == "industry" else None,
        source_code=code if scope == "stock" else None,
        major=major,
        sentiment=sentiment,
        channel="demand",
        template_id="t",
        slot_values=(),
        expectation=expectation,
        magnitude_ppm=magnitude_ppm,
        publish_trading_tick=ticks[-1],
        knots=knots,
        rumor=rumor,
        impacts=(),
        news=news,
        source_stock_idx=None,
    )


# ---------------------------------------------------------------- 04 §3.2 的 v2 例子（逐字段）


def test_v2_worked_example_bucket():
    ev = _event(event_id="e3-0", ticks=(773,), trading_day=3)  # 3·242+47 = 773，即 10:17
    specs = contracts_for_event(ev, _ctx(clock_rules=2))
    assert len(specs) == 1
    s = specs[0]
    assert s.kind == "bucket"
    assert s.event_id == "e3-0"
    assert s.scope == "industry" and s.industry == "有色" and s.code is None
    assert (s.from_day, s.to_day) == (3, 5)
    assert s.open_tt == 773
    assert s.close_tt == 242 * 5 == 1210
    assert s.resolve_tt == 242 * 6 == 1452
    assert s.edges_bp == (-320, -110, 110, 320)
    assert s.n_outcomes == 5
    assert s.prior_ppm == BUCKET_PRIOR_PPM[("industry", 1)]
    assert sum(s.prior_ppm) == 1_000_000
    assert s.close_public is True


def test_v1_worked_example_bucket():
    ev = _event(event_id="e37-0", ticks=(745,), trading_day=37)  # 20·37+5
    specs = contracts_for_event(ev, _ctx(clock_rules=1, last=900))
    s = specs[0]
    assert (s.from_day, s.to_day) == (37, 39)
    assert s.open_tt == 745
    assert s.close_tt == 780
    assert s.resolve_tt == 800
    assert s.edges_bp == (-600, -200, 200, 600)


def test_bucket_edges_follow_scope_and_clock():
    ctx2 = _ctx(clock_rules=2)
    stock = contracts_for_event(_event(scope="stock", code="600000", ticks=(773,)), ctx2)[0]
    market = contracts_for_event(_event(scope="market", ticks=(773,)), ctx2)[0]
    assert stock.edges_bp == (-600, -200, 200, 600)  # v2 单股 n=1
    assert stock.code == "600000" and stock.industry is None
    assert market.edges_bp == (-200, -70, 70, 200)  # v2 全市场 n=385
    assert market.industry is None and market.code is None
    assert market.prior_ppm == BUCKET_PRIOR_PPM[("market", 1)]


def test_industry_n_comes_from_structure():
    st = _structure(有色=2)
    s = contracts_for_event(_event(ticks=(773,)), _ctx(structure=st))[0]
    assert s.edges_bp == (-440, -150, 150, 440)  # v2 行业 n=2 表


def test_minor_event_has_no_contract():
    ev = _event(major=False)
    assert contracts_for_event(ev, _ctx()) == ()


def test_event_without_news_has_no_contract():
    ev = _event()
    ev = GameEvent(**{**ev.__dict__, "news": ()})
    assert contracts_for_event(ev, _ctx()) == ()


# ---------------------------------------------------------------- 窗口锚定与 priced_in


def test_window_anchors_to_first_seen_day_not_publish():
    # priced_in：前兆在第 2 日（tick 700），正式发布在第 3 日（tick 773）
    ev = _event(
        expectation="priced_in",
        ticks=(700, 773),
        stages=("precursor", "publish"),
    )
    s = contracts_for_event(ev, _ctx())[0]
    assert s.open_tt == 700
    assert (s.from_day, s.to_day) == (2, 4)  # 700 // 242 = 2
    assert s.close_tt == 242 * 4
    assert s.resolve_tt == 242 * 5


def test_v1_anchors_day_with_20_tick_base():
    ev = _event(ticks=(745,), trading_day=37)
    s = contracts_for_event(ev, _ctx(clock_rules=1, last=900))[0]
    assert s.from_day == 745 // 20 == 37


# ---------------------------------------------------------------- 过滤


def test_bucket_dropped_when_resolve_beyond_challenge():
    ev = _event(ticks=(773,))  # resolve = 1452
    assert contracts_for_event(ev, _ctx(last=1451)) == ()
    assert len(contracts_for_event(ev, _ctx(last=1452))) == 1


def test_first_tt_filter():
    ev = _event(ticks=(773,))
    assert contracts_for_event(ev, _ctx(first=774)) == ()
    assert len(contracts_for_event(ev, _ctx(first=773))) == 1


def test_min_open_filter_v1_and_v2():
    # 传闻：close = min(r, last+1) − lead，open = f；v2 lead=12、MIN=30；v1 lead=1、MIN=10
    rumor_long = RumorInfo(truth=True, resolve_trading_tick=773 + 40, credibility_ppm=500_000)
    ev_v2 = _event(kind="rumor", ticks=(773,), rumor=rumor_long)
    kinds_v2 = [s.kind for s in contracts_for_event(ev_v2, _ctx(clock_rules=2))]
    assert kinds_v2 == ["bucket"]  # rumor close − open = 28 < 30，被过滤
    rumor_ok = RumorInfo(truth=True, resolve_trading_tick=773 + 42, credibility_ppm=500_000)
    ev_v2b = _event(kind="rumor", ticks=(773,), rumor=rumor_ok)
    assert [s.kind for s in contracts_for_event(ev_v2b, _ctx(clock_rules=2))] == ["bucket", "rumor"]
    rumor_v1_ok = RumorInfo(truth=False, resolve_trading_tick=745 + 11, credibility_ppm=1)
    ev_v1 = _event(event_id="e37-0", kind="rumor", ticks=(745,), trading_day=37, rumor=rumor_v1_ok)
    assert [s.kind for s in contracts_for_event(ev_v1, _ctx(clock_rules=1, last=900))] == [
        "bucket",
        "rumor",
    ]


# ---------------------------------------------------------------- 传闻合约


def test_rumor_contract_fields_v2():
    r = RumorInfo(truth=True, resolve_trading_tick=1000, credibility_ppm=500_000)
    ev = _event(kind="rumor", ticks=(773,), rumor=r)
    rumor = next(s for s in contracts_for_event(ev, _ctx()) if s.kind == "rumor")
    assert rumor.open_tt == 773
    assert rumor.resolve_tt == 1000
    assert rumor.close_tt == 1000 - 12
    assert rumor.n_outcomes == 2
    assert rumor.edges_bp == ()
    assert rumor.from_day is None and rumor.to_day is None
    assert rumor.prior_ppm == RUMOR_PRIOR_PPM == (300_000, 700_000)
    assert rumor.close_public is False


def test_rumor_resolve_capped_at_challenge_end():
    r = RumorInfo(truth=False, resolve_trading_tick=10_000, credibility_ppm=1)
    ev = _event(kind="rumor", ticks=(773,), rumor=r)
    ctx = _ctx(last=1500)
    rumor = next(s for s in contracts_for_event(ev, ctx) if s.kind == "rumor")
    assert rumor.resolve_tt == 1501  # min(r, last+1)
    assert rumor.close_tt == 1501 - 12
    # 传闻合约不因揭晓晚于挑战而被过滤；bucket 因 resolve 1452 ≤ 1500 保留
    assert {s.kind for s in contracts_for_event(ev, ctx)} == {"bucket", "rumor"}


def test_rumor_resolve_tick_hidden_in_spec_changes_only_resolve_timing():
    """spec 不含真值：真值翻转时 spec 完全相同。"""
    a = _event(kind="rumor", ticks=(773,), rumor=RumorInfo(True, 1000, 900_000))
    b = _event(kind="rumor", ticks=(773,), rumor=RumorInfo(False, 1000, 900_000))
    assert contracts_for_event(a, _ctx()) == contracts_for_event(b, _ctx())


def test_resolve_rumor_uses_truth():
    yes = _event(kind="rumor", ticks=(773,), rumor=RumorInfo(True, 1000, 1))
    no = _event(kind="rumor", ticks=(773,), rumor=RumorInfo(False, 1000, 1))
    assert resolve_rumor(yes) == 1  # confirm
    assert resolve_rumor(no) == 0  # deny


# ---------------------------------------------------------------- 结算判定与 spec 保密


def test_resolve_bucket_left_closed():
    s = contracts_for_event(_event(ticks=(773,)), _ctx())[0]
    assert resolve_bucket(s, -321) == 0
    assert resolve_bucket(s, -320) == 1  # 等于边界进上一档
    assert resolve_bucket(s, 0) == 2
    assert resolve_bucket(s, 320) == 4
    rumor_ev = _event(ticks=(773,), kind="rumor", rumor=RumorInfo(True, 1000, 1))
    rumor_spec = next(x for x in contracts_for_event(rumor_ev, _ctx()) if x.kind == "rumor")
    with pytest.raises(ValueError):
        resolve_bucket(rumor_spec, 0)


def test_spec_independent_of_hidden_fields():
    base = _event(ticks=(773,), magnitude_ppm=40_000, expectation="surprise")
    alt = _event(
        ticks=(773,),
        magnitude_ppm=-90_000,
        expectation="priced_in",
        knots=((0, 0), (5, 900_000)),
    )
    assert contracts_for_event(base, _ctx()) == contracts_for_event(alt, _ctx())


# ---------------------------------------------------------------- 挑战级：回合过滤、截断、顺序


def test_only_round_events_open_markets():
    ev_round = _event(event_id="e3-0", ticks=(773,))
    ev_other = _event(event_id="e4-1", ticks=(900,), trading_day=4)
    specs = contracts_for_challenge([ev_round, ev_other], _ctx(), round_event_ids={"e3-0"})
    assert [s.event_id for s in specs] == ["e3-0"]


def test_truncation_keeps_earliest_eight_stable_order():
    events = [_event(event_id=f"e{k}-0", ticks=(10 * (k + 1),), trading_day=0) for k in range(10)]
    ids = {e.event_id for e in events}
    ctx = _ctx(last=242 * 8 - 1)
    a = contracts_for_challenge(events, ctx, round_event_ids=ids)
    b = contracts_for_challenge(list(reversed(events)), ctx, round_event_ids=ids)
    assert len(a) == MAX_MARKETS_PER_CHALLENGE == 8
    assert a == b
    assert [s.open_tt for s in a] == [10 * (k + 1) for k in range(8)]


def test_same_first_tick_sorted_by_event_id_then_kind():
    r = RumorInfo(True, 1000, 1)
    ev_b = _event(event_id="e5-1", ticks=(773,), kind="rumor", rumor=r)
    ev_a = _event(event_id="e5-0", ticks=(773,), kind="rumor", rumor=r)
    specs = contracts_for_challenge([ev_b, ev_a], _ctx(), round_event_ids={"e5-0", "e5-1"})
    assert [(s.event_id, s.kind) for s in specs] == [
        ("e5-0", "bucket"),
        ("e5-0", "rumor"),
        ("e5-1", "bucket"),
        ("e5-1", "rumor"),
    ]


# ---------------------------------------------------------------- 真实规则集的行业 n


def test_real_ruleset_industry_n_matches_predictions(event_ruleset_v2):
    from stocksim.domain.predictions import bucket_edges_bp

    rs = event_ruleset_v2
    st = Structure(
        industries=tuple(rs.industries),
        stock_count={name: rs.stock_counts[i] for i, name in enumerate(rs.industries)},
        neighbors={name: frozenset() for name in rs.industries},
        stock_total=len(rs.stocks),
    )
    for i, name in enumerate(rs.industries[:6]):
        ev = _event(industry=name, ticks=(773,))
        s = contracts_for_event(ev, _ctx(structure=st))[0]
        assert s.edges_bp == bucket_edges_bp("industry", rs.stock_counts[i], 3, 2)
