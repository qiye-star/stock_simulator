"""预测卡出题（02 §4）：档位表、时钟换算、确定性、候选规则、保密白名单与答案校验。"""

import json

import pytest

from stocksim.domain.clock import timebase
from stocksim.domain.errors import DomainError
from stocksim.domain.events.types import GameEvent, NewsItem, NodeImpact, RumorInfo
from stocksim.domain.predictions import (
    BinaryQ,
    BucketQ,
    QuestionContext,
    RankQ,
    Structure,
    bucket_edges_bp,
    build_questions,
    impact_at,
    resolve_rank,
    validate_answers,
)

INDUSTRIES = tuple(f"行业{i:02d}" for i in range(12))
SRC = INDUSTRIES[0]
NEIGH = {
    SRC: frozenset({INDUSTRIES[1], INDUSTRIES[2]}),
    INDUSTRIES[1]: frozenset({SRC, INDUSTRIES[3]}),
    INDUSTRIES[2]: frozenset({SRC}),
    INDUSTRIES[3]: frozenset({INDUSTRIES[1]}),
}


def _structure() -> Structure:
    return Structure(
        industries=INDUSTRIES,
        stock_count={name: 3 for name in INDUSTRIES},
        neighbors={name: NEIGH.get(name, frozenset()) for name in INDUSTRIES},
        stock_total=385,
        stock_names={"600000": "测试股"},
    )


def _event(
    *,
    tt_publish: int,
    day: int = 41,
    scope: str = "industry",
    rumor: bool = False,
    impacts_scale: dict[str, int] | None = None,
) -> GameEvent:
    scales = impacts_scale or {
        SRC: 1_000_000,
        INDUSTRIES[1]: 800_000,
        INDUSTRIES[2]: 600_000,
        INDUSTRIES[3]: 500_000,
        INDUSTRIES[4]: 400_000,
        INDUSTRIES[5]: 300_000,
        INDUSTRIES[6]: 200_000,
        INDUSTRIES[7]: 50_000,  # 低于门槛
    }
    impacts = tuple(
        NodeImpact(
            industry=name,
            hop=0 if name == SRC else 1,
            scale_ppm=scale,
            delay_ticks=0 if name == SRC else 3 + i,
            via_industry=None if name == SRC else SRC,
            relation=None if name == SRC else "supply",
        )
        for i, (name, scale) in enumerate(scales.items())
    )
    return GameEvent(
        event_id=f"e{day}-0",
        trading_day=day,
        slot=0,
        kind="rumor" if rumor else "news",
        subtype=None,
        scope=scope,
        source_industry=SRC,
        source_code="600000" if scope == "stock" else None,
        major=True,
        sentiment=-1,
        channel="cost",
        template_id="t",
        slot_values=(),
        expectation="surprise",
        magnitude_ppm=50_000,
        publish_trading_tick=tt_publish,
        knots=((-1, 0), (0, 500_000), (5, 1_000_000), (300, 1_000_000)),
        rumor=RumorInfo(truth=True, resolve_trading_tick=tt_publish + 30, credibility_ppm=600_000)
        if rumor
        else None,
        impacts=impacts,
        news=(NewsItem("publish", tt_publish, True, -1),),
        source_stock_idx=0 if scope == "stock" else None,
    )


def _ctx(trigger: int, seed: int = 12345, clock_rules: int = 1) -> QuestionContext:
    return QuestionContext(
        seed=seed, trigger_trading_tick=trigger, structure=_structure(), clock_rules=clock_rules
    )


def test_bucket_table_v1_matches_plan():
    assert bucket_edges_bp("industry", 2) == (-950, -320, 320, 950)
    assert bucket_edges_bp("industry", 5) == (-600, -200, 200, 600)
    assert bucket_edges_bp("industry", 16) == (-330, -110, 110, 330)
    assert bucket_edges_bp("stock", 1) == (-1340, -450, 450, 1340)
    assert bucket_edges_bp("market", 385) == (-250, -100, 100, 250)


def test_bucket_table_v2_matches_plan():
    v2 = {"clock_rules": 2}
    assert bucket_edges_bp("industry", 2, **v2) == (-440, -150, 150, 440)
    assert bucket_edges_bp("industry", 5, **v2) == (-320, -110, 110, 320)
    assert bucket_edges_bp("industry", 16, **v2) == (-240, -80, 80, 240)
    assert bucket_edges_bp("stock", 1, **v2) == (-600, -200, 200, 600)
    assert bucket_edges_bp("market", 385, **v2) == (-200, -70, 70, 200)


def test_default_clock_is_v1():
    assert bucket_edges_bp("industry", 5) == bucket_edges_bp("industry", 5, clock_rules=1)


@pytest.mark.parametrize("offset", [0, 1, 120, 121, 241])
def test_v2_window_uses_242_ticks_per_day(offset):
    tb = timebase(2)
    d = 41
    trigger = 242 * d + offset
    qs = build_questions(_event(tt_publish=trigger, day=d), _ctx(trigger, clock_rules=2))
    dir_q = qs[0]
    assert isinstance(dir_q, BucketQ)
    assert (dir_q.from_day, dir_q.to_day) == (d, d + 2)
    assert tb.day_of(trigger) == d


def test_v1_window_uses_20_ticks_per_day():
    trigger = 20 * 41 + 7
    qs = build_questions(_event(tt_publish=trigger), _ctx(trigger))
    assert (qs[0].from_day, qs[0].to_day) == (41, 43)


def test_same_input_is_byte_identical_and_seed_changes_decoys_only():
    trigger = 20 * 41 + 5
    ev = _event(tt_publish=trigger + 2)
    a = build_questions(ev, _ctx(trigger, seed=1))
    b = build_questions(ev, _ctx(trigger, seed=1))
    assert json.dumps([q.to_public() for q in a], sort_keys=True) == json.dumps(
        [q.to_public() for q in b], sort_keys=True
    )
    c = build_questions(ev, _ctx(trigger, seed=987654321))
    ra = next(q for q in a if isinstance(q, RankQ))
    rc = next(q for q in c if isinstance(q, RankQ))
    tr_a = {n for n, v in resolve_rank_truth(ev, ra).items() if v}
    tr_c = {n for n, v in resolve_rank_truth(ev, rc).items() if v}
    assert tr_a == tr_c  # 真受影响集合不随 seed 变化


def resolve_rank_truth(ev, q):
    return resolve_rank(ev, q)


def test_rank_candidates_rules():
    trigger = 20 * 41 + 5
    ev = _event(tt_publish=trigger + 2)
    qs = build_questions(ev, _ctx(trigger))
    rank = next(q for q in qs if isinstance(q, RankQ))
    assert len(rank.candidates) == 8
    assert list(rank.candidates) == sorted(rank.candidates, key=INDUSTRIES.index)
    assert SRC not in rank.candidates and rank.exclude == SRC
    relevance = resolve_rank(ev, rank)
    top3 = sorted((n for n, v in relevance.items() if v), key=lambda n: -relevance[n])
    assert len(top3) == 3
    assert set(top3) <= set(rank.candidates)
    # 前三一定是真受影响的前三（诱饵不取任何真受影响行业）
    affected = [n for n in INDUSTRIES[1:] if impact_at(ev, n, rank.tt_end) >= 100_000]
    assert set(top3) == set(sorted(affected, key=lambda n: -impact_at(ev, n, rank.tt_end))[:3])
    assert [relevance[n] for n in top3] == [3, 2, 1] or sorted(relevance[n] for n in top3) == [
        1,
        2,
        3,
    ]


def test_no_rank_when_fewer_than_three_affected():
    trigger = 20 * 41 + 5
    ev = _event(
        tt_publish=trigger + 2,
        impacts_scale={SRC: 1_000_000, INDUSTRIES[1]: 200_000, INDUSTRIES[2]: 50_000},
    )
    qs = build_questions(ev, _ctx(trigger))
    assert [type(q) for q in qs] == [BucketQ]


def test_market_event_has_no_rank_and_rumor_only_for_rumor():
    trigger = 20 * 41 + 5
    qs = build_questions(_event(tt_publish=trigger + 2, scope="market"), _ctx(trigger))
    assert [type(q) for q in qs] == [BucketQ]
    assert qs[0].target_kind == "market" and qs[0].target is None
    rq = build_questions(_event(tt_publish=trigger + 2, rumor=True), _ctx(trigger))
    assert [type(q) for q in rq] == [BucketQ, RankQ, BinaryQ]


def test_stock_scope_targets_code_with_n_one():
    trigger = 20 * 41 + 5
    qs = build_questions(_event(tt_publish=trigger + 2, scope="stock"), _ctx(trigger))
    assert qs[0].target_kind == "stock" and qs[0].target == "600000"
    assert qs[0].target_name == "测试股"
    assert qs[0].edges_bp == bucket_edges_bp("stock", 1)


def test_public_json_whitelist():
    trigger = 20 * 41 + 5
    qs = build_questions(_event(tt_publish=trigger + 2, rumor=True), _ctx(trigger))
    allowed = {
        "dir": {
            "qid",
            "kind",
            "target_kind",
            "target",
            "target_name",
            "edges_bp",
            "from_day",
            "to_day",
        },
        "rank": {"qid", "kind", "k", "exclude", "candidates", "at_day"},
        "rumor": {"qid", "kind"},
    }
    for q in qs:
        pub = q.to_public()
        assert set(pub) == allowed[pub["qid"]]
        text = json.dumps(pub, ensure_ascii=False)
        for hidden in ("magnitude", "knots", "scale", "delay", "truth", "resolve", "tt_end"):
            assert hidden not in text


def _pub(trigger: int, rumor: bool = True):
    qs = build_questions(_event(tt_publish=trigger + 2, rumor=rumor), _ctx(trigger))
    return [q.to_public() for q in qs]


def test_validate_answers_accepts_complete_answer():
    pub = _pub(20 * 41 + 5)
    answers = {
        "dir": {"probs": [7, 7, 8, 70, 8]},
        "rank": {
            "order": [pub[1]["candidates"][0], pub[1]["candidates"][1], pub[1]["candidates"][2]]
        },
        "rumor": {"probs": [20, 80]},
    }
    validate_answers(pub, answers)


def _expect(pub, answers, field, reason):
    with pytest.raises(DomainError) as exc:
        validate_answers(pub, answers)
    assert exc.value.params == {"field": field, "reason": reason}


def test_validate_answers_rejects_bad_input():
    pub = _pub(20 * 41 + 5)
    cands = pub[1]["candidates"]
    good_rank = {"order": cands[:3]}
    _expect(
        pub,
        {"dir": {"probs": [20, 20, 20, 20, 19]}, "rank": good_rank, "rumor": {"probs": [50, 50]}},
        "answers.dir.probs",
        "sum",
    )
    _expect(
        pub,
        {
            "dir": {"probs": [7, 7, 8, 70, 8]},
            "rank": {"order": [cands[0], cands[0], cands[1]]},
            "rumor": {"probs": [50, 50]},
        },
        "answers.rank.order",
        "duplicate",
    )
    _expect(
        pub,
        {
            "dir": {"probs": [7, 7, 8, 70, 8]},
            "rank": {"order": [pub[1]["exclude"], cands[1], cands[2]]},
            "rumor": {"probs": [50, 50]},
        },
        "answers.rank.order",
        "excluded",
    )
    _expect(
        pub, {"dir": {"probs": [7, 7, 8, 70, 8]}, "rank": good_rank}, "answers.rumor", "missing"
    )
    _expect(
        pub,
        {
            "dir": {"probs": [7, 7, 8, 70, 8]},
            "rank": good_rank,
            "rumor": {"probs": [50, 50]},
            "extra": {"probs": [50, 50]},
        },
        "answers.extra",
        "unexpected",
    )


def test_validate_answers_rejects_missing_dir_and_extra_rumor():
    pub = _pub(20 * 41 + 5, rumor=False)
    cands = pub[1]["candidates"]
    _expect(pub, {"rank": {"order": cands[:3]}}, "answers.dir", "missing")
    _expect(
        pub,
        {
            "dir": {"probs": [7, 7, 8, 70, 8]},
            "rank": {"order": cands[:3]},
            "rumor": {"probs": [50, 50]},
        },
        "answers.rumor",
        "unexpected",
    )
