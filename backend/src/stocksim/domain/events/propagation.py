"""分层传导（01 §5.3）：QuantEcon ``x←A·x`` 的截断版，整数 ppm。

每个节点只在第一次到达的层被计入（简单路径，环路天然截断）；同一层多个父节点的贡献相加后
截断到 ±NODE_CAP_PPM；低于 MIN_SCALE_PPM 或延迟超过 MAX_DELAY_TICKS 的节点丢弃且不再往下传。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..money import round_half_up_div
from .constants import (
    GATE_PPM,
    MAX_DELAY_TICKS,
    MIN_SCALE_PPM,
    NODE_CAP_PPM,
    REFERENCE_TICKS_PER_DAY,
    SAME_DAY_DELAY_TICKS,
    TIER_COEF_PPM,
)
from .timing import scale_ticks
from .types import NodeImpact, TransmissionEdge

PPM = 1_000_000


def edge_scale_ppm(edge: TransmissionEdge, channel: str, jitter_ppm: int = PPM) -> int:
    """单条传导边的有效比例 t = sign × coef × gate（带符号 ppm）。coef 已含存档抖动。"""
    coef = round_half_up_div(TIER_COEF_PPM[edge.strength] * jitter_ppm, PPM)
    return round_half_up_div(edge.sign * coef * GATE_PPM[edge.relation][channel], PPM)


def edge_delay_ticks(edge: TransmissionEdge, ticks_per_day: int = REFERENCE_TICKS_PER_DAY) -> int:
    """lag_days>=1 取 L 个交易日；L=0 取 SAME_DAY_DELAY_TICKS（参考 tick），
    同日传导也能看出先后。"""
    if edge.lag_days >= 1:
        return ticks_per_day * edge.lag_days
    return scale_ticks(SAME_DAY_DELAY_TICKS, ticks_per_day)


def propagate(
    out_edges: Sequence[Sequence[TransmissionEdge]],
    names: Sequence[str],
    source: int,
    channel: str,
    max_hops: int,
    *,
    source_amp_ppm: int = PPM,
    edge_jitter: Mapping[tuple[int, int], int] | None = None,
    ticks_per_day: int = REFERENCE_TICKS_PER_DAY,
) -> tuple[NodeImpact, ...]:
    """从 source 出发传导，返回含源节点（hop=0）的全部影响，按 (hop, 节点下标) 排序。"""
    jitter = edge_jitter or {}
    max_delay = scale_ticks(MAX_DELAY_TICKS, ticks_per_day)
    amp = {source: source_amp_ppm}
    delay = {source: 0}
    hop_of = {source: 0}
    via: dict[int, tuple[int, str] | None] = {source: None}
    frontier = [source]
    for hop in range(1, max_hops + 1):
        total: dict[int, int] = {}
        best: dict[int, tuple[int, int, int, str]] = {}  # v -> (|c|, -delay, u, relation)
        best_delay: dict[int, int] = {}
        for u in sorted(frontier):
            for e in out_edges[u]:
                v = e.dst
                if v in amp:
                    continue
                t = edge_scale_ppm(e, channel, jitter.get(e.key, PPM))
                c = round_half_up_div(amp[u] * t, PPM)
                if c == 0:
                    continue
                d = delay[u] + edge_delay_ticks(e, ticks_per_day)
                total[v] = total.get(v, 0) + c
                cand = (abs(c), -d, u, e.relation)
                if v not in best or cand[:2] > best[v][:2]:
                    best[v] = cand
                    best_delay[v] = d
        frontier = []
        for v in sorted(total):
            s = max(-NODE_CAP_PPM, min(NODE_CAP_PPM, total[v]))
            if abs(s) < MIN_SCALE_PPM or best_delay[v] > max_delay:
                continue
            amp[v] = s
            delay[v] = best_delay[v]
            hop_of[v] = hop
            via[v] = (best[v][2], best[v][3])
            frontier.append(v)
    out: list[NodeImpact] = []
    for v in sorted(amp, key=lambda n: (hop_of[n], n)):
        parent = via[v]
        out.append(
            NodeImpact(
                industry=names[v],
                hop=hop_of[v],
                scale_ppm=amp[v],
                delay_ticks=delay[v],
                via_industry=names[parent[0]] if parent else None,
                relation=parent[1] if parent else None,
            )
        )
    return tuple(out)
