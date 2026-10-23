"""行情引擎：确定性、涨跌停、±2% 波动、彩蛋偏多、交易日切换、五档盘口。"""

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from stocksim.domain import market_engine as me
from stocksim.domain.money import scale_ppm
from stocksim.domain.rules import is_within_limits

DATA = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "data"
POOL = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
RANGES = {
    i["name"]: i["base_price_range_yuan"]
    for i in json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
}
AS_OF = dt.date(2026, 10, 23)
MORNING = 600  # 10:00，交易时段
SUBSET = [
    s for s in POOL if s["code"] in {"600036", "600519", "999999", "000001", "600000"}
] or POOL[:5]


def _state(seed=2024, stocks=None):
    return me.init_market(seed, stocks or POOL, AS_OF, RANGES)


def _run(state, seed, ticks, start_tick=1, minute=MORNING):
    for t in range(start_tick, start_tick + ticks):
        state = me.advance(state, seed, t, minute)
    return state


def test_init_is_deterministic_and_shaped():
    a = _state()
    b = _state()
    assert a == b
    assert len(a["stocks"]) == 385
    assert _state(seed=1) != a
    first = a["stocks"][0]
    assert len(first["history"]) == me.HISTORY_LEN
    assert first["history"][-1]["date"] == AS_OF.isoformat()
    assert first["prev_close"] == first["history"][-1]["close"]


def test_init_base_price_within_industry_range_and_price_continuous():
    st = _state()
    for stock in st["stocks"]:
        lo, hi = RANGES.get(stock["industry"], RANGES.get("default", [5, 100]))
        base = stock["history"][0]["open"]  # 60 天前的起始价即 basePrice
        assert lo * 100 <= base < hi * 100
        # 现价与昨收连续，且位于涨跌停区间内
        assert stock["price"] == stock["prev_close"] == stock["history"][-1]["close"]
        assert is_within_limits(stock["price"], stock["prev_close"])
        assert stock["price"] >= 1


def test_init_rejects_duplicate_codes():
    dup = [POOL[0], POOL[0]]
    with pytest.raises(ValueError):
        me.init_market(1, dup, AS_OF, RANGES)


def test_advance_is_deterministic_for_seed_and_tick():
    start = _state()
    a = _run(start, 77, 60)
    b = _run(start, 77, 60)
    assert a == b
    c = _run(start, 78, 60)
    assert c != a


def test_advance_does_not_mutate_input():
    start = _state(stocks=SUBSET)
    snapshot = copy.deepcopy(start)
    me.advance(start, 5, 1, MORNING)
    assert start == snapshot


def test_non_trading_minute_is_noop():
    start = _state(stocks=SUBSET)
    assert me.advance(start, 5, 1, 0) == start
    assert me.advance(start, 5, 1, 720) == start


def test_per_tick_move_is_at_most_two_percent_for_normal_stocks():
    st = _state(stocks=SUBSET)
    for t in range(1, 200):
        nxt = me.advance(st, 9, t, MORNING)
        for old, new in zip(st["stocks"], nxt["stocks"], strict=True):
            if old["profile"] == "normal" and old["prev_close"] == new["prev_close"]:
                bound = scale_ppm(old["price"], 20_000)
                assert abs(new["price"] - old["price"]) <= bound + 1
        st = nxt


def test_prices_stay_within_daily_limits_over_many_days():
    st = _state(stocks=SUBSET)
    for t in range(1, 20 * 12 + 1):
        st = me.advance(st, 31, t, MORNING)
        for stock in st["stocks"]:
            assert is_within_limits(stock["price"], stock["prev_close"]), stock["code"]
            assert stock["price"] >= 1


def test_day_rollover_every_twenty_trading_ticks():
    st = _state(stocks=SUBSET)
    st19 = _run(st, 4, 19)
    assert st19["trading_day"] == 0 and st19["trading_tick"] == 19
    st20 = me.advance(st19, 4, 20, MORNING)
    assert st20["trading_day"] == 1 and st20["trading_tick"] == 20
    for before, after in zip(st19["stocks"], st20["stocks"], strict=True):
        # 切换日：昨收 = 上一交易 tick 的收盘价，成交量滚动
        assert after["prev_close"] == before["price"]
        assert after["prev_daily_volume"] == before["daily_volume"]
        assert len(after["history"]) == me.HISTORY_LEN
        assert after["history"][-1]["date"] > before["history"][-1]["date"]


def test_non_trading_ticks_do_not_count_towards_day():
    st = _state(stocks=SUBSET)
    for t in range(1, 40):
        st = me.advance(st, 4, t, 720)  # 午休
    assert st["trading_tick"] == 0 and st["trading_day"] == 0


def test_bull_bias_stock_skews_up():
    """单 tick、从昨收起步（不触及涨跌停），跨 400 个种子统计上涨比例（期望 70%）。"""
    ups = downs = 0
    for seed in range(400):
        st = _state(seed=seed, stocks=SUBSET)
        old = next(s for s in st["stocks"] if s["code"] == "999999")
        nxt = me.advance(st, seed, 1, MORNING)
        new = next(s for s in nxt["stocks"] if s["code"] == "999999")
        ups += new["price"] > old["price"]
        downs += new["price"] < old["price"]
    assert ups + downs > 380
    assert 0.62 < ups / (ups + downs) < 0.78


def test_normal_stock_is_roughly_symmetric():
    ups = downs = 0
    for seed in range(400):
        st = _state(seed=seed, stocks=SUBSET)
        old = next(s for s in st["stocks"] if s["code"] == "600036")
        nxt = me.advance(st, seed, 1, MORNING)
        new = next(s for s in nxt["stocks"] if s["code"] == "600036")
        ups += new["price"] > old["price"]
        downs += new["price"] < old["price"]
    assert 0.4 < ups / (ups + downs) < 0.6


def test_volume_is_positive_integer():
    st = _run(_state(stocks=SUBSET), 11, 30)
    for stock in st["stocks"]:
        assert isinstance(stock["daily_volume"], int) and stock["daily_volume"] >= 0
        assert isinstance(stock["price"], int)


def test_order_book_levels_are_ordered_and_bounded():
    book = me.order_book(10_000, 3, 12, 4)
    bids, asks = book["bids"], book["asks"]
    assert len(bids) == len(asks) == me.ORDER_BOOK_LEVELS
    assert all(b["price_cents"] < 10_000 for b in bids)
    assert all(a["price_cents"] > 10_000 for a in asks)
    assert [b["price_cents"] for b in bids] == sorted(
        (b["price_cents"] for b in bids), reverse=True
    )
    assert [a["price_cents"] for a in asks] == sorted(a["price_cents"] for a in asks)
    for level in bids + asks:
        assert 100 <= level["volume"] < 10_100
    assert me.order_book(10_000, 3, 12, 4) == book  # 确定性


def test_to_quote_reflects_state_and_breaker():
    st = _state(stocks=SUBSET)
    code = SUBSET[0]["code"]
    q = me.to_quote(st, code)
    assert q is not None and q.price_cents == st["stocks"][0]["price"]
    assert q.prev_close_cents == st["stocks"][0]["prev_close"]
    assert me.to_quote(st, "NOPE") is None
    st["breaker"][code] = 2
    assert me.to_quote(st, code).circuit_breaker_active
