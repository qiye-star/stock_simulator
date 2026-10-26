"""传导算法：符号/门控/方向/延迟/截断/跳数/环路/多父相加/顺序无关（01 §5.2-§5.3）。"""

import itertools
import random as stdlib_random  # 测试代码允许；纯度守卫只扫 domain/

import pytest

from stocksim.domain.events import SupplyEdge, build_out_edges, propagate
from stocksim.domain.events import constants as c
from stocksim.domain.events.propagation import edge_delay_ticks, edge_scale_ppm

NAMES = ["A", "B", "C", "D", "E"]
PPM = 1_000_000


def _edges():
    return [
        SupplyEdge(0, 1, "supply", -1, 3, 1),  # A→B（上游 A 供下游 B）
        SupplyEdge(2, 0, "demand", 1, 2, 0),  # 下游 A 景气 → 上游 C 订单（传导 A→C）
        SupplyEdge(0, 3, "substitute", -1, 2, 0),  # A↔D
        SupplyEdge(1, 4, "same_theme", 1, 2, 2),  # B↔E
    ]


def _run(edges, source, channel="sentiment", hops=2, **kw):
    out = build_out_edges(len(NAMES), edges)
    return {i.industry: i for i in propagate(out, NAMES, source, channel, hops, **kw)}


@pytest.mark.parametrize("relation", c.RELATIONS)
@pytest.mark.parametrize("channel", c.CHANNELS)
@pytest.mark.parametrize("strength", [1, 2, 3])
def test_edge_scale_covers_every_gate_cell(relation, channel, strength):
    sign = -1 if relation in ("supply", "substitute") else 1
    edge = build_out_edges(2, [SupplyEdge(0, 1, relation, sign, strength, 1)])[
        0 if relation != "demand" else 1
    ][0]
    coef = c.TIER_COEF_PPM[strength]
    expected = sign * coef * c.GATE_PPM[relation][channel] // PPM
    assert edge_scale_ppm(edge, channel) == expected


def test_directions_follow_relation_type():
    from_a = _run(_edges(), 0)
    assert set(from_a) == {"A", "B", "C", "D", "E"}  # A→B(supply) A→C(demand 反向) A→D(替代) B→E
    assert from_a["B"].via_industry == "A" and from_a["B"].relation == "supply"
    assert from_a["C"].via_industry == "A" and from_a["C"].relation == "demand"
    from_b = _run(_edges(), 1)
    assert "A" not in from_b  # supply 不会反向传
    assert "E" in from_b  # same_theme 双向
    from_c = _run(_edges(), 2)
    assert set(from_c) == {"C"}  # demand 边的上游 C 不向下游传
    from_e = _run(_edges(), 4)
    assert "B" in from_e and from_e["B"].relation == "same_theme"
    from_d = _run(_edges(), 3)
    assert "A" in from_d and from_d["A"].scale_ppm < 0  # substitute 双向且为负


def test_signs_multiply_along_path():
    r = _run(_edges(), 0, channel="sentiment", hops=2)
    assert r["B"].scale_ppm < 0 and r["C"].scale_ppm > 0 and r["D"].scale_ppm < 0
    assert r["E"].scale_ppm < 0 and r["E"].hop == 2  # (-)(+) = (-)


def test_delay_ticks_lag_zero_and_lag_n():
    r = _run(_edges(), 0)
    assert r["C"].delay_ticks == c.SAME_DAY_DELAY_TICKS == 3  # lag 0
    assert r["B"].delay_ticks == 20  # lag 1
    assert r["E"].delay_ticks == 20 + 40  # 累计：B(20) + lag 2(40)
    edge = build_out_edges(2, [SupplyEdge(0, 1, "supply", -1, 1, 2)])[0][0]
    assert edge_delay_ticks(edge) == 40


def test_truncates_below_min_scale_and_does_not_propagate_further():
    # supply 的 demand 通道门控 0.3、强度 1 系数 0.25 → |t|=75k < MIN_SCALE_PPM
    edges = [SupplyEdge(0, 1, "supply", -1, 1, 0), SupplyEdge(1, 2, "substitute", -1, 3, 0)]
    r = _run(edges, 0, channel="demand", hops=3)
    assert set(r) == {"A"}
    r = _run(edges, 0, channel="cost", hops=3)  # 门控 1.0：t=250k，能通过
    assert set(r) == {"A", "B", "C"}


def test_hop_limit():
    edges = [SupplyEdge(i, i + 1, "same_theme", 1, 3, 0) for i in range(3)]
    assert set(_run(edges, 0, hops=2)) == {"A", "B", "C"}
    assert set(_run(edges, 0, hops=3)) == {"A", "B", "C", "D"}
    assert set(_run(edges, 0, hops=0)) == {"A"}


def test_cycle_never_revisits_nodes():
    edges = [
        SupplyEdge(0, 1, "same_theme", 1, 3, 0),
        SupplyEdge(1, 2, "same_theme", 1, 3, 0),
        SupplyEdge(2, 0, "same_theme", 1, 3, 0),
    ]
    out = build_out_edges(5, edges)
    result = propagate(out, NAMES, 0, "sentiment", 5)
    assert [i.industry for i in result].count("A") == 1
    assert len({i.industry for i in result}) == len(result)


def test_multiple_parents_add_and_cap_at_node_cap():
    edges = [
        SupplyEdge(0, 1, "same_theme", 1, 3, 0),
        SupplyEdge(0, 2, "same_theme", 1, 3, 0),
        SupplyEdge(1, 3, "same_theme", 1, 3, 0),
        SupplyEdge(2, 3, "same_theme", 1, 3, 0),
    ]
    r = _run(edges, 0, channel="sentiment", hops=2)
    assert r["B"].scale_ppm == r["C"].scale_ppm == 700_000
    assert r["D"].scale_ppm == c.NODE_CAP_PPM  # 490k + 490k = 980k → 截断到 800k
    # 单父时不截断
    r2 = _run(edges[:3], 0, channel="sentiment", hops=2)
    assert r2["D"].scale_ppm == 490_000


def test_edge_order_does_not_change_result():
    edges = [*_edges(), SupplyEdge(3, 4, "same_theme", 1, 2, 1)]
    base = _run(edges, 0)
    rnd = stdlib_random.Random(5)
    for _ in range(10):
        shuffled = edges[:]
        rnd.shuffle(shuffled)
        assert _run(shuffled, 0) == base
    for perm in itertools.islice(itertools.permutations(edges), 24):
        assert _run(list(perm), 0) == base


def test_jittered_tiers_do_not_overlap():
    lo, hi = c.SAVE_JITTER_PPM
    ranges = {t: (coef * lo // PPM, coef * hi // PPM) for t, coef in c.TIER_COEF_PPM.items()}
    assert ranges[1][1] < ranges[2][0] and ranges[2][1] < ranges[3][0]


def test_edge_jitter_scales_coefficient():
    edges = [SupplyEdge(0, 1, "same_theme", 1, 3, 0)]
    base = _run(edges, 0, channel="sentiment")["B"].scale_ppm
    jit = _run(edges, 0, channel="sentiment", edge_jitter={(0, 1): 1_100_000})["B"].scale_ppm
    assert jit > base == 700_000


def test_source_amp_scales_result():
    edges = [SupplyEdge(0, 1, "same_theme", 1, 3, 0)]
    r = _run(edges, 0, channel="sentiment", source_amp_ppm=300_000)
    assert r["A"].scale_ppm == 300_000 and r["B"].scale_ppm == 210_000


def test_v2_edge_delays_scale_with_trading_day_length():
    """v2 每交易日 242 tick：同日边 scale(3)=36，lag L 为 242·L（01 §5.2）。"""
    lag0 = build_out_edges(2, [SupplyEdge(0, 1, "supply", -1, 1, 0)])[0][0]
    lag2 = build_out_edges(2, [SupplyEdge(0, 1, "supply", -1, 1, 2)])[0][0]
    assert edge_delay_ticks(lag0, 242) == 36
    assert edge_delay_ticks(lag2, 242) == 484
    assert edge_delay_ticks(lag0) == c.SAME_DAY_DELAY_TICKS == 3  # v1 不变
