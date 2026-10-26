"""行情引擎金值：在加入事件漂移（drift 参数）之前，用当时的代码采集。

这些 sha256 是行为契约：``advance`` 在不传 drift（或 drift 为 None / 空）时，必须与没有事件功能
时的输出逐位一致。禁止为通过测试而修改下面的常量；只有规范性变更（行情规则本身改变）才可整体更新。

采集方式：seed ∈ {1, 2024, 2**62+7}，全量 385 只股票 init（as_of=2026-10-23），从 minute=600
起每个全局 tick 先 ``advance_minute`` 再 ``advance``，在 tick 20/60/120/200 取
``sha256(json.dumps(state, sort_keys=True))``。120 个 tick 内含多次交易日切换与午休；
200 个 tick 还覆盖下午开盘后的恢复。
"""

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from stocksim.domain import market_engine as me
from stocksim.domain.clock import advance_minute
from stocksim.domain.rules import is_within_limits

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"
POOL = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
RANGES = {
    i["name"]: i["base_price_range_yuan"]
    for i in json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
}
AS_OF = dt.date(2026, 10, 23)
START_MINUTE = 600
SEEDS = (1, 2024, 2**62 + 7)
CHECKPOINTS = (20, 60, 120, 200)

GOLDEN = {
    (1, 20): "7f9df13ad0f984fe4eee2a7ed283e40608495b418c11a574c110dfb7d3b19572",
    (1, 60): "a84883a74cda777560516070466877e2578ddd0c66290bef798aeb27b2cdd9ee",
    (1, 120): "3544b76198343bc5b40826655ea92cf03841609188160ddc9f442c632d0a2dd2",
    (1, 200): "4d0ba2eb1a19b7d046763226269416e5948cd0d592aec7420317ddc3eedb848b",
    (2024, 20): "1d18626c08837aaeedaeb461de21108b64c91395e5dd6ec2fe584ef3d0285cc5",
    (2024, 60): "9e3fc8b31965e09bdcadb9623e642d532ec2a7ba65baf8dfac5c444ada6166fa",
    (2024, 120): "056ecd16df17c6da081121d8e5cf723faf399ce505bff9ff3c59899a5baaec89",
    (2024, 200): "f036e83b3c9874ed28194a1571f93566dfa0716010e1b043e0655f706da2f723",
    (2**62 + 7, 20): "32eb4c93d35e9f230cb0a88f109c0b99d24c63f5621529e41edfb3863ded199b",
    (2**62 + 7, 60): "9159ac5940188285fb6a4a124176424298a272b75df175e37a96676bfc2b8eba",
    (2**62 + 7, 120): "9f0e693f832c2ceffb9ad1257f88b9b29eaa8918ac4e240b8b195d3f9344af05",
    (2**62 + 7, 200): "63f9068f2ed91e540da1094574d34f975b365448683e868d84f3f2fd845bbcf4",
}


def _digest(state) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def _run(seed, **kwargs):
    """推进 200 个全局 tick，返回 {checkpoint: digest}。kwargs 原样传给 advance。"""
    state = me.init_market(seed, POOL, AS_OF, RANGES)
    minute = START_MINUTE
    digests = {}
    for tick in range(1, max(CHECKPOINTS) + 1):
        minute = advance_minute(minute)
        state = me.advance(state, seed, tick, minute, **kwargs)
        if tick in CHECKPOINTS:
            digests[tick] = _digest(state)
    return digests


@pytest.mark.parametrize("seed", SEEDS)
def test_golden_digests_without_drift(seed):
    digests = _run(seed)
    for tick in CHECKPOINTS:
        assert digests[tick] == GOLDEN[(seed, tick)], f"seed={seed} tick={tick}"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("drift", [None, {}])
def test_golden_digests_with_disabled_drift(seed, drift):
    """drift=None 与 drift={} 都必须与金值（即不传参）逐位一致。"""
    digests = _run(seed, drift=drift)
    for tick in CHECKPOINTS:
        assert digests[tick] == GOLDEN[(seed, tick)], f"seed={seed} tick={tick} drift={drift!r}"


def test_drift_changes_only_targeted_stock_and_stays_within_limits():
    """带 drift 时目标股票偏离基线、其他股票不变，价格始终在涨跌停区间内。"""
    seed = 2024
    base = me.init_market(seed, POOL, AS_OF, RANGES)
    state = base
    plain = base
    minute = START_MINUTE
    for tick in range(1, 41):
        minute = advance_minute(minute)
        # 极端漂移（远超正常上限）也必须被涨跌停钳制
        state = me.advance(state, seed, tick, minute, drift={3: 400_000, 4: -400_000})
        plain = me.advance(plain, seed, tick, minute)
    for idx, (a, b) in enumerate(zip(state["stocks"], plain["stocks"], strict=True)):
        if idx in (3, 4):
            assert a["price"] != b["price"]
            assert is_within_limits(a["price"], a["prev_close"])
        else:
            assert a["price"] == b["price"]
    assert state["stocks"][3]["price"] > plain["stocks"][3]["price"]
    assert state["stocks"][4]["price"] < plain["stocks"][4]["price"]


def test_golden_covers_lunch_break_and_day_rollover():
    """采集窗口确实包含交易日切换与午休，避免金值覆盖面悄悄缩水。"""
    seed = 2024
    state = me.init_market(seed, POOL, AS_OF, RANGES)
    minute = START_MINUTE
    days = set()
    paused_ticks = 0
    for tick in range(1, 201):
        minute = advance_minute(minute)
        before = state["trading_tick"]
        state = me.advance(state, seed, tick, minute)
        days.add(state["trading_day"])
        if state["trading_tick"] == before:
            paused_ticks += 1
    assert len(days) >= 5
    assert paused_ticks > 60
