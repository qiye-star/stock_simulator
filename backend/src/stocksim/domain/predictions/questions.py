"""预测卡出题、真值与答案校验（02 §4）。纯函数，确定性：同 (seed, 事件, 结构) → 逐字节相同的题目。

- 方向题档位只依赖公开的 n、窗口、目标类型与时钟版本，不依赖事件的 M（不泄密）。
- 排序题真值用理论冲击 `impact_at`（不用实际涨跌），诱饵抽样走 §4.4 的预测 RNG 段。
- 传闻题的揭晓 tick 与真值不进入题目 JSON，结算时从 GameEvent 重算。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isqrt
from typing import Any

from ..clock import CLOCK_RULES_V1, timebase
from ..errors import VALIDATION_ERROR, DomainError
from ..events.path import eval_path
from ..events.types import GameEvent
from ..money import round_half_up_div
from ..rng import rand_below
from ..scoring import validate_probs
from .constants import (
    DIRECTION_WINDOW_DAYS,
    EDGE_FLOOR_BP_BY_CLOCK,
    NOISE_IDIO_DAY_BP,
    NOISE_MKT_DAY_BP,
    PREDICTION_TICK_BASE,
    RANK_CANDIDATES,
    RANK_DECOY_WEIGHT,
    RANK_K,
    RANK_MIN_IMPACT_PPM,
    RANK_TRUE_MAX,
    RUMOR_BUCKETS,
)
from .types import BinaryQ, BucketQ, QuestionSpec, RankQ, TargetKind


@dataclass(frozen=True)
class Structure:
    """公开的产业链结构（由 services 从规则集组装并缓存）。行业顺序 = 节点下标。"""

    industries: tuple[str, ...]
    stock_count: Mapping[str, int]  # 行业名 → 主行业成分股数 n
    neighbors: Mapping[str, frozenset[str]]  # 无向邻接（任一方向有边即相邻）
    stock_total: int  # 全市场股票数（市场目标的 n）
    stock_names: Mapping[str, str] = field(default_factory=dict)  # 代码 → 名称


@dataclass(frozen=True)
class QuestionContext:
    seed: int
    trigger_trading_tick: int
    structure: Structure
    window_days: int = DIRECTION_WINDOW_DAYS
    clock_rules: int = CLOCK_RULES_V1


# ---------------------------------------------------------------- 方向题档位（§4.1）


def bucket_edges_bp(
    target_kind: TargetKind,
    n: int,
    window_days: int = DIRECTION_WINDOW_DAYS,
    clock_rules: int = CLOCK_RULES_V1,
) -> tuple[int, int, int, int]:
    """五档的四个边界（bp），左闭右开：(−e2, −e1, e1, e2)。clock_rules=1 时与原式逐位相同。"""
    if n < 1:
        raise ValueError("n must be >= 1")
    idio = NOISE_IDIO_DAY_BP[clock_rules]
    mkt = NOISE_MKT_DAY_BP[clock_rules]
    floor = EDGE_FLOOR_BP_BY_CLOCK[clock_rules][target_kind]
    sigma = isqrt(window_days * (idio * idio * 10_000 + n * mkt * mkt * 10_000) // n) // 100
    e1 = max(round_half_up_div(sigma, 20) * 10, floor[0])
    e2 = max(round_half_up_div(3 * sigma, 20) * 10, floor[1], e1 + 20)
    return (-e2, -e1, e1, e2)


# ---------------------------------------------------------------- 理论冲击（§4.2）


def impact_at(ev: GameEvent, industry: str, trading_tick: int) -> int:
    """|scale_ppm · S(τ−δ)| / 1e6，单位 ppm of M。未出现在传导链中的行业为 0。"""
    for imp in ev.impacts:
        if imp.industry == industry:
            tau = trading_tick - ev.publish_trading_tick - imp.delay_ticks
            shape = eval_path(ev.knots, tau)
            return round_half_up_div(abs(imp.scale_ppm * shape), 1_000_000)
    return 0


def rank_truth(ev: GameEvent, q: RankQ) -> tuple[list[str], dict[str, int]]:
    """真前三（冲击降序，下标升序，且冲击 > 0）与相关度 {候选: 3|2|1|0}。"""
    scored = [(impact_at(ev, c, q.tt_end), pos, c) for pos, c in enumerate(q.candidates)]
    order = sorted(scored, key=lambda t: (-t[0], t[1]))  # candidates 已按行业下标升序，pos 即下标序
    relevance = {c: 0 for c in q.candidates}
    top: list[str] = []
    for i, (value, _, name) in enumerate(order[:RANK_K]):
        if value > 0:
            relevance[name] = RANK_K - i
            top.append(name)
    return top, relevance


def resolve_rank(ev: GameEvent, q: RankQ) -> dict[str, int]:
    """候选 → 相关度（3/2/1/0）。结算时调用。"""
    return rank_truth(ev, q)[1]


# ---------------------------------------------------------------- 出题


def _affected(ev: GameEvent, st: Structure, tt_end: int) -> list[str]:
    """除源行业外、理论冲击 ≥ RANK_MIN_IMPACT_PPM 的行业，按冲击降序、下标升序。"""
    index = {name: i for i, name in enumerate(st.industries)}
    rows = []
    for imp in ev.impacts:
        if imp.industry == ev.source_industry:
            continue
        value = impact_at(ev, imp.industry, tt_end)
        if value >= RANK_MIN_IMPACT_PPM:
            rows.append((-value, index[imp.industry], imp.industry))
    rows.sort()
    return [name for _, _, name in rows]


def _two_hop(st: Structure, src: str) -> set[str]:
    one = set(st.neighbors.get(src, frozenset()))
    two = set(one)
    for name in one:
        two |= set(st.neighbors.get(name, frozenset()))
    two.discard(src)
    return two


def _decoys(ev: GameEvent, ctx: QuestionContext, excluded: set[str], count: int) -> list[str]:
    """不放回加权抽样（§4.4 预测 RNG 段）：结构邻居权重 3，其它 1。"""
    st = ctx.structure
    near = _two_hop(st, ev.source_industry)
    remaining = [name for name in st.industries if name not in excluded]
    chosen: list[str] = []
    tick = PREDICTION_TICK_BASE - ev.trading_day
    for j in range(min(count, len(remaining))):
        weights = [RANK_DECOY_WEIGHT[0] if x in near else RANK_DECOY_WEIGHT[1] for x in remaining]
        total = sum(weights)
        r = rand_below(ctx.seed, tick, ev.slot, j, total)
        acc = 0
        for i, name in enumerate(remaining):
            acc += weights[i]
            if r < acc:
                chosen.append(name)
                remaining.pop(i)
                break
    return chosen


def build_questions(ev: GameEvent, ctx: QuestionContext) -> tuple[QuestionSpec, ...]:
    """出题（顺序固定 dir → rank → rumor）。ev 必须是重大事件（调用方保证）。"""
    tb = timebase(ctx.clock_rules)
    st = ctx.structure
    w = ctx.window_days
    d0 = tb.day_of(ctx.trigger_trading_tick)
    from_day, to_day = d0, d0 + w - 1
    tt_end = tb.first_tt(to_day + 1) - 1
    out: list[QuestionSpec] = []

    if ev.scope == "industry":
        kind: TargetKind = "industry"
        target: str | None = ev.source_industry
        name: str | None = ev.source_industry
        n = st.stock_count[ev.source_industry or ""]
    elif ev.scope == "stock":
        kind, target = "stock", ev.source_code
        name = st.stock_names.get(ev.source_code or "", ev.source_code)
        n = 1
    else:
        kind, target, name = "market", None, None
        n = st.stock_total
    out.append(
        BucketQ(
            target_kind=kind,
            target=target,
            target_name=name,
            edges_bp=bucket_edges_bp(kind, n, w, ctx.clock_rules),
            from_day=from_day,
            to_day=to_day,
        )
    )

    if ev.scope in ("industry", "stock"):
        affected = _affected(ev, st, tt_end)
        if len(affected) >= RANK_K:
            include = affected[:RANK_TRUE_MAX]
            excluded = {ev.source_industry or "", *affected}  # 诱饵不取任何真受影响行业
            decoys = _decoys(ev, ctx, excluded, RANK_CANDIDATES - len(include))
            index = {n_: i for i, n_ in enumerate(st.industries)}
            cands = sorted([*include, *decoys], key=lambda x: index[x])
            out.append(
                RankQ(
                    candidates=tuple(cands),
                    exclude=ev.source_industry or "",
                    at_day=to_day,
                    tt_end=tt_end,
                )
            )

    if ev.rumor is not None:
        out.append(BinaryQ())
    return tuple(out)


# ---------------------------------------------------------------- 答案校验（§10.2 末段）


def _fail(field_name: str, reason: str) -> DomainError:
    return DomainError(VALIDATION_ERROR, {"field": field_name, "reason": reason})


def validate_answers(questions: Sequence[Mapping[str, Any]], answers: Mapping[str, Any]) -> None:
    """questions 为 to_public() 的 JSON；answers 为 {qid: {"probs":[…]} | {"order":[…]}}。

    每道题必须作答，多答的题不允许；bucket/binary 合计 100、长度 = 档数；rank 长度 3、互不相同、
    都在候选内且不等于排除行业。失败抛 DomainError(VALIDATION_ERROR, {field, reason})。
    """
    by_qid = {str(q["qid"]): q for q in questions}
    for qid in answers:
        if qid not in by_qid:
            raise _fail(f"answers.{qid}", "unexpected")
    for qid, q in by_qid.items():
        if qid not in answers:
            raise _fail(f"answers.{qid}", "missing")
        ans = answers[qid]
        if not isinstance(ans, Mapping):
            raise _fail(f"answers.{qid}", "shape")
        if q["kind"] in ("bucket", "binary"):
            if set(ans) != {"probs"}:
                raise _fail(f"answers.{qid}", "shape")
            probs = ans["probs"]
            if not isinstance(probs, (list, tuple)):
                raise _fail(f"answers.{qid}.probs", "type")
            k = len(q["edges_bp"]) + 1 if q["kind"] == "bucket" else RUMOR_BUCKETS
            try:
                validate_probs(list(probs), k)
            except DomainError as exc:
                raise _fail(f"answers.{qid}.probs", str(exc.params.get("reason"))) from exc
        elif q["kind"] == "rank":
            if set(ans) != {"order"}:
                raise _fail(f"answers.{qid}", "shape")
            order = ans["order"]
            if not isinstance(order, (list, tuple)) or not all(isinstance(x, str) for x in order):
                raise _fail(f"answers.{qid}.order", "type")
            if len(order) != int(q["k"]):
                raise _fail(f"answers.{qid}.order", "length")
            if len(set(order)) != len(order):
                raise _fail(f"answers.{qid}.order", "duplicate")
            cands = set(q["candidates"])
            for name in order:
                if name == q["exclude"]:
                    raise _fail(f"answers.{qid}.order", "excluded")
                if name not in cands:
                    raise _fail(f"answers.{qid}.order", "unknown")
        else:  # pragma: no cover - 未知题型是服务端数据错误
            raise _fail(f"answers.{qid}", "unknown_kind")


__all__ = [
    "QuestionContext",
    "Structure",
    "bucket_edges_bp",
    "build_questions",
    "impact_at",
    "rank_truth",
    "resolve_rank",
    "validate_answers",
]
