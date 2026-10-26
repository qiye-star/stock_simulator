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

# 2026-10-26 因 000938 名称修正重采；行情字段逐位不变，见决策 19。
GOLDEN = {
    (1, 300): "594205dc25262c82c3cc7d5a15946df59126696594133dd33eb41878344ca1b9",
    (1, 700): "95a6f14795941d296bbfc96e9a67f3055be525b71f3b292f1f7f5cfbb7a581c7",
    (1, 1500): "83cd8ecb848b53c2b433aa2eb7353ad02cabd298f4d1ddd7b2dcb427f789f479",
    (2024, 300): "c3124920626c8942f3cf66ef5a1758ee35c1aed9a3e45ef1583414265830b0e1",
    (2024, 700): "987092cf82ba4d2942b16f0362ff20bb459021f7bd9c25dca7fb6cd58be9cb5b",
    (2024, 1500): "9c3d49068b0ab94f1b66aeb3a0ab4717530a62d222d1b79b680cae9f7f9521a6",
    (2**62 + 7, 300): "4f17db04b34d2b676530bc7ab82f5597c4ec74c830f3ef50c08af5eb70629164",
    (2**62 + 7, 700): "889ce55c792e154ebd8827d6593c310c374e05d10a3ea418df2e9f068e7e9190",
    (2**62 + 7, 1500): "a05acdb4744ce8707483f97b03862d18678f1e66b83fa5cd42d8ff86381c8d0e",
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
