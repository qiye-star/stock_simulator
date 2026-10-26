from __future__ import annotations

import itertools
import math
import statistics

import pytest

from stocksim.replay_ingest.errors import BuildError
from stocksim.replay_ingest.questions import auto_edges, bucket_of, rank_relevance, return_bp

EDGES = [-400, -100, 100, 400]


@pytest.mark.parametrize(
    ("value", "bucket"),
    [
        (-10_000, 0),
        (-401, 0),
        (-400, 1),
        (-101, 1),
        (-100, 2),
        (0, 2),
        (99, 2),
        (100, 3),
        (399, 3),
        (400, 4),
        (9999, 4),
    ],
)
def test_bucket_of_is_left_closed_right_open(value: int, bucket: int) -> None:
    assert bucket_of(value, EDGES) == bucket


def test_return_bp_rounds_half_away_from_zero() -> None:
    assert return_bp(32, 33) == 313  # 312.5
    assert return_bp(32, 31) == -313
    assert return_bp(3, 4) == 3333
    assert return_bp(100, 100) == 0
    with pytest.raises(BuildError):
        return_bp(0, 1)


def test_auto_edges_matches_independent_calculation() -> None:
    closes = [10000, 10100] * 8
    rets = [(b / a - 1) * 10_000 for a, b in itertools.pairwise(closes)]
    s = statistics.stdev(rets) * math.sqrt(5)

    def r50(x: float) -> int:
        return math.floor(x / 50 + 0.5) * 50

    expected = [-r50(s), -max(50, r50(0.3 * s)), max(50, r50(0.3 * s)), r50(s)]
    assert auto_edges(closes, 5) == expected == [-250, -50, 50, 250]


def test_auto_edges_floor_and_strictly_increasing() -> None:
    flat = [10000] * 5 + [10001] * 5
    e = auto_edges(flat, 1)
    assert e == [-100, -50, 50, 100]  # 最小 ±50，外侧至少比内侧大 50
    wild = auto_edges([10000, 10400, 9800, 10300, 9700, 10500, 9600] * 2, 5)
    assert wild == sorted(set(wild))
    assert all(x % 50 == 0 for x in wild)


def test_auto_edges_needs_enough_history() -> None:
    with pytest.raises(BuildError, match="回看期"):
        auto_edges([100, 101], 5)


def test_rank_relevance_top3_values() -> None:
    rel, ties = rank_relevance({"s1": 100, "s2": 900, "s3": 300, "s4": -20}, 3)
    assert rel == {"s2": 3, "s3": 2, "s1": 1}
    assert ties == []


def test_rank_relevance_tie_break_by_stock_key() -> None:
    rel, ties = rank_relevance({"b": 5, "a": 5, "c": 1, "d": 0}, 3)
    assert rel == {"a": 3, "b": 2, "c": 1}
    assert ties == [("a", "b")]
    rel, ties = rank_relevance({"a": 5, "c": 3, "b": 3, "d": 1}, 2)  # 并列跨越前 k 名边界
    assert rel == {"a": 3, "b": 2}
    assert ties == [("b", "c")]
    _, ties = rank_relevance({"a": 5, "b": 4, "c": 3, "d": 1, "e": 1}, 3)  # 名次外的并列不告警
    assert ties == []


def test_fixture_answers(pack_min: dict) -> None:
    q1, q2 = pack_min["questions"]
    s1 = pack_min["bars"]["s1"]
    lb = pack_min["lookback_days"]
    ret = return_bp(s1[lb][3], s1[lb + 5][3])  # 第 0 日收盘（第 1 日的前收）-> 第 5 日收盘
    assert q1["answer"]["return_bp"] == ret
    assert q1["answer"]["bucket"] == bucket_of(ret, q1["edges_bp"])
    assert q1["resolves"] == {"day": 5, "phase": "close"}
    assert q2["answer"]["relevance"] == {"s2": 3, "s1": 2, "s3": 1}
    assert q2["prompt_masked"] == "券商A、券商B、银行A未来 5 日涨幅排序"  # 自动脱敏
    assert (
        q1["prompt_masked"] == "从昨收到 5 个交易日后收盘，{name} 的涨跌幅？"
    )  # 作者给的占位符保留
