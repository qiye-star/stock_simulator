"""RNG 命名空间无碰撞（01 §6.2）：暴力枚举线性索引 L = tick*1000003 + idx*7919 + k。

交易 tick 只枚举 [-2, 400]：不同 tick 间要碰撞需 |Δidx*7919 + Δk| = Δtick*1000003，
而 |Δidx*7919| <= 384*7919 < 3.05*1000003，故 Δtick >= 4 时不可能碰撞，400 已覆盖全部结构。
"""

from stocksim.domain.events import constants as c
from stocksim.domain.rng import STOCK_MULT, TICK_MULT

STOCKS = 385
TRADING_KS = (0, 1, 2, *range(100, 120))
INIT_KS = (0, 1, *range(2, 242))
DAY_KS = (*range(0, 17), *range(20, 24), *range(c.PICK_K_BASE, c.PICK_K_BASE + c.MAX_PICKS))


def _lin(tick, idx, k):
    return tick * TICK_MULT + idx * STOCK_MULT + k


def _entries():
    for tick in range(1, 401):
        for idx in range(STOCKS):
            for k in TRADING_KS:
                yield ("trade", tick, idx, k)
    for idx in range(STOCKS):
        for k in INIT_KS:
            yield ("init", -1, idx, k)
    yield ("start", -2, 0, 0)
    for day in range(0, 51):
        for idx in (*range(0, c.MAX_SLOT + 1), c.PERIOD_META_IDX, c.DAY_META_IDX):
            for k in DAY_KS:
                yield ("day", c.EVENT_DAY_TICK_BASE - day, idx, k)
    for idx in range(STOCKS):
        yield ("save-beta", c.EVENT_SAVE_TICK, idx, 0)
    for from_idx in range(128):
        for to_idx in range(128):
            yield ("save-edge", c.EVENT_SAVE_TICK, c.SAVE_EDGE_IDX_BASE + from_idx, to_idx)


def test_no_linear_index_collisions_across_namespaces():
    seen = {}
    for kind, tick, idx, k in _entries():
        lin = _lin(tick, idx, k)
        other = seen.get(lin)
        assert other is None, f"collision: {(kind, tick, idx, k)} vs {other}"
        seen[lin] = (kind, tick, idx, k)
    assert len(seen) > 3_000_000


def test_k_spans_stay_below_collision_bound():
    # 同一 tick 命名空间内 k 的跨度必须小于 1292（01 §2）
    assert max(DAY_KS) - min(DAY_KS) < 1292
    assert c.PICK_K_BASE + c.MAX_PICKS - 1 == 131
    assert c.SAVE_EDGE_IDX_BASE > STOCKS - 1
