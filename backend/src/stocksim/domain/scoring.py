"""计分纯函数（02 §1.2、§5）：RPS、NDCG@k、档位、基线分、同伴分、校准表。

约定：整数入、整数出；舍入一律 `money.round_half_up_div`（半远离零）。
概率一律是整数百分比、合计 100。对数只用 `decimal`（精度 34，跨平台一致），不用浮点。
公式与示例见 docs/10.26-plan/02-预测卡.md §5；积分发放在 services/predictions.py。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal

from .errors import VALIDATION_ERROR, DomainError
from .money import round_half_up_div

_CTX = Context(prec=34)
_LN2 = _CTX.ln(Decimal(2))
_LN100 = _CTX.ln(Decimal(100))


def _round_dec(x: Decimal) -> int:
    """Decimal 四舍五入到整数，半远离零（与 round_half_up_div 一致）。"""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _fail(field: str, reason: str) -> DomainError:
    return DomainError(VALIDATION_ERROR, {"field": field, "reason": reason})


# ---------------------------------------------------------------- 概率与档位


def validate_probs(probs: Sequence[int], k: int) -> None:
    """长度 = k ≥ 2，每项为 0..100 的 int（bool 拒绝），合计 100。否则 DomainError。"""
    if k < 2:
        raise ValueError("k must be >= 2")
    if len(probs) != k:
        raise _fail("probs", "length")
    for p in probs:
        if isinstance(p, bool) or not isinstance(p, int):
            raise _fail("probs", "type")
        if not 0 <= p <= 100:
            raise _fail("probs", "range")
    if sum(probs) != 100:
        raise _fail("probs", "sum")


def probs_from_pick(pick: int, conf_pct: int, k: int) -> tuple[int, ...]:
    """“档位 + 把握”→ 分布：pick 档得 conf，其余 100−conf 平分。

    余数按离 pick 近优先、同距下标小优先。

    conf_pct ∈ [ceil(100/k), 100]。(3,70,5) → (7,7,8,70,8)；(1,80,2) → (20,80)；(2,20,5) → 全 20。
    前端 model.js 与手机端 prediction-card.js 实现同一算法。
    """
    if k < 2 or not 0 <= pick < k:
        raise ValueError("bad pick/k")
    lo = -(-100 // k)
    if not lo <= conf_pct <= 100:
        raise ValueError("conf_pct out of range")
    rest = 100 - conf_pct
    others = sorted((j for j in range(k) if j != pick), key=lambda j: (abs(j - pick), j))
    base, rem = divmod(rest, k - 1)
    out = [0] * k
    out[pick] = conf_pct
    for j in others:
        out[j] = base
    for j in others[:rem]:
        out[j] += 1
    return tuple(out)


def argmax_pick(probs: Sequence[int]) -> int | None:
    """唯一最大值的下标；并列最大返回 None。"""
    top = max(probs)
    idx = [i for i, p in enumerate(probs) if p == top]
    return idx[0] if len(idx) == 1 else None


def bucket_of(value_bp: int, edges_bp: Sequence[int]) -> int:
    """左闭右开档位：返回 edges 中 ≤ value 的个数，0..len(edges)。"""
    return sum(1 for e in edges_bp if e <= value_bp)


# ---------------------------------------------------------------- RPS（方向题、传闻题）


def _check_outcome(outcome: int, k: int) -> None:
    if isinstance(outcome, bool) or not isinstance(outcome, int) or not 0 <= outcome < k:
        raise ValueError(f"outcome out of range: {outcome}")


def rps_score(probs: Sequence[int], outcome: int) -> int:
    """0..100 = round(100·(1−RPS))，RPS = 1/(K−1)·Σ_{j<K−1}(F_j−O_j)²。"""
    k = len(probs)
    validate_probs(probs, k)
    _check_outcome(outcome, k)
    s = 0
    cum = 0
    for j in range(k - 1):
        cum += probs[j]
        cum_o = 100 if outcome <= j else 0
        s += (cum - cum_o) ** 2
    return round_half_up_div((k - 1) * 10**6 - 100 * s, (k - 1) * 10**4)


def uniform_rps_score(k: int, outcome: int) -> int:
    """均匀分布在该结果上的 RPS 分（精确有理数后再舍入）。

    K=5 时结果 0..4 → 70/85/90/85/70；K=2 → 75。
    """
    if k < 2:
        raise ValueError("k must be >= 2")
    _check_outcome(outcome, k)
    t = 0
    for j in range(k - 1):
        cum_o = 100 if outcome <= j else 0
        t += ((j + 1) * 100 - cum_o * k) ** 2
    return round_half_up_div((k - 1) * 10**6 * k * k - 100 * t, (k - 1) * 10**4 * k * k)


# ---------------------------------------------------------------- NDCG@k（排序题）


def _discount_ppm(i: int) -> int:
    """折扣 round(10⁶·ln2/ln(i+1))，i ≥ 1。"""
    return _round_dec(Decimal(10**6) * _LN2 / _CTX.ln(Decimal(i + 1)))


DISCOUNT_PPM: tuple[int, ...] = tuple(_discount_ppm(i) for i in range(1, 11))  # i=1..10


def _gain(rel: int) -> int:
    return (1 << rel) - 1


def _ideal_dcg(relevance: Mapping[str, int], k: int) -> int:
    top = sorted(relevance.values(), reverse=True)[:k]
    return sum(_gain(r) * DISCOUNT_PPM[i] for i, r in enumerate(top))


def ndcg_at_k_score(order: Sequence[str], relevance: Mapping[str, int], k: int = 3) -> int:
    """0..100 = round(100·DCG/IDCG)。

    order 中不在 relevance 的项 rel=0；重复项 DomainError；IDCG=0 抛 ValueError。
    """
    if len(set(order)) != len(order):
        raise _fail("order", "duplicate")
    if not 1 <= k <= len(DISCOUNT_PPM):
        raise ValueError("k out of range")
    idcg = _ideal_dcg(relevance, k)
    if idcg <= 0:
        raise ValueError("IDCG is zero: relevance all zero")
    dcg = sum(_gain(relevance.get(c, 0)) * DISCOUNT_PPM[i] for i, c in enumerate(order[:k]))
    return round_half_up_div(100 * dcg, idcg)


def expected_random_ndcg_score(n_candidates: int, relevance: Mapping[str, int], k: int = 3) -> int:
    """随机排序（候选位置边际均匀）的期望 NDCG 分：100·(Σgain/n)·Σdisc / IDCG。"""
    if n_candidates < 1:
        raise ValueError("n_candidates must be >= 1")
    idcg = _ideal_dcg(relevance, k)
    if idcg <= 0:
        raise ValueError("IDCG is zero: relevance all zero")
    sum_gain = sum(_gain(r) for r in relevance.values())
    sum_disc = sum(DISCOUNT_PPM[:k])
    return round_half_up_div(100 * sum_gain * sum_disc, n_candidates * idcg)


# ---------------------------------------------------------------- 基线分（单人反馈）与同伴分


def baseline_score(score: int, uniform_score: int) -> int:
    """相对瞎猜的基线分，−100..100。S ≥ U：100·(S−U)/(100−U)（U=100 时为 0）；否则 100·(S−U)/U。"""
    s, u = score, uniform_score
    if s >= u:
        if u >= 100:
            return 0
        return round_half_up_div(100 * (s - u), 100 - u)
    return round_half_up_div(100 * (s - u), u)


def log_baseline_score(p_outcome_pct: int, k: int) -> int:
    """Metaculus 口径：100·ln(k·p)/ln k，p 为结果的概率（百分比，夹到 [1,100]）。"""
    if k < 2:
        raise ValueError("k must be >= 2")
    p = min(100, max(1, int(p_outcome_pct)))
    num = _CTX.ln(Decimal(k * p) / Decimal(100))
    den = _CTX.ln(Decimal(k))
    return _round_dec(Decimal(100) * num / den)


def peer_scores(scores: Sequence[int]) -> list[int]:
    """同伴分（分数差）：peer_i = S_i − mean_{j≠i} S_j = round(n·S_i − ΣS, n−1)。n=1 返回 [0]。"""
    n = len(scores)
    if n == 0:
        return []
    if n == 1:
        return [0]
    total = sum(scores)
    return [round_half_up_div(n * s - total, n - 1) for s in scores]


# 下标 p=1..100；下标 0 为占位（输入先夹到 [1,100]）
_LOG_TABLE: tuple[int, ...] = (
    0,
    *(_round_dec(Decimal(10**6) * _CTX.ln(Decimal(p) / Decimal(100))) for p in range(1, 101)),
)


def log_peer_scores(p_outcome_pcts: Sequence[int]) -> list[int]:
    """同伴分（Metaculus 对数版本）：L_p = round(10⁶·ln(p/100))，p 夹到 [1,100]。"""
    n = len(p_outcome_pcts)
    if n == 0:
        return []
    if n == 1:
        return [0]
    logs = [_LOG_TABLE[min(100, max(1, int(p)))] for p in p_outcome_pcts]
    total = sum(logs)
    return [round_half_up_div(100 * (n * lp - total), (n - 1) * 10**6) for lp in logs]


# ---------------------------------------------------------------- 校准


@dataclass(frozen=True)
class CalibrationBin:
    lo_pct: int  # [lo, hi)；最后一档 [90, 100]
    hi_pct: int
    n: int
    hits: int
    claimed_sum: int  # 本档声称置信度之和（百分比）


def calibration_bins(samples: Iterable[tuple[int, bool]]) -> tuple[CalibrationBin, ...]:
    """10 档 [0,10)…[80,90)、[90,100]。样本为 (声称置信度 %, 是否命中)。"""
    n = [0] * 10
    hits = [0] * 10
    claimed = [0] * 10
    for pct, hit in samples:
        b = min(int(pct) // 10, 9)
        n[b] += 1
        hits[b] += 1 if hit else 0
        claimed[b] += int(pct)
    return tuple(
        CalibrationBin(
            lo_pct=10 * i,
            hi_pct=100 if i == 9 else 10 * (i + 1),
            n=n[i],
            hits=hits[i],
            claimed_sum=claimed[i],
        )
        for i in range(10)
    )


def calibration_error_bp(bins: Sequence[CalibrationBin]) -> int | None:
    """期望校准误差（bp）= round(100·Σ_b|100·hits_b − claimed_sum_b| / N)；N=0 返回 None。"""
    total = sum(b.n for b in bins)
    if total == 0:
        return None
    err = sum(abs(100 * b.hits - b.claimed_sum) for b in bins)
    return round_half_up_div(100 * err, total)


__all__ = [
    "DISCOUNT_PPM",
    "CalibrationBin",
    "argmax_pick",
    "baseline_score",
    "bucket_of",
    "calibration_bins",
    "calibration_error_bp",
    "expected_random_ndcg_score",
    "log_baseline_score",
    "log_peer_scores",
    "ndcg_at_k_score",
    "peer_scores",
    "probs_from_pick",
    "rps_score",
    "uniform_rps_score",
    "validate_probs",
]
