"""domain 单测共用夹具：事件规则集（由 data/*.json 构造，domain 本身不读文件）。"""

import json
from pathlib import Path

import pytest

from stocksim.domain.events import build_ruleset, save_params

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def load_ruleset(clock_rules=1):
    return build_ruleset(
        supply_chain=_load("supply_chain.json"),
        exposure=_load("stock_exposure.json"),
        templates=_load("news_templates.json"),
        industries=_load("industries.json"),
        stock_pool=_load("stock_pool.json"),
        clock_rules=clock_rules,
    )


@pytest.fixture(scope="session")
def event_ruleset():
    return load_ruleset()


@pytest.fixture(scope="session")
def event_params(event_ruleset):
    """seed=2024 的存档抖动参数。"""
    return save_params(2024, event_ruleset)


@pytest.fixture(scope="session")
def event_ruleset_v2():
    """时钟 v2（每交易日 242 tick）的规则集。"""
    return load_ruleset(2)
