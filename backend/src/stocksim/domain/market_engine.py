"""确定性行情引擎。全部整数分；同一 (seed, tick, 初始状态) 永远得到同一结果。

状态（dict，可 JSON 序列化）：
{
  "trading_tick": int,        # 已处理的交易 tick 数（只在交易时段递增）
  "trading_day": int,         # = trading_tick // TICKS_PER_TRADING_DAY
  "breaker": {code: int},     # 熔断剩余冷却 tick（仅 >0）
  "stocks": [                 # 顺序即 stock_idx（RNG 维度），必须稳定
    {code, name, industry, profile, stock_idx,
     price, prev_close, open, high, low,            # 分
     volume, daily_volume, prev_daily_volume, avg_volume,
     history: [{date: "YYYY-MM-DD", open, high, low, close, volume}, ...]  # 最多 60 根
    }, ...]
}

RNG 维度约定：init 使用 INIT_TICK=-1；交易 tick 使用其全局 tick（k=0 涨跌，1 彩蛋幅度，
2 成交量扰动，100+ 五档）。见 rng.py。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from .clock import TICKS_PER_TRADING_DAY, is_trading_time
from .money import PPM_DENOMINATOR, round_half_up_div, scale_ppm
from .rng import rand_below
from .rules import breaker_move_exceeded, clamp_to_limits, tick_circuit_breakers
from .types import Quote

INIT_TICK = -1
HISTORY_LEN = 60
DAILY_MOVE_SPAN_PPM = 40_000  # 单 tick ±2%（legacy 2099）：rand_below(40000) - 20000
DAILY_MOVE_OFFSET_PPM = 20_000
BULL_UP_PERCENT = 70  # 影视飓风 70% 概率上涨（legacy 2089-2095）
BULL_UP_MIN_PPM = 5_000  # +0.5%
BULL_UP_SPAN_PPM = 25_000  # 到 +3%
BULL_DOWN_MIN_PPM = -20_000  # -2%
BULL_DOWN_SPAN_PPM = 15_000  # 到 -0.5%
VOLUME_CHANGE_CLAMP_PPM = 200_000  # 成交量涨跌幅限制 ±20%（legacy 1735 / 2140）
VOLUME_RANDOM_BASE_PPM = 970_000  # ±3%
VOLUME_RANDOM_SPAN_PPM = 60_000
INTRADAY_HIGH_SPAN_PPM = 20_000  # 历史 K 线高低点 ±2%
INITIAL_VOLUME_SPAN = 1_000_000
AVG_VOLUME_WINDOW = 5
ORDER_BOOK_LEVELS = 5
ORDER_BOOK_K_BASE = 100
ORDER_BOOK_VOLUME_SPAN = 10_000
ORDER_BOOK_VOLUME_MIN = 100
DEFAULT_PRICE_RANGE_YUAN = (5, 100)  # legacy generateBasePrice default
BULL_BIAS_PROFILE = "bull_bias"
BULL_BIAS_CODE = "999999"

# 行业价格区间来自 data/industries.json（由调用方传入 industry_ranges）


def _candle_volume(prev_volume: int, daily_change_ppm: int, random_ppm: int) -> int:
    """成交量：prev * (1 + clamp(涨跌幅) * 1.5) * 随机因子，整数向下取整（legacy 1725-1737）。"""
    clamped = max(-VOLUME_CHANGE_CLAMP_PPM, min(VOLUME_CHANGE_CLAMP_PPM, daily_change_ppm))
    factor = PPM_DENOMINATOR + (clamped * 3) // 2
    return max(0, prev_volume * factor * random_ppm // (PPM_DENOMINATOR * PPM_DENOMINATOR))


def _change_ppm(prev: int, new: int) -> int:
    return round_half_up_div((new - prev) * PPM_DENOMINATOR, prev)


def _generate_history(
    seed: int, stock_idx: int, base_price: int, as_of: date, initial_volume: int
) -> list[dict[str, Any]]:
    """60 根日 K（legacy generateHistory 1638-1694）。"""
    history: list[dict[str, Any]] = []
    price = base_price
    prev_volume = initial_volume
    for i in range(HISTORY_LEN):
        k = 2 + 4 * i
        change = (
            rand_below(seed, INIT_TICK, stock_idx, k, DAILY_MOVE_SPAN_PPM) - DAILY_MOVE_OFFSET_PPM
        )
        open_ = price
        close = max(1, scale_ppm(open_, PPM_DENOMINATOR + change))
        high = scale_ppm(
            max(open_, close),
            PPM_DENOMINATOR + rand_below(seed, INIT_TICK, stock_idx, k + 1, INTRADAY_HIGH_SPAN_PPM),
        )
        low = scale_ppm(
            min(open_, close),
            PPM_DENOMINATOR - rand_below(seed, INIT_TICK, stock_idx, k + 2, INTRADAY_HIGH_SPAN_PPM),
        )
        low = max(1, min(low, open_, close))
        high = max(high, open_, close)
        random_ppm = VOLUME_RANDOM_BASE_PPM + rand_below(
            seed, INIT_TICK, stock_idx, k + 3, VOLUME_RANDOM_SPAN_PPM
        )
        volume = _candle_volume(prev_volume, _change_ppm(open_, close), random_ppm)
        day = as_of - timedelta(days=HISTORY_LEN - 1 - i)
        history.append(
            {
                "date": day.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
        price = close
        prev_volume = volume
    return history


def init_market(
    seed: int,
    stocks: Sequence[Mapping[str, Any]],
    as_of: date,
    industry_ranges: Mapping[str, Sequence[int]],
) -> dict[str, Any]:
    """生成初始行情状态（legacy initMarketData 1687-1750）。

    stocks: [{code, name, industry, profile}]；industry_ranges: {行业: [lo_yuan, hi_yuan]}。
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for idx, stock in enumerate(stocks):
        code = str(stock["code"])
        if code in seen:
            raise ValueError(f"duplicate stock code: {code}")
        seen.add(code)
        lo, hi = industry_ranges.get(
            str(stock["industry"]), industry_ranges.get("default", DEFAULT_PRICE_RANGE_YUAN)
        )
        base = int(lo) * 100 + rand_below(seed, INIT_TICK, idx, 0, (int(hi) - int(lo)) * 100)
        initial_volume = rand_below(seed, INIT_TICK, idx, 1, INITIAL_VOLUME_SPAN)
        history = _generate_history(seed, idx, base, as_of, initial_volume)
        recent = [c["volume"] for c in history[-AVG_VOLUME_WINDOW:]]
        avg_volume = sum(recent) // len(recent)
        # 现价取最后一根 K 线收盘价（与昨收连续，保证涨跌停区间包含现价）。
        # legacy 把现价设为 60 天前的起始价 basePrice，与昨收可相差 >10%，首 tick 会跳变。
        last_close = history[-1]["close"]
        out.append(
            {
                "code": code,
                "name": str(stock["name"]),
                "industry": str(stock["industry"]),
                "profile": str(stock.get("profile", "normal")),
                "stock_idx": idx,
                "price": last_close,
                "prev_close": last_close,
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "volume": 0,
                "daily_volume": 0,
                "prev_daily_volume": avg_volume,
                "avg_volume": avg_volume,
                "history": history,
            }
        )
    return {"trading_tick": 0, "trading_day": 0, "breaker": {}, "stocks": out}


def _rollover(stock: dict[str, Any]) -> None:
    """交易日切换（legacy updateMarket 2033-2063）。就地修改 stock。"""
    stock["prev_close"] = stock["price"]
    stock["prev_daily_volume"] = stock["daily_volume"]
    # 近 5 根 K 线（含刚结束的交易日）的均量。legacy 会把当日量重复计入一次，此处修正。
    recent = [c["volume"] for c in stock["history"][-AVG_VOLUME_WINDOW:]]
    stock["avg_volume"] = sum(recent) // len(recent) if recent else stock["daily_volume"]
    stock["daily_volume"] = 0
    stock["volume"] = 0
    stock["open"] = stock["high"] = stock["low"] = stock["price"]
    last_date = date.fromisoformat(stock["history"][-1]["date"])
    stock["history"].append(
        {
            "date": (last_date + timedelta(days=1)).isoformat(),
            "open": stock["price"],
            "high": stock["price"],
            "low": stock["price"],
            "close": stock["price"],
            "volume": 0,
        }
    )
    if len(stock["history"]) > HISTORY_LEN:
        del stock["history"][0]


def _move_ppm(seed: int, tick: int, stock: Mapping[str, Any]) -> int:
    idx = int(stock["stock_idx"])
    if stock.get("profile") == BULL_BIAS_PROFILE:
        if rand_below(seed, tick, idx, 0, 100) < BULL_UP_PERCENT:
            return BULL_UP_MIN_PPM + rand_below(seed, tick, idx, 1, BULL_UP_SPAN_PPM)
        return BULL_DOWN_MIN_PPM + rand_below(seed, tick, idx, 1, BULL_DOWN_SPAN_PPM)
    return rand_below(seed, tick, idx, 0, DAILY_MOVE_SPAN_PPM) - DAILY_MOVE_OFFSET_PPM


def _clone(state: Mapping[str, Any]) -> dict[str, Any]:
    """结构化复制（不共享 list/dict），避免修改入参。"""
    stocks = []
    for stock in state["stocks"]:
        copied = dict(stock)
        copied["history"] = [dict(c) for c in stock["history"]]
        stocks.append(copied)
    return {
        "trading_tick": state["trading_tick"],
        "trading_day": state["trading_day"],
        "breaker": dict(state["breaker"]),
        "stocks": stocks,
    }


def advance(state: Mapping[str, Any], seed: int, tick: int, minute_of_day: int) -> dict[str, Any]:
    """推进一个全局 tick。非交易时段原样返回副本（legacy 2028-2031 不更新行情）。

    tick 为全局单调递增的 tick 编号（RNG 维度）。返回新 dict，不修改入参。
    """
    new = _clone(state)
    if not is_trading_time(minute_of_day):
        return new

    trading_tick = int(new["trading_tick"]) + 1
    new["trading_tick"] = trading_tick
    rollover = trading_tick % TICKS_PER_TRADING_DAY == 0
    new["trading_day"] = trading_tick // TICKS_PER_TRADING_DAY
    if rollover:
        new["breaker"] = {}

    triggered: list[str] = []
    for stock in new["stocks"]:
        if rollover:
            _rollover(stock)
        pre = int(stock["price"])
        prev_close = int(stock["prev_close"])
        attempted = max(1, scale_ppm(pre, PPM_DENOMINATOR + _move_ppm(seed, tick, stock)))
        if breaker_move_exceeded(attempted, pre):
            triggered.append(stock["code"])
        price = clamp_to_limits(attempted, prev_close)
        stock["price"] = price
        stock["high"] = max(int(stock["high"]), price)
        stock["low"] = min(int(stock["low"]), price)

        daily_change = _change_ppm(prev_close, price)
        random_ppm = VOLUME_RANDOM_BASE_PPM + rand_below(
            seed, tick, int(stock["stock_idx"]), 2, VOLUME_RANDOM_SPAN_PPM
        )
        daily_volume = _candle_volume(int(stock["prev_daily_volume"]), daily_change, random_ppm)
        stock["daily_volume"] = daily_volume
        stock["volume"] = daily_volume

        candle = stock["history"][-1]
        candle["close"] = price
        candle["high"] = max(int(candle["high"]), price)
        candle["low"] = min(int(candle["low"]), price)
        candle["volume"] = daily_volume

    # 熔断：先置位再统一递减（legacy triggerCircuitBreaker → updateCircuitBreakerCooldown）
    new["breaker"] = tick_circuit_breakers(new["breaker"], triggered)
    return new


def order_book(
    price_cents: int, seed: int, tick: int, stock_idx: int
) -> dict[str, list[dict[str, int]]]:
    """五档盘口，按需由 RNG 计算（不入状态）。legacy generateOrderBook 2164-2184。

    第 i 档价差 = (i+1) 分 + 额外 0/1 分（由随机数决定），买价低于 1 分时钳制为 1 分。
    """
    bids: list[dict[str, int]] = []
    asks: list[dict[str, int]] = []
    for i in range(ORDER_BOOK_LEVELS):
        k = ORDER_BOOK_K_BASE + i * 4
        bid_extra = 1 if rand_below(seed, tick, stock_idx, k, 2) == 1 else 0
        ask_extra = 1 if rand_below(seed, tick, stock_idx, k + 2, 2) == 1 else 0
        bid_vol = (
            rand_below(seed, tick, stock_idx, k + 1, ORDER_BOOK_VOLUME_SPAN) + ORDER_BOOK_VOLUME_MIN
        )
        ask_vol = (
            rand_below(seed, tick, stock_idx, k + 3, ORDER_BOOK_VOLUME_SPAN) + ORDER_BOOK_VOLUME_MIN
        )
        bids.append({"price_cents": max(1, price_cents - (i + 1) - bid_extra), "volume": bid_vol})
        asks.append({"price_cents": price_cents + (i + 1) + ask_extra, "volume": ask_vol})
    return {"bids": bids, "asks": asks}


def find_stock(state: Mapping[str, Any], code: str) -> dict[str, Any] | None:
    for stock in state["stocks"]:
        if stock["code"] == code:
            return stock
    return None


def to_quote(state: Mapping[str, Any], code: str) -> Quote | None:
    """由行情状态派生撮合用的 Quote（trade-time 快照的数据来源）。"""
    stock = find_stock(state, code)
    if stock is None:
        return None
    return Quote(
        code=stock["code"],
        name=stock["name"],
        industry=stock["industry"],
        price_cents=int(stock["price"]),
        prev_close_cents=int(stock["prev_close"]),
        circuit_breaker_active=int(state["breaker"].get(code, 0)) > 0,
    )


__all__ = [
    "HISTORY_LEN",
    "INIT_TICK",
    "advance",
    "find_stock",
    "init_market",
    "order_book",
    "to_quote",
]
