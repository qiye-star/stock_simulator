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

# 2026-10-26 因 000938 名称修正重采；行情字段逐位不变，见决策 19。
GOLDEN = {
    (1, 20): "0a738c3c83057bd49f579d44a58c1931d4dbe428f2d869de0338cd8b2561e0a0",
    (1, 60): "17f29a4f75350a250d1b67624d127a1340a1493c2c311857bec2a0401d21373a",
    (1, 120): "50a393a314b4acd638d02f62de69d959fa73b47c6a26209d78914b33ad40f137",
    (1, 200): "5c1e10e0b22fb09ed523a9123176add6cb0db4b3765410e58ed9909839a5ab6e",
    (2024, 20): "7ea2c8bf18d9bc163eb9e750dce8f27d24b47558b5779db2b92e465b779227e1",
    (2024, 60): "f129ac38f8fda4c4f7e74342cfc9e6d28fe633327d6c34924e248b33a1565e8a",
    (2024, 120): "09a9ada70d6be851d07db0af6e94f3000f8dd6922513f836f192a89313126c27",
    (2024, 200): "f228054a113a11a31aa9fc01a69de6ec529cdbd48b41ba4f8f4ded6589d0cca0",
    (2**62 + 7, 20): "887f4b25009ed66d40dc29a46fb6cdb23111545065a9cca5eca217ce7766384f",
    (2**62 + 7, 60): "a9449a9616001b39f771f6b2d1f1af069a8a965cce7e47397f820f082ef3400d",
    (2**62 + 7, 120): "29217d0e1fc34eb7862886eefa193a98b2588aa01ca94dec85211f962b5bf07e",
    (2**62 + 7, 200): "470969dc6c988a9e77884b8ad4be1ef6743b79674df0955ce533e91d0ddd654a",
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
