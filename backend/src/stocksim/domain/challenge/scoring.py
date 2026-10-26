"""挑战计分（03 §8.1、§8.2）：同伴分与交易同伴差。纯函数，整数入出。

题目原始分 S/U 由调用方经 `domain.scoring`（B）算好传入；本模块只负责参考集与同伴化。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..money import round_half_up_div
from ..scoring import baseline_score, peer_scores
from .constants import CHALLENGE_PEER_MIN, TRADE_POINTS_PER_100BP, TRADE_SCORE_CAP


@dataclass(frozen=True)
class QuestionResult:
    raw: int  # 原始分 S（rps_score / ndcg_at_k_score）
    uniform_score: int  # U（uniform_rps_score / expected_random_ndcg_score）
    baseline: int  # baseline_score(S, U)，−100..100
    peer: int | None  # 同伴分；未进参考集或退化为基线时为 None
    score: int  # 最终计分：used=peer 为 peer，否则为 baseline
    used: Literal["peer", "baseline"]


def question_results(
    S_list: Sequence[int],
    U_list: Sequence[int],
    eligible: Sequence[bool],
    *,
    peer_min: int = CHALLENGE_PEER_MIN,
) -> list[QuestionResult]:
    """单题计分。参考集 = 合格作答者；合格人数 ≥ peer_min 时合格者取同伴分，否则全员基线分；
    不合格者一律基线分（不进参考集）。未作答的人不应传入。"""
    n = len(S_list)
    if len(U_list) != n or len(eligible) != n:
        raise ValueError("length mismatch")
    ref = [i for i in range(n) if eligible[i]]
    use_peer = len(ref) >= peer_min
    peers: dict[int, int] = {}
    if use_peer:
        peers = dict(zip(ref, peer_scores([S_list[i] for i in ref]), strict=True))
    out: list[QuestionResult] = []
    for i in range(n):
        base = baseline_score(S_list[i], U_list[i])
        if use_peer and eligible[i]:
            p = peers[i]
            out.append(QuestionResult(S_list[i], U_list[i], base, p, p, "peer"))
        else:
            out.append(QuestionResult(S_list[i], U_list[i], base, None, base, "baseline"))
    return out


def _clamp(value: int, cap: int) -> int:
    return max(-cap, min(cap, value))


def trade_scores(
    returns_bp: Sequence[int],
    eligible: Sequence[bool],
    *,
    peer_min: int = CHALLENGE_PEER_MIN,
) -> list[int]:
    """交易分。参考集 = 全部合格报名（含未交易者，收益 0）。n ≥ peer_min 时用同伴差
    diff = r − mean(others)；否则 diff = r。映射 round(diff·TRADE_POINTS_PER_100BP/100)，
    封顶 ±TRADE_SCORE_CAP。
    不合格者为 0。"""
    if len(returns_bp) != len(eligible):
        raise ValueError("length mismatch")
    ref = [i for i in range(len(returns_bp)) if eligible[i]]
    n = len(ref)
    total = sum(returns_bp[i] for i in ref)
    out = [0] * len(returns_bp)
    for i in ref:
        own = returns_bp[i]
        diff = own
        if n >= peer_min and n > 1:
            diff = own - round_half_up_div(total - own, n - 1)
        pts = round_half_up_div(diff * TRADE_POINTS_PER_100BP, 100)
        out[i] = _clamp(pts, TRADE_SCORE_CAP)
    return out
