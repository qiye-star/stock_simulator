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

from .clock import (
    CLOCK_RULES_V1,
    CLOCK_RULES_V2,
    TICKS_PER_TRADING_DAY,
    V2_TRADING_TICKS_PER_DAY,
    is_trading_time,
    timebase,
)
from .money import PPM_DENOMINATOR, round_half_up_div, scale_ppm
from .rng import rand_below
from .rules import LIMIT_PCT_BP, breaker_move_exceeded, clamp_to_limits, tick_circuit_breakers
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

# ---- v2（clock_rules=2，见 docs/10.26-plan/07-时钟v2.md §4）常量：整数 ppm，发布后冻结 ----
V2_IDIO_SPAN_PPM = 3_200  # 个股特质噪声 rand_below(3200) - 1600，σ≈924 ppm
V2_IDIO_OFFSET_PPM = 1_600
V2_MKT_SPAN_PPM = 1_680  # 全市场共同因子 rand_below(1680) - 840，所有股票共用
V2_MKT_OFFSET_PPM = 840
V2_MARKET_FACTOR_IDX = 400  # RNG 维度：共同因子占用的 stock_idx（个股为 0..384）
# 波动档位 (概率%, 波动倍数 ppm)
V2_VOL_TABLE = ((35, 750_000), (45, 1_000_000), (15, 1_500_000), (5, 2_500_000))
# 趋势日概率（%）。标定见 scripts/clock_v2_sim_report.py：
# 计划初值 4% / [200,450] 时触涨停与触跌停比值 1.57（超出 0.7–1.4）。
V2_TREND_PCT = 1
V2_TREND_PPM = (400, 700)  # 趋势日每 tick 漂移幅度 U[400, 700] ppm，方向随机
V2_BULL_DRIFT_PPM = 120  # bull_bias 每 tick 额外漂移（日均约 +2.9%）
V2_REGIME_TICK_BASE = -(1 << 33)  # 日档位 RNG 的 tick 命名空间：V2_REGIME_TICK_BASE - day
V2_VOLUME_RANDOM_BASE_PPM = 700_000  # 成交量随机因子 700k + rand_below(600k)，均值约 1.0
V2_VOLUME_RANDOM_SPAN_PPM = 600_000
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


def _clone_v2(state: Mapping[str, Any]) -> dict[str, Any]:
    """v2 用的结构化复制：只浅拷贝 history 列表。

    v2 只替换末根 K 线（先复制再改），历史 K 线对象与入参共享且不被修改。
    """
    stocks = []
    for stock in state["stocks"]:
        copied = dict(stock)
        copied["history"] = list(stock["history"])
        stocks.append(copied)
    return {
        "trading_tick": state["trading_tick"],
        "trading_day": state["trading_day"],
        "breaker": dict(state["breaker"]),
        "stocks": stocks,
    }


def advance(
    state: Mapping[str, Any],
    seed: int,
    tick: int,
    minute_of_day: int,
    *,
    drift: Mapping[int, int] | None = None,
    rules: int = CLOCK_RULES_V1,
) -> dict[str, Any]:
    """推进一个全局 tick。非交易时段原样返回副本（legacy 2028-2031 不更新行情）。

    tick 为全局单调递增的 tick 编号（RNG 维度）。返回新 dict，不修改入参。

    drift: {stock_idx: ppm}，本 tick 叠加到随机涨跌幅上的外部漂移（事件行情用，由调用方算好）。
    None / 空映射时执行的整数运算与没有该参数时完全一致（金值测试守护）。漂移只改变“尝试价”，
    熔断判断与涨跌停钳制照旧，被钳掉的部分直接丢弃。

    rules: 时钟规则版本。1（默认）为 v1 引擎（本函数体逐字保留，金值测试守护）；
    2 为 v2 引擎（_advance_v2）。
    """
    if rules == CLOCK_RULES_V2:
        return _advance_v2(state, seed, tick, minute_of_day, drift)
    if rules != CLOCK_RULES_V1:
        raise ValueError(f"unknown clock_rules: {rules}")
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
        move = _move_ppm(seed, tick, stock)
        if drift:
            move += drift.get(int(stock["stock_idx"]), 0)
        attempted = max(1, scale_ppm(pre, PPM_DENOMINATOR + move))
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


def _day_regime(seed: int, day: int, idx: int) -> tuple[int, int]:
    """v2 日档位：(波动倍数 ppm, 趋势日每 tick 漂移 ppm)。(seed, day, idx) 的纯函数。"""
    tick = V2_REGIME_TICK_BASE - day
    pick = rand_below(seed, tick, idx, 0, 100)
    vol_ppm = V2_VOL_TABLE[-1][1]
    acc = 0
    for weight, ppm in V2_VOL_TABLE:
        acc += weight
        if pick < acc:
            vol_ppm = ppm
            break
    trend_ppm = 0
    if rand_below(seed, tick, idx, 1, 100) < V2_TREND_PCT:
        lo, hi = V2_TREND_PPM
        mag = lo + rand_below(seed, tick, idx, 2, hi - lo + 1)
        trend_ppm = mag if rand_below(seed, tick, idx, 3, 2) == 1 else -mag
    return vol_ppm, trend_ppm


def _regime_of(state: dict[str, Any], seed: int, day: int, idx: int) -> tuple[int, int]:
    """取当日档位，缓存在 state["regime"]（不入 payload）；日切换时整体重建。

    就地修改 state，调用方须已复制。
    """
    cache = state.get("regime")
    if cache is None or cache["day"] != day:
        cache = {"day": day, "vol": {}, "trend": {}}
        state["regime"] = cache
    if idx not in cache["vol"]:
        vol_ppm, trend_ppm = _day_regime(seed, day, idx)
        cache["vol"][idx] = vol_ppm
        cache["trend"][idx] = trend_ppm
    return cache["vol"][idx], cache["trend"][idx]


def _increment_v2(prev_daily_volume: int, daily_change_ppm: int, random_ppm: int) -> int:
    """v2 成交量增量：整日量按前一日量 × (1 + 1.5·涨跌幅) × 随机因子 分摊到 242 个 tick。"""
    clamped = max(-VOLUME_CHANGE_CLAMP_PPM, min(VOLUME_CHANGE_CLAMP_PPM, daily_change_ppm))
    factor = PPM_DENOMINATOR + (clamped * 3) // 2
    inc = (
        prev_daily_volume
        * factor
        * random_ppm
        // (PPM_DENOMINATOR * PPM_DENOMINATOR * V2_TRADING_TICKS_PER_DAY)
    )
    return max(1, inc)


def _advance_v2(
    state: Mapping[str, Any],
    seed: int,
    tick: int,
    minute_of_day: int,
    drift: Mapping[int, int] | None,
) -> dict[str, Any]:
    """v2 单 tick：242 个交易 tick / 日，换日在次日 9:30（rolls_at）。07 §4.1–4.6。"""
    new = _clone_v2(state)
    if "regime" in state:
        cache = state["regime"]
        new["regime"] = {
            "day": cache["day"],
            "vol": dict(cache["vol"]),
            "trend": dict(cache["trend"]),
        }
    if not is_trading_time(minute_of_day):
        return new

    tb = timebase(CLOCK_RULES_V2)
    trading_tick = int(new["trading_tick"]) + 1
    new["trading_tick"] = trading_tick
    rollover = tb.rolls_at(trading_tick)
    day = tb.day_of(trading_tick)
    new["trading_day"] = day
    if rollover:
        new["breaker"] = {}
    market_factor = (
        rand_below(seed, tick, V2_MARKET_FACTOR_IDX, 0, V2_MKT_SPAN_PPM) - V2_MKT_OFFSET_PPM
    )

    triggered: list[str] = []
    for stock in new["stocks"]:
        if rollover:
            _rollover(stock)
        idx = int(stock["stock_idx"])
        pre = int(stock["price"])
        prev_close = int(stock["prev_close"])
        vol_ppm, trend_ppm = _regime_of(new, seed, day, idx)
        idio = rand_below(seed, tick, idx, 0, V2_IDIO_SPAN_PPM) - V2_IDIO_OFFSET_PPM
        move = round_half_up_div(idio * vol_ppm, PPM_DENOMINATOR) + market_factor + trend_ppm
        if stock.get("profile") == BULL_BIAS_PROFILE:
            move += V2_BULL_DRIFT_PPM
        if drift:
            move += drift.get(idx, 0)
        attempted = max(1, scale_ppm(pre, PPM_DENOMINATOR + move))
        if breaker_move_exceeded(attempted, pre):
            triggered.append(stock["code"])
        price = clamp_to_limits(attempted, prev_close)
        stock["price"] = price
        stock["high"] = max(int(stock["high"]), price)
        stock["low"] = min(int(stock["low"]), price)

        daily_change = _change_ppm(prev_close, price)
        random_ppm = V2_VOLUME_RANDOM_BASE_PPM + rand_below(
            seed, tick, idx, 2, V2_VOLUME_RANDOM_SPAN_PPM
        )
        daily_volume = int(stock["daily_volume"]) + _increment_v2(
            int(stock["prev_daily_volume"]), daily_change, random_ppm
        )
        stock["daily_volume"] = daily_volume
        stock["volume"] = daily_volume

        candle = dict(stock["history"][-1])  # 末根 K 线可能与入参共享，先复制再改
        candle["close"] = price
        candle["high"] = max(int(candle["high"]), price)
        candle["low"] = min(int(candle["low"]), price)
        candle["volume"] = daily_volume
        stock["history"][-1] = candle

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
        limit_pct_bp=int(stock.get("limit_pct_bp", LIMIT_PCT_BP)),
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
