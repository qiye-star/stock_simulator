"""挑战计分与排名（03 §8.1–§8.4）：同伴分、交易同伴差、竞赛排名、奖励表、ISO 周。"""

from datetime import date

from stocksim.domain.challenge.constants import TRADE_SCORE_CAP
from stocksim.domain.challenge.ranking import (
    competition_ranks,
    iso_week_key,
    reward_points,
    top_share_cutoff,
)
from stocksim.domain.challenge.scoring import question_results, trade_scores


def test_question_results_peer_when_enough_eligible():
    S = [60, 40, 20, 80, 50]
    U = [30] * 5
    res = question_results(S, U, [True] * 5, peer_min=5)
    assert all(r.used == "peer" for r in res)
    peers = [r.peer for r in res]
    assert peers == [round_div(5 * s - sum(S), 4) for s in S]
    assert abs(sum(peers)) <= 5  # 同伴分合计约为 0
    assert all(r.score == r.peer for r in res)


def round_div(num, den):
    return (2 * num + den) // (2 * den) if num >= 0 else -((2 * -num + den) // (2 * den))


def test_question_results_baseline_fallback_below_min():
    S = [60, 40, 20, 80]
    U = [30] * 4
    res = question_results(S, U, [True] * 4, peer_min=5)
    assert all(r.used == "baseline" and r.peer is None for r in res)
    assert [r.score for r in res] == [r.baseline for r in res]


def test_ineligible_do_not_affect_reference_and_get_baseline():
    S = [60, 40, 20, 80, 50, 99, -100]
    U = [30] * 7
    elig = [True, True, True, True, True, False, False]
    res = question_results(S, U, elig, peer_min=5)
    base = question_results(S[:5], U[:5], [True] * 5, peer_min=5)
    assert [r.peer for r in res[:5]] == [r.peer for r in base]
    for i in (5, 6):
        assert res[i].used == "baseline" and res[i].score == res[i].baseline


def test_question_results_length_mismatch():
    import pytest

    with pytest.raises(ValueError):
        question_results([1, 2], [1], [True, True])


def test_trade_scores_peer_difference_formula():
    returns = [500, 0, 0, 0, 0]
    elig = [True] * 5
    out = trade_scores(returns, elig, peer_min=5)
    # own 500：others 均值 0，diff 500，500·10/100 = 50
    assert out[0] == 50
    # 其它人：others 均值 125，diff −125，−125·10/100 = −12.5 → −13（半远离零）
    assert out[1:] == [-13, -13, -13, -13]


def test_trade_scores_capped():
    out = trade_scores([100000, 0, 0, 0, 0], [True] * 5, peer_min=5)
    assert out[0] == TRADE_SCORE_CAP
    out = trade_scores([-100000, 0, 0, 0, 0], [True] * 5, peer_min=5)
    assert out[0] == -TRADE_SCORE_CAP


def test_trade_scores_fallback_uses_raw_return_and_ineligible_zero():
    out = trade_scores([300, -100, 999], [True, True, False], peer_min=5)
    assert out == [30, -10, 0]


def test_competition_ranks_standard():
    assert competition_ranks([10, 9, 9, 5]) == [1, 2, 2, 4]
    assert competition_ranks([7, 7, 7]) == [1, 1, 1]
    assert competition_ranks([]) == []


def test_top_share_cutoff_ceiling():
    assert top_share_cutoff(10) == 1
    assert top_share_cutoff(11) == 2
    assert top_share_cutoff(20) == 2
    assert top_share_cutoff(21) == 3


def test_reward_table():
    assert reward_points(None, 50) == 0  # 不发奖
    assert reward_points(1, 4) == 50  # 人数不足 5：只有参与分
    assert reward_points(1, 5) == 50 + 300  # 前三，未达前 10% 门槛
    assert reward_points(1, 10) == 50 + 100 + 300  # 每日最多约 450
    assert reward_points(2, 10) == 50 + 200  # 前 10% 的 cutoff 为 1
    assert reward_points(2, 20) == 50 + 100 + 200
    assert reward_points(3, 20) == 50 + 100  # 第 3 名不在前 10%（cutoff 2）
    assert reward_points(3, 25) == 50 + 100 + 100  # cutoff 3
    assert reward_points(4, 100) == 50 + 100  # cutoff 10，第 4 名仅前 10%
    assert reward_points(11, 100) == 50


def test_iso_week_key_year_boundaries():
    assert iso_week_key(date(2026, 12, 31)) == "2026-W53"
    assert iso_week_key(date(2027, 1, 4)) == "2027-W01"
    assert iso_week_key(date(2026, 10, 26)) == "2026-W44"
