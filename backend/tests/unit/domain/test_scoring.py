"""计分纯函数（02 §5）：示例值、适当性抽查、边界与异常。"""

import itertools

import pytest

from stocksim.domain.errors import DomainError
from stocksim.domain.scoring import (
    DISCOUNT_PPM,
    argmax_pick,
    baseline_score,
    bucket_of,
    calibration_bins,
    calibration_error_bp,
    expected_random_ndcg_score,
    log_baseline_score,
    log_peer_scores,
    ndcg_at_k_score,
    peer_scores,
    probs_from_pick,
    rps_score,
    uniform_rps_score,
    validate_probs,
)


def test_rps_examples_k5():
    probs = [7, 7, 8, 70, 8]
    assert rps_score(probs, 3) == 98
    assert rps_score(probs, 4) == 77
    assert rps_score(probs, 0) == 45


def test_uniform_rps_k5_and_k2():
    assert [uniform_rps_score(5, o) for o in range(5)] == [70, 85, 90, 85, 70]
    assert uniform_rps_score(2, 0) == 75
    assert uniform_rps_score(2, 1) == 75


def test_rumor_examples_and_perfect_scores():
    assert rps_score([20, 80], 1) == 96
    assert rps_score([20, 80], 0) == 36
    assert rps_score([0, 100], 1) == 100
    assert rps_score([0, 100], 0) == 0


def test_rps_proper_scoring_rule_spot_check():
    """对若干信念分布 q，期望分在 probs=q 附近最大（允许舍入 ≤1）。K=5 用步长 5 的网格。"""
    grid = [p for p in itertools.product(range(0, 101, 5), repeat=4)]
    grid = [(*g, 100 - sum(g)) for g in grid if sum(g) <= 100]
    for q in ([10, 20, 40, 20, 10], [60, 20, 10, 5, 5], [5, 5, 10, 30, 50]):

        def expected(p, q=q):
            return sum(q[o] * rps_score(p, o) for o in range(5)) / 100

        best = max(grid, key=expected)
        assert expected(q) >= expected(best) - 1.0


def test_validate_probs_rejects_bad_input():
    for bad, field_reason in (
        ([50, 50], "length"),
        ([-1, 101, 0, 0, 0], "range"),
        ([20, 20, 20, 20, 19], "sum"),
        ([True, 0, 0, 0, 100], "type"),
    ):
        with pytest.raises(DomainError) as exc:
            validate_probs(bad, 5)
        assert exc.value.params["field"] == "probs"
        assert exc.value.params["reason"] == field_reason


def test_probs_from_pick_examples_and_sum():
    assert probs_from_pick(3, 70, 5) == (7, 7, 8, 70, 8)
    assert probs_from_pick(1, 80, 2) == (20, 80)
    assert probs_from_pick(2, 20, 5) == (20, 20, 20, 20, 20)
    for k in (2, 5):
        for pick in range(k):
            for conf in range(-(-100 // k), 101, 5):
                p = probs_from_pick(pick, conf, k)
                assert sum(p) == 100
                assert argmax_pick(p) == pick or conf == -(-100 // k)


def test_argmax_pick_ties_return_none():
    assert argmax_pick([20, 20, 20, 20, 20]) is None
    assert argmax_pick([7, 7, 8, 70, 8]) == 3


def test_bucket_of_half_open():
    edges = (-600, -200, 200, 600)
    assert bucket_of(-600, edges) == 1
    assert bucket_of(-601, edges) == 0
    assert bucket_of(600, edges) == 4
    assert bucket_of(599, edges) == 3
    assert bucket_of(0, edges) == 2


def test_ndcg_examples():
    rel = {"A": 3, "B": 2, "C": 1}
    assert ndcg_at_k_score(["A", "C", "B"], rel) == 97
    assert ndcg_at_k_score(["B", "A", "X"], rel) == 79
    assert ndcg_at_k_score(["A", "B", "C"], rel) == 100
    assert ndcg_at_k_score(["X", "Y", "Z"], rel) == 0
    assert expected_random_ndcg_score(8, rel) == 31
    assert baseline_score(79, 31) == 70


def test_ndcg_errors():
    with pytest.raises(DomainError):
        ndcg_at_k_score(["A", "A", "B"], {"A": 3, "B": 2})
    with pytest.raises(ValueError):
        ndcg_at_k_score(["A", "B", "C"], {"A": 0, "B": 0, "C": 0})


def test_discount_table_prefix():
    assert DISCOUNT_PPM[:3] == (1_000_000, 630_930, 500_000)


def test_baseline_examples_and_edges():
    assert baseline_score(98, 85) == 87
    assert baseline_score(77, 70) == 23
    assert baseline_score(45, 70) == -36
    assert baseline_score(0, 100) == -100
    assert baseline_score(100, 100) == 0


def test_log_baseline_bounds():
    assert log_baseline_score(100, 5) == 100
    assert log_baseline_score(20, 5) == 0
    assert log_baseline_score(0, 5) == log_baseline_score(1, 5)  # 夹到 [1,100]


def test_peer_scores_examples_and_zero_sum():
    assert peer_scores([80, 60, 40]) == [30, 0, -30]
    assert peer_scores([55]) == [0]
    assert log_peer_scores([70, 40, 10]) == [125, 41, -167]
    vals = [13, 87, 50, 42, 99, 1, 64]
    assert abs(sum(peer_scores(vals))) <= len(vals)
    assert abs(sum(log_peer_scores([10, 30, 55, 90]))) <= 4


def test_calibration_example():
    samples = [(70, True), (70, False), (75, True), (90, True)]
    bins = calibration_bins(samples)
    assert len(bins) == 10
    assert (bins[7].n, bins[7].hits, bins[7].claimed_sum) == (3, 2, 215)
    assert (bins[9].n, bins[9].hits, bins[9].claimed_sum) == (1, 1, 90)
    assert bins[9].hi_pct == 100
    assert calibration_error_bp(bins) == 625
    assert calibration_error_bp(calibration_bins([])) is None
