"""事件生成（01 §4）：``generate_day(seed, day, ruleset, params)`` 是 (seed, day) 的纯函数。

事件不落库、不进行情状态；任何时候都能由 seed 重建。随机只走 rng.rand_below，命名空间与 k 段见
constants.py 的文档字符串。重大事件按周期（12 个交易日）分配，小快讯每个交易日 2-5 条。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..rng import rand_below
from .constants import (
    DAY_META_IDX,
    EVENT_DAY_TICK_BASE,
    IMPULSE_CAP_PPM,
    K_BUILD,
    K_HOLD,
    K_IMPULSE,
    K_KIND,
    K_LEAD,
    K_MAG,
    K_OFFSET,
    K_PRICED_IN,
    K_RECOVER,
    K_RETAIN,
    K_RUMOR_CRED,
    K_RUMOR_DELAY,
    K_RUMOR_TRUTH,
    K_SENTIMENT,
    K_SOURCE,
    K_SOURCE_REDRAW,
    K_TEMPLATE,
    KIND_WEIGHTS_MAJOR,
    KIND_WEIGHTS_MINOR,
    MAG_SCALE_PPM,
    MAJOR_BUILD_TICKS,
    MAJOR_COUNT_PCT,
    MAJOR_HOLD_TICKS,
    MAJOR_IMPULSE_PPM,
    MAJOR_MAG_PPM,
    MAJOR_RECOVER_TICKS,
    MAJOR_RETAIN_PPM,
    MAX_EVENT_SPAN_TICKS,
    MAX_HOPS_MAJOR_INDUSTRY,
    MAX_HOPS_MAJOR_STOCK,
    MAX_HOPS_MINOR_INDUSTRY,
    MAX_HOPS_MINOR_STOCK,
    MINOR_BUILD_TICKS,
    MINOR_COUNT_MIN,
    MINOR_COUNT_SPAN,
    MINOR_HOLD_TICKS,
    MINOR_IMPULSE_PPM,
    MINOR_MAG_PPM,
    MINOR_RECOVER_TICKS,
    MINOR_RETAIN_PPM,
    MINOR_SLOT_BASE,
    PERIOD_META_IDX,
    PICK_K_BASE,
    PRICED_IN_LEAD_TICKS,
    PRICED_IN_PCT,
    REFERENCE_TICKS_PER_DAY,
    RUMOR_CRED_PPM,
    RUMOR_DELAY_TICKS,
    RUMOR_DENY_PCT,
    SOURCE_REDRAWS,
    STOCK_SPILL_MAJOR_PPM,
    STOCK_SPILL_MINOR_PPM,
)
from .news import CONTEXT_SLOTS, pick_count, placeholders
from .path import max_step, priced_in_knots, rumor_knots, surprise_knots
from .propagation import propagate
from .timing import major_period_days, publish_offsets, scale_bounds, scale_magnitude, scale_ticks
from .types import (
    EventRuleset,
    GameEvent,
    NewsItem,
    NodeImpact,
    RumorInfo,
    SaveParams,
    Template,
)

PPM = 1_000_000


def _tick(day: int) -> int:
    return EVENT_DAY_TICK_BASE - day


def _r(seed: int, day: int, idx: int, k: int, n: int) -> int:
    return rand_below(seed, _tick(day), idx, k, n)


def _span(seed: int, day: int, idx: int, k: int, bounds: tuple[int, int]) -> int:
    lo, hi = bounds
    return lo + _r(seed, day, idx, k, hi - lo + 1)


def _weighted(seed: int, day: int, idx: int, k: int, weights: Sequence[int]) -> int:
    """按权重抽下标（权重全 0 抛 ValueError）。"""
    total = sum(weights)
    if total <= 0:
        raise ValueError("no candidates")
    r = _r(seed, day, idx, k, total)
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if r < acc:
            return i
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------- 重大事件周期
def major_days(
    seed: int, period: int, ticks_per_day: int = REFERENCE_TICKS_PER_DAY
) -> tuple[int, ...]:
    """第 period 个周期内重大事件的排期日（绝对交易日，长度 1 或 2，slot 0、1 依次对应）。

    周期长度见 timing.major_period_days：20 tick/日时为 12 日，两条落在不同的日子；
    周期只有 1 日时（如 242 tick/日），两条落在同一日，靠各自的日内偏移错开。
    """
    length = major_period_days(ticks_per_day)
    base = period * length
    u = _r(seed, base, PERIOD_META_IDX, 0, 100)
    n, acc = 0, 0
    for count, pct in enumerate(MAJOR_COUNT_PCT):
        acc += pct
        if u < acc:
            n = count
            break
    j0 = _r(seed, base, PERIOD_META_IDX, 1, length)
    days = [base + j0]
    if n >= 2:
        if length > 1:
            j1 = (j0 + 1 + _r(seed, base, PERIOD_META_IDX, 2, length - 1)) % length
        else:
            j1 = j0
        days.append(base + j1)
    return tuple(days)


def minor_count(seed: int, day: int) -> int:
    return MINOR_COUNT_MIN + _r(seed, day, DAY_META_IDX, 1, MINOR_COUNT_SPAN)


def day_slots(
    seed: int, day: int, ticks_per_day: int = REFERENCE_TICKS_PER_DAY
) -> tuple[tuple[int, bool], ...]:
    """当日的 (slot, major) 列表，按 slot 升序。"""
    length = major_period_days(ticks_per_day)
    slots: list[tuple[int, bool]] = [
        (slot, True)
        for slot, d in enumerate(major_days(seed, day // length, ticks_per_day))
        if d == day
    ]
    slots += [(MINOR_SLOT_BASE + i, False) for i in range(minor_count(seed, day))]
    return tuple(slots)


# ---------------------------------------------------------------- 单个事件
def _pick_template(seed: int, day: int, slot: int, ruleset: EventRuleset, major: bool) -> Template:
    tier = "major" if major else "minor"
    table = KIND_WEIGHTS_MAJOR if major else KIND_WEIGHTS_MINOR
    kinds = [k for k, _ in table]
    weights = [w if ruleset.templates_by_kind_tier.get((k, tier)) else 0 for k, w in table]
    kind = kinds[_weighted(seed, day, slot, K_KIND, weights)]
    pool = ruleset.templates_by_kind_tier[(kind, tier)]
    return pool[_weighted(seed, day, slot, K_TEMPLATE, [t.weight for t in pool])]


def _pick_source(
    seed: int, day: int, slot: int, tmpl: Template, ruleset: EventRuleset, taken: set[int]
) -> tuple[int | None, int | None]:
    """返回 (源行业下标, 源股票下标)。同日已用过的源行业最多重抽 4 次，仍冲突就接受。"""
    if tmpl.scope == "market":
        return None, None
    allowed = (
        list(range(len(ruleset.industries)))
        if tmpl.industries is None
        else [ruleset.industry_index[n] for n in tmpl.industries]
    )
    if tmpl.scope == "industry":
        weights = [ruleset.stock_counts[i] + 2 * ruleset.degree[i] for i in allowed]
    else:
        stock_pool = [s for i in allowed for s in ruleset.industry_stocks[i]]
        if tmpl.industries is None:
            stock_pool = list(range(len(ruleset.stocks)))
    pick_ind = pick_stock = None
    for attempt in range(1 + SOURCE_REDRAWS):
        k = K_SOURCE if attempt == 0 else K_SOURCE_REDRAW + attempt - 1
        if tmpl.scope == "industry":
            pick_ind = allowed[_weighted(seed, day, slot, k, weights)]
        else:
            pick_stock = stock_pool[_r(seed, day, slot, k, len(stock_pool))]
            pick_ind = ruleset.stocks[pick_stock].industry
        if pick_ind not in taken:
            break
    return pick_ind, pick_stock


def _template_pick_names(ruleset: EventRuleset, tmpl: Template) -> list[str]:
    used: set[str] = set()
    for text in (tmpl.title, tmpl.precursor, tmpl.confirm, tmpl.deny):
        if text is None:
            continue
        for value in text.values():
            if value:
                used.update(p for p in placeholders(value) if p not in CONTEXT_SLOTS)
    return [n for n in ruleset.pick_names if n in used]


def generate_event(
    seed: int,
    day: int,
    slot: int,
    major: bool,
    ruleset: EventRuleset,
    params: SaveParams,
    taken: set[int] | None = None,
    taken_offsets: set[int] | None = None,
) -> GameEvent:
    taken = set() if taken is None else taken
    taken_offsets = set() if taken_offsets is None else taken_offsets
    tmpl = _pick_template(seed, day, slot, ruleset, major)
    sentiment = (
        tmpl.sign if tmpl.sign != 0 else (1 if _r(seed, day, slot, K_SENTIMENT, 2) == 1 else -1)
    )
    src_ind, src_stock = _pick_source(seed, day, slot, tmpl, ruleset, taken)
    src_name = None if src_ind is None else ruleset.industries[src_ind]

    # ---- 参数（tick 类区间按 ticks_per_day 换算，20 时恒等）
    tpd = ruleset.ticks_per_day
    mag_bounds = MAJOR_MAG_PPM[tmpl.scope] if major else MINOR_MAG_PPM
    if tmpl.scope != "market":  # market 不随时钟缩放（01 §5.1）
        mag_bounds = scale_magnitude(mag_bounds, MAG_SCALE_PPM[ruleset.clock_rules])
    magnitude = _span(seed, day, slot, K_MAG, mag_bounds)
    # 合法集已排除第 0 日的偏移 0（该 tick 不推进）与 v2 的不接单 tick
    legal = publish_offsets(ruleset.clock_rules, tpd, major, day)
    pos = _r(seed, day, slot, K_OFFSET, len(legal))
    if major:
        # 同一日的两条重大事件（周期只有 1 日时）发布 tick 必须错开，方便预测卡逐条暂停
        for _ in range(len(legal)):
            if legal[pos] not in taken_offsets:
                break
            pos = (pos + 1) % len(legal)
        taken_offsets.add(legal[pos])
    offset = legal[pos]
    build = _span(
        seed,
        day,
        slot,
        K_BUILD,
        scale_bounds(MAJOR_BUILD_TICKS if major else MINOR_BUILD_TICKS, tpd),
    )
    hold = _span(
        seed, day, slot, K_HOLD, scale_bounds(MAJOR_HOLD_TICKS if major else MINOR_HOLD_TICKS, tpd)
    )
    recover = _span(
        seed,
        day,
        slot,
        K_RECOVER,
        scale_bounds(MAJOR_RECOVER_TICKS if major else MINOR_RECOVER_TICKS, tpd),
    )
    retain = _span(
        seed, day, slot, K_RETAIN, MAJOR_RETAIN_PPM[tmpl.kind] if major else MINOR_RETAIN_PPM
    )
    impulse = _span(seed, day, slot, K_IMPULSE, MAJOR_IMPULSE_PPM if major else MINOR_IMPULSE_PPM)
    impulse = min(impulse, IMPULSE_CAP_PPM * PPM // magnitude)
    publish_tick = tpd * day + offset

    # ---- 预期差 / 传闻
    expectation = "surprise"
    lead = 0
    if (
        tmpl.can_price_in
        and tmpl.kind != "rumor"
        and _r(seed, day, slot, K_PRICED_IN, 100) < PRICED_IN_PCT
    ):
        lead = _span(seed, day, slot, K_LEAD, scale_bounds(PRICED_IN_LEAD_TICKS, tpd))
        if publish_tick - lead >= 1:
            expectation = "priced_in"
    rumor: RumorInfo | None = None
    if tmpl.kind == "rumor":
        truth = _r(seed, day, slot, K_RUMOR_TRUTH, 100) >= RUMOR_DENY_PCT
        delay = _span(seed, day, slot, K_RUMOR_DELAY, scale_bounds(RUMOR_DELAY_TICKS, tpd))
        cred = _span(seed, day, slot, K_RUMOR_CRED, RUMOR_CRED_PPM)
        rumor = RumorInfo(
            truth=truth, resolve_trading_tick=publish_tick + delay, credibility_ppm=cred
        )

    # ---- 曲线与幅度上限
    if rumor is not None:
        knots = rumor_knots(
            impulse,
            build,
            hold,
            recover,
            retain,
            rumor.credibility_ppm,
            rumor.resolve_trading_tick - publish_tick,
            rumor.truth,
            tpd,
        )
    elif expectation == "priced_in":
        knots = priced_in_knots(lead, recover)
    else:
        knots = surprise_knots(impulse, build, hold, recover, retain)
    step = max_step(knots)
    if magnitude * step > IMPULSE_CAP_PPM * PPM:
        magnitude = IMPULSE_CAP_PPM * PPM // step

    # ---- 传导
    impacts = _impacts(tmpl, major, src_ind, src_stock, ruleset, params)
    last_tau = knots[-1][0]
    max_span = scale_ticks(MAX_EVENT_SPAN_TICKS, tpd)
    impacts = tuple(i for i in impacts if i.hop == 0 or i.delay_ticks + last_tau <= max_span)

    # ---- 快讯
    news: list[NewsItem] = []
    if expectation == "priced_in":
        news.append(NewsItem("precursor", publish_tick - lead, major, sentiment))
    news.append(NewsItem("publish", publish_tick, major, sentiment))
    if rumor is not None:
        stage = "confirm" if rumor.truth else "deny"
        news.append(
            NewsItem(
                stage, rumor.resolve_trading_tick, major, sentiment if rumor.truth else -sentiment
            )
        )

    # ---- 文案槽位
    picks: list[tuple[str, int]] = []
    for name in _template_pick_names(ruleset, tmpl):
        n = pick_count(ruleset, name, src_name)
        j = ruleset.pick_names.index(name)
        picks.append((name, _r(seed, day, slot, PICK_K_BASE + j, n)))

    if src_ind is not None:
        taken.add(src_ind)
    return GameEvent(
        event_id=f"e{day}-{slot}",
        trading_day=day,
        slot=slot,
        kind=tmpl.kind,
        subtype=tmpl.subtype,
        scope=tmpl.scope,
        source_industry=src_name,
        source_code=None if src_stock is None else ruleset.stocks[src_stock].code,
        major=major,
        sentiment=sentiment,
        channel=tmpl.channel,
        template_id=tmpl.id,
        slot_values=tuple(picks),
        expectation=expectation,
        magnitude_ppm=sentiment * magnitude,
        publish_trading_tick=publish_tick,
        knots=knots,
        rumor=rumor,
        impacts=impacts,
        news=tuple(news),
        source_stock_idx=src_stock,
    )


def _impacts(
    tmpl: Template,
    major: bool,
    src_ind: int | None,
    src_stock: int | None,
    ruleset: EventRuleset,
    params: SaveParams,
) -> tuple[NodeImpact, ...]:
    names = ruleset.industries
    if tmpl.scope == "market":
        return tuple(
            NodeImpact(
                industry=n, hop=0, scale_ppm=w, delay_ticks=0, via_industry=None, relation=None
            )
            for n, w in (tmpl.tilts or ())
        )
    assert src_ind is not None
    if tmpl.scope == "industry":
        hops = MAX_HOPS_MAJOR_INDUSTRY if major else MAX_HOPS_MINOR_INDUSTRY
        return propagate(
            ruleset.out_edges,
            names,
            src_ind,
            tmpl.channel,
            hops,
            edge_jitter=params.edge_jitter_ppm,
            ticks_per_day=ruleset.ticks_per_day,
        )
    spill = STOCK_SPILL_MAJOR_PPM if major else STOCK_SPILL_MINOR_PPM
    hops = MAX_HOPS_MAJOR_STOCK if major else MAX_HOPS_MINOR_STOCK
    assert src_stock is not None
    return propagate(
        ruleset.out_edges,
        names,
        src_ind,
        tmpl.channel,
        hops,
        source_amp_ppm=spill,
        edge_jitter=params.edge_jitter_ppm,
        ticks_per_day=ruleset.ticks_per_day,
    )


def generate_day(
    seed: int, day: int, ruleset: EventRuleset, params: SaveParams
) -> tuple[GameEvent, ...]:
    """交易日 day 排期的全部事件（重大 + 小快讯），按 slot 升序。day 必须 >= 0。"""
    if day < 0:
        raise ValueError("day must be >= 0")
    taken: set[int] = set()
    taken_offsets: set[int] = set()
    return tuple(
        generate_event(seed, day, slot, major, ruleset, params, taken, taken_offsets)
        for slot, major in day_slots(seed, day, ruleset.ticks_per_day)
    )
