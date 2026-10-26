"""v2 行情引擎金值（07 §9.1）：standard 股票池全量 385 只，从 570（9:30，tt=0）起每个全局 tick
先 ``advance_minute`` 再 ``advance(rules=2)``，在全局 tick 300 / 700 / 1500 取 sha256。

1500 个全局 tick 覆盖 tt 0→302：跨越第 0 日收盘、次日 9:30 换日（全局 tick 1440）与午休。
v2 对外发布后冻结：之后只能新增 ``clock_rules = 3``，禁止为通过测试修改下面的常量。
采集脚本见 scripts/clock_v2_sim_report.py 同一引擎（本测试由 2026-10-26 当前代码采集）。
"""

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from stocksim.domain import market_engine as me
from stocksim.domain.clock import CLOCK_RULES_V2, V2_START_MINUTE, advance_minute

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"
POOL = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
RANGES = {
    i["name"]: i["base_price_range_yuan"]
    for i in json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
}
AS_OF = dt.date(2026, 10, 23)
SEEDS = (1, 2024, 2**62 + 7)
CHECKPOINTS = (300, 700, 1500)

GOLDEN = {
    (1, 300): "c7c24b480e67158c950d908e6afe767c4513dbb34fb031b2d3d62d41f795093a",
    (1, 700): "4aca97e91e253bd347bdf7e7c3d0fb2bd2ccbe061fc8817cac49869dcc7e2a17",
    (1, 1500): "7e872a81a7334c09a819d766c76f9a6fa24b552c9d429c5dac72a2e9c4ddb2b2",
    (2024, 300): "2da2e998616dda6bcde7769ae33af772198f3696af058f4984515a1f3729c58f",
    (2024, 700): "259b8a5a8f85f3ad5574828748ad27adc1f7803a56f421a14e880bad0f1f87b4",
    (2024, 1500): "ceafe4b3e6ece28a764d9ad23f81952953608c829a77b8067e5dfe1acd22904a",
    (2**62 + 7, 300): "48257d6b364e98e57984509952924997670ec6ce0a35401c3164629c53fcd85c",
    (2**62 + 7, 700): "5c1c2562aacb87b929f5b268da1293df0977144a58f8f0b677fc8268bcdbb8da",
    (2**62 + 7, 1500): "be55eea0f7abd533acb14a373562f54400a18f403d2ef045ee1c5b700b1db457",
}


def _digest(state) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("seed", SEEDS)
def test_v2_golden_digests(seed):
    state = me.init_market(seed, POOL, AS_OF, RANGES)
    minute = V2_START_MINUTE
    for tick in range(1, max(CHECKPOINTS) + 1):
        minute = advance_minute(minute)
        state = me.advance(state, seed, tick, minute, rules=CLOCK_RULES_V2)
        if tick in CHECKPOINTS:
            assert _digest(state) == GOLDEN[(seed, tick)], f"seed={seed} tick={tick}"
