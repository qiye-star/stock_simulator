"""预测卡 RNG 段无碰撞（02 §4.4）：与 A 的事件段、行情段一起暴力枚举线性索引。"""

from stocksim.domain.events import constants as ec
from stocksim.domain.predictions.constants import PREDICTION_TICK_BASE, RANK_CANDIDATES
from stocksim.domain.rng import STOCK_MULT, TICK_MULT


def _lin(tick, idx, k):
    return tick * TICK_MULT + idx * STOCK_MULT + k


def _entries():
    for tick in range(1, 401):
        for idx in range(385):
            for k in (0, 1, 2, *range(100, 120)):
                yield ("trade", tick, idx, k)
    for idx in range(385):
        for k in (0, 1, *range(2, 242)):
            yield ("init", -1, idx, k)
    yield ("start", -2, 0, 0)
    for day in range(0, 51):
        for idx in (*range(0, ec.MAX_SLOT + 1), ec.PERIOD_META_IDX, ec.DAY_META_IDX):
            for k in (
                *range(0, 17),
                *range(20, 24),
                *range(ec.PICK_K_BASE, ec.PICK_K_BASE + ec.MAX_PICKS),
            ):
                yield ("event-day", ec.EVENT_DAY_TICK_BASE - day, idx, k)
    for idx in range(385):
        yield ("event-save", ec.EVENT_SAVE_TICK, idx, 0)
    for from_idx in range(128):
        for to_idx in range(128):
            yield ("event-edge", ec.EVENT_SAVE_TICK, ec.SAVE_EDGE_IDX_BASE + from_idx, to_idx)
    for day in range(0, 51):  # v2 日档位（见 test_clock_v2_rng_layout.py 的完整段表）
        for idx in range(385):
            for k in range(4):
                yield ("v2-regime", -(1 << 33) - day, idx, k)
    for tick in range(1, 401):
        yield ("v2-market", tick, 400, 0)


def test_prediction_segment_has_no_collision_with_existing_segments():
    seen = {}
    for kind, tick, idx, k in _entries():
        seen.setdefault(_lin(tick, idx, k), (kind, tick, idx, k))
    count = 0
    for day in range(0, 51):
        for slot in (0, 1):
            for j in range(RANK_CANDIDATES):
                entry = ("prediction", PREDICTION_TICK_BASE - day, slot, j)
                lin = _lin(entry[1], entry[2], entry[3])
                assert lin not in seen, f"collision: {entry} vs {seen[lin]}"
                count += 1
    assert count == 51 * 2 * RANK_CANDIDATES


def test_prediction_base_is_below_all_other_bases():
    assert PREDICTION_TICK_BASE < -(1 << 33) - 10_000
    assert PREDICTION_TICK_BASE < ec.EVENT_DAY_TICK_BASE - 10_000
