"""显式 ``rules=1`` 与未传 rules 的 v1 行为逐位一致（07 §3.4）。

v1 金值本身由 test_market_engine_golden.py 守护（该文件一字不改）；这里复用其 GOLDEN 与 _run，
证明 advance 新增的 rules 参数在 v1 路径上不改变结果。
"""

import importlib.util
from pathlib import Path

import pytest

_GOLDEN_PATH = Path(__file__).with_name("test_market_engine_golden.py")
_spec = importlib.util.spec_from_file_location("_v1_golden", _GOLDEN_PATH)
_golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_golden)


@pytest.mark.parametrize("seed", _golden.SEEDS)
def test_explicit_rules_1_matches_v1_golden(seed):
    digests = _golden._run(seed, rules=1)
    for tick in _golden.CHECKPOINTS:
        assert digests[tick] == _golden.GOLDEN[(seed, tick)], f"seed={seed} tick={tick}"
