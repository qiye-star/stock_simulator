"""日计划与快讯区间（01 §5.5-§5.6）。

``build_day_plan`` 把窗口内全部事件折算成某个交易日每个 tick、每只股票的漂移（ppm）：

    C_{e,s}(τ) = round( M · β_s · Σ_v amp_v · w_{s,v} · S(τ - δ_v) / 10^24 )
    drift_s(t) = clamp( Σ_e [C_{e,s}(t-p_e) - C_{e,s}(t-1-p_e)], ±cap )

每个“事件×股票”对只在整体上做一次舍入，逐 tick 差分精确相加回累计值（截断时除外）。延迟队列不需要
状态：``S(τ-δ)`` 本身就是闭式写法。漂移只依赖 (seed, ruleset, 交易 tick, stock_idx)，因此可重放。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ..money import round_half_up_div
from .constants import (
    BULL_BIAS_DRIFT_CAP_PPM,
    DRIFT_CAP_PPM,
    LOOKAHEAD_DAYS,
    LOOKBACK_DAYS,
    NEWS_LOOKAHEAD_DAYS,
    NEWS_LOOKBACK_DAYS,
)
from .graph import stock_beta_ppm
from .path import eval_path
from .types import EventRuleset, GameEvent, NewsItem, SaveParams

DayPlan = tuple[
    Mapping[int, int], ...
]  # 长度 ticks_per_day，下标 = day_offset，值 {stock_idx: drift_ppm}
PPM = 1_000_000
DENOM = PPM**4


def plan_window(day: int) -> range:
    """构建 day 的计划需要的事件排期日：[day-15, day+2]（不含负数日）。"""
    return range(max(0, day - LOOKBACK_DAYS), day + LOOKAHEAD_DAYS + 1)


def news_window(day: int) -> range:
    """某日内发布的快讯所属事件的排期日：[day-3, day+2]。"""
    return range(max(0, day - NEWS_LOOKBACK_DAYS), day + NEWS_LOOKAHEAD_DAYS + 1)


def _event_terms(event: GameEvent, ruleset: EventRuleset) -> dict[int, dict[int, int]]:
    """{stock_idx: {delay: Σ amp·w}}，A 的量纲是 ppm²。"""
    terms: dict[int, dict[int, int]] = {}

    def add(stock: int, delay: int, value: int) -> None:
        by_delay = terms.setdefault(stock, {})
        by_delay[delay] = by_delay.get(delay, 0) + value

    if event.scope == "market":
        for s in ruleset.stocks:
            add(s.idx, 0, PPM * PPM)
    for imp in event.impacts:
        node = ruleset.industry_index[imp.industry]
        for stock, weight in ruleset.industry_members[node]:
            add(stock, imp.delay_ticks, imp.scale_ppm * weight)
    if event.scope == "stock" and event.source_stock_idx is not None:
        # 源股票单独按满幅计，不经暴露度，也不吃行业外溢
        terms[event.source_stock_idx] = {0: PPM * PPM}
    return terms


def build_day_plan(
    day: int, events: Iterable[GameEvent], ruleset: EventRuleset, params: SaveParams
) -> DayPlan:
    """交易日 day 的漂移计划。events 应包含 plan_window(day) 内排期的全部事件。"""
    tpd = ruleset.ticks_per_day
    t0 = day * tpd
    acc: list[dict[int, int]] = [{} for _ in range(tpd)]
    for ev in events:
        p = ev.publish_trading_tick
        max_delay = max((i.delay_ticks for i in ev.impacts), default=0)
        if p + max_delay + ev.knots[-1][0] < t0 or p + ev.knots[0][0] > t0 + tpd - 1:
            continue
        terms = _event_terms(ev, ruleset)
        delays = sorted({d for by in terms.values() for d in by})
        # S_δ 在 tick t0-1 .. t0+19 上的采样（共 21 个点）
        samples = {
            d: [eval_path(ev.knots, t0 - 1 + i - p - d) for i in range(tpd + 1)] for d in delays
        }
        for stock, by_delay in terms.items():
            mb = ev.magnitude_ppm * stock_beta_ppm(ruleset, params, stock)
            cum = [
                round_half_up_div(mb * sum(a * samples[d][i] for d, a in by_delay.items()), DENOM)
                for i in range(tpd + 1)
            ]
            for i in range(tpd):
                step = cum[i + 1] - cum[i]
                if step:
                    acc[i][stock] = acc[i].get(stock, 0) + step
    out: list[dict[int, int]] = []
    for tick_drift in acc:
        clamped: dict[int, int] = {}
        for stock, value in tick_drift.items():
            cap = (
                BULL_BIAS_DRIFT_CAP_PPM[ruleset.clock_rules]
                if ruleset.stocks[stock].profile == "bull_bias"
                else DRIFT_CAP_PPM
            )
            value = max(-cap, min(cap, value))
            if value:
                clamped[stock] = value
        out.append(clamped)
    return tuple(out)


def news_id(event: GameEvent, item: NewsItem) -> str:
    return f"{event.event_id}:{item.stage}"


def news_between(
    events: Sequence[GameEvent], lo_tick: int, hi_tick: int
) -> tuple[tuple[GameEvent, NewsItem], ...]:
    """发布 tick 满足 lo_tick < tick <= hi_tick 的快讯，按 (tick, news_id) 升序。"""
    found = [
        (ev, item) for ev in events for item in ev.news if lo_tick < item.trading_tick <= hi_tick
    ]
    found.sort(key=lambda pair: (pair[1].trading_tick, news_id(*pair)))
    return tuple(found)


def news_at(
    events: Sequence[GameEvent], trading_tick: int
) -> tuple[tuple[GameEvent, NewsItem], ...]:
    return news_between(events, trading_tick - 1, trading_tick)
