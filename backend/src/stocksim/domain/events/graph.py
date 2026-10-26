"""传导图：把行业级边展开成有向传导边，以及按存档抖动的参数（01 §5.2、§6.2）。

方向与符号完全沿用 01a 草稿定义：supply 只 from→to；demand 只 to→from；
substitute / same_theme 双向。sign = 源行业受正面冲击时目标行业的方向。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..money import round_half_up_div
from ..rng import rand_below
from .constants import (
    EVENT_SAVE_TICK,
    RELATIONS,
    SAVE_EDGE_IDX_BASE,
    SAVE_JITTER_ENABLED,
    SAVE_JITTER_PPM,
)
from .types import EventRuleset, SaveParams, SupplyEdge, TransmissionEdge

_RELATION_CODE = {name: i for i, name in enumerate(RELATIONS)}


def build_out_edges(
    n_nodes: int, edges: Sequence[SupplyEdge]
) -> tuple[tuple[TransmissionEdge, ...], ...]:
    """按关系类型展开，每个节点的出边按 (目标下标, 关系代码) 升序，与输入顺序无关。"""
    buckets: list[list[TransmissionEdge]] = [[] for _ in range(n_nodes)]
    for e in edges:
        key = (e.from_idx, e.to_idx)

        def make(src: int, dst: int, e: SupplyEdge = e, key: tuple[int, int] = key) -> None:
            buckets[src].append(
                TransmissionEdge(src, dst, e.relation, e.sign, e.strength, e.lag_days, key)
            )

        if e.relation == "supply":
            make(e.from_idx, e.to_idx)
        elif e.relation == "demand":
            make(e.to_idx, e.from_idx)
        elif e.relation in ("substitute", "same_theme"):
            make(e.from_idx, e.to_idx)
            make(e.to_idx, e.from_idx)
        else:
            raise ValueError(f"unknown relation: {e.relation}")
    return tuple(
        tuple(sorted(b, key=lambda t: (t.dst, _RELATION_CODE[t.relation]))) for b in buckets
    )


def build_transmission(ruleset: EventRuleset) -> tuple[tuple[TransmissionEdge, ...], ...]:
    """规则集的传导图（出边表）。ruleset.out_edges 已预先计算，此处保持计划中的 API。"""
    return build_out_edges(len(ruleset.industries), ruleset.edges)


def _jitter(seed: int, idx: int, k: int) -> int:
    if not SAVE_JITTER_ENABLED:
        return 1_000_000
    lo, hi = SAVE_JITTER_PPM
    return lo + rand_below(seed, EVENT_SAVE_TICK, idx, k, hi - lo + 1)


def save_params(seed: int, ruleset: EventRuleset) -> SaveParams:
    """存档级抖动：股票 β（idx=stock_idx, k=0）与边系数（idx=1000+from_idx, k=to_idx）。

    边以 (from_idx, to_idx) 定位，不依赖边在数组中的位置，增删其它边不影响已有边。
    """
    beta = tuple(_jitter(seed, s.idx, 0) for s in ruleset.stocks)
    edge = {
        (e.from_idx, e.to_idx): _jitter(seed, SAVE_EDGE_IDX_BASE + e.from_idx, e.to_idx)
        for e in ruleset.edges
    }
    return SaveParams(beta_jitter_ppm=beta, edge_jitter_ppm=edge)


def stock_beta_ppm(ruleset: EventRuleset, params: SaveParams, stock_idx: int) -> int:
    """β_s = base_beta（龙头 1.2 / 其他 1.0）× 存档抖动。"""
    info = ruleset.stocks[stock_idx]
    base = ruleset.leader_beta_ppm if info.leader else ruleset.default_beta_ppm
    return round_half_up_div(base * params.beta_jitter_ppm[stock_idx], 1_000_000)
