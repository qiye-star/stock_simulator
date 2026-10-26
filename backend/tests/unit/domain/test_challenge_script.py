"""剧本贪心挑回合（03 §4.2）：接受/拒绝规则与 holdable 排除。"""

from stocksim.domain.challenge.script import MajorRef, holdable_v2, plan_rounds

PARAMS = dict(rounds=4, warmup=121, min_gap=121, max_burst=726, max_tt=1936, holdable=holdable_v2)


def m(eid, trig, resolve=None):
    return MajorRef(
        event_id=eid, kind="industry", trigger_tt=trig, resolve_tt=resolve or trig + 400
    )


def test_accepts_clean_plan():
    majors = [m("e1", 200), m("e2", 500), m("e3", 800), m("e4", 1100, 1500)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None
    assert plan.event_ids == ("e1", "e2", "e3", "e4")
    assert plan.hold_tts == (200, 500, 800, 1100)
    assert plan.resolve_tts == (600, 900, 1200, 1500)
    assert plan.end_tt == 1500


def test_greedy_skips_candidates_closer_than_min_gap():
    majors = [m("a", 130), m("b", 150), m("c", 300), m("d", 500), m("e", 700)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None
    assert plan.hold_tts == (130, 300, 500, 700)


def test_gap_boundary_is_inclusive():
    majors = [m("a", 200), m("b", 321), m("c", 500), m("d", 700)]  # 321 - 200 == 121
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None and plan.hold_tts[1] == 321


def test_non_round_majors_are_allowed_between_rounds():
    majors = [m("a", 130), m("x", 200), m("b", 260), m("c", 500), m("d", 700), m("y", 900)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None
    assert "x" not in plan.event_ids and "y" not in plan.event_ids
    assert plan.event_ids == ("a", "b", "c", "d")


def test_warmup_excludes_early_candidates():
    majors = [m("early", 100), m("a", 130), m("b", 300), m("c", 500), m("d", 700)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None and plan.event_ids[0] == "a"


def test_same_tick_duplicates_are_excluded():
    majors = [m("p", 400), m("q", 400), m("a", 130), m("b", 300), m("c", 500), m("d", 700)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None and "p" not in plan.event_ids and "q" not in plan.event_ids


def test_order_blackout_ticks_are_not_holdable():
    # 偏移 120（11:30）与 241（15:00）的候选被跳过；363 = 242 + 121 为首个可停顿点
    majors = [m("a", 120), m("b", 241), m("c", 363), m("d", 600), m("e", 850), m("f", 1100)]
    plan = plan_rounds(majors, **PARAMS)
    assert plan is not None
    assert plan.event_ids == ("c", "d", "e", "f")
    assert plan.hold_tts == (363, 600, 850, 1100)
    assert all(holdable_v2(h) for h in plan.hold_tts)


def test_rejects_when_not_enough_rounds():
    assert plan_rounds([m("a", 200), m("b", 500)], **PARAMS) is None


def test_rejects_first_round_beyond_burst():
    assert plan_rounds([m("late", 900), m("b", 1100), m("c", 1300), m("d", 1500)], **PARAMS) is None


def test_rejects_resolve_not_after_hold():
    majors = [m("a", 200, 200), m("b", 500), m("c", 800), m("d", 1100)]
    assert plan_rounds(majors, **PARAMS) is None


def test_rejects_final_burst_too_long_and_max_tt():
    # 最后一个停顿 1100，end 1100+726+1 超出单段上限
    majors = [m("a", 200), m("b", 500), m("c", 800), m("d", 1100, 1100 + 727)]
    assert plan_rounds(majors, **PARAMS) is None
    majors = [m("a", 200), m("b", 500), m("c", 800), m("d", 1500, 1936 + 1)]
    assert plan_rounds(majors, **PARAMS) is None


def test_rounds_one_returns_single_round_plan():
    plan = plan_rounds([m("a", 200, 300)], **{**PARAMS, "rounds": 1})
    assert plan is not None and plan.end_tt == 300 and plan.event_ids == ("a",)
