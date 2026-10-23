"""静态数据：股票池与行业文件（由 scripts/convert_stockdata.py 生成）。"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_pool_has_385_unique_stocks_with_profile():
    pool = _load("stock_pool.json")
    assert len(pool) == 385
    codes = [s["code"] for s in pool]
    assert len(set(codes)) == 385
    for s in pool:
        assert set(s) == {"code", "name", "industry", "profile"}
        assert s["code"] and s["name"] and s["industry"]
    bull = [s for s in pool if s["profile"] == "bull_bias"]
    assert [s["code"] for s in bull] == ["999999"] and bull[0]["name"] == "影视飓风"


def test_industries_cover_pool_and_have_ranges():
    pool = _load("stock_pool.json")
    industries = _load("industries.json")
    counts = {}
    for s in pool:
        counts[s["industry"]] = counts.get(s["industry"], 0) + 1
    assert {i["name"]: i["stock_count"] for i in industries} == counts
    assert sum(i["stock_count"] for i in industries) == 385
    for i in industries:
        lo, hi = i["base_price_range_yuan"]
        assert 0 < lo < hi
    by_name = {i["name"]: i["base_price_range_yuan"] for i in industries}
    assert by_name["银行"] == [5, 15] and by_name["券商"] == [8, 30]
