"""v2 RNG 命名空间无碰撞（07 §4.4）。

线性索引 L = tick*1000003 + idx*7919 + k。两个条目碰撞需 Δtick*1000003 = Δidx*7919 + Δk，
而 |Δidx*7919 + Δk| 不超过事件边索引上限 * 7919 + 131（< 1e7），故 |Δtick| >= 10 不可能碰撞。
因此对“近端”命名空间（交易/init/开局/v2 共同因子，tick ∈ [-2, 12]）穷尽枚举；
日档位（tick = -2^33 - d）与事件命名空间（-2^32 系列）离近端很远，单独枚举后两两检查。
"""

from stocksim.domain.events import constants as ec
from stocksim.domain.market_engine import V2_MARKET_FACTOR_IDX
from stocksim.domain.market_engine import V2_REGIME_TICK_BASE as REGIME_BASE
from stocksim.domain.rng import STOCK_MULT, TICK_MULT

STOCKS = 385
TRADING_KS = (0, 1, 2, *range(100, 120))
INIT_KS = (0, 1, *range(2, 242))
REGIME_KS = (0, 1, 2, 3)
DAY_KS = (*range(0, 17), *range(20, 24), *range(ec.PICK_K_BASE, ec.PICK_K_BASE + ec.MAX_PICKS))


def _lin(tick, idx, k):
    return tick * TICK_MULT + idx * STOCK_MULT + k


def _entries():
    # 近端：交易 tick 1..12（含 v2 共同因子 idx 400）、init、开局
    for tick in range(1, 13):
        for idx in (*range(STOCKS), V2_MARKET_FACTOR_IDX):
            for k in TRADING_KS:
                yield ("trade", tick, idx, k)
    for idx in range(STOCKS):
        for k in INIT_KS:
            yield ("init", -1, idx, k)
    yield ("start", -2, 0, 0)
    # v2 日档位
    for day in range(0, 401):
        for idx in range(STOCKS):
            for k in REGIME_KS:
                yield ("regime", REGIME_BASE - day, idx, k)
    # 01 事件命名空间（与 test_events_rng_layout 同口径）
    for day in range(0, 51):
        for idx in (*range(0, ec.MAX_SLOT + 1), ec.PERIOD_META_IDX, ec.DAY_META_IDX):
            for k in DAY_KS:
                yield ("event-day", ec.EVENT_DAY_TICK_BASE - day, idx, k)
    for idx in range(STOCKS):
        yield ("event-beta", ec.EVENT_SAVE_TICK, idx, 0)
    for from_idx in range(128):
        for to_idx in range(128):
            yield ("event-edge", ec.EVENT_SAVE_TICK, ec.SAVE_EDGE_IDX_BASE + from_idx, to_idx)


def test_no_linear_index_collisions_across_namespaces():
    seen: dict[int, tuple] = {}
    for kind, tick, idx, k in _entries():
        lin = _lin(tick, idx, k)
        other = seen.get(lin)
        assert other is None, f"collision: {(kind, tick, idx, k)} vs {other}"
        seen[lin] = (kind, tick, idx, k)
    assert len(seen) > 800_000  # 近端 + 日档位 + 事件，实测 866k 条


def test_far_tick_bounds():
    """近端窗口的论证前提：同一线性索引跨越 10 个 tick 以上的碰撞不可能。"""
    max_idx = ec.SAVE_EDGE_IDX_BASE + 127
    max_span = max_idx * STOCK_MULT + 131
    assert max_span < 10 * TICK_MULT
    assert REGIME_BASE == -(1 << 33)
    assert ec.EVENT_DAY_TICK_BASE == -(1 << 32)


def test_v2_common_factor_does_not_overlap_stock_indices():
    assert V2_MARKET_FACTOR_IDX == 400
    assert V2_MARKET_FACTOR_IDX - (STOCKS - 1) >= 16
    gap = (V2_MARKET_FACTOR_IDX - (STOCKS - 1)) * STOCK_MULT
    assert max(TRADING_KS) - min(TRADING_KS) < gap
