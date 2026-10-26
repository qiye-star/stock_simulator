"""事件行情服务（01 §1、§6、§8）：规则集缓存、行情漂移与快讯钩子入口、列表/详情/标记/回放、
产业链结构、情报卡揭示的服务层函数。

保密（01 §1.8）：这里返回的公开对象只含“已发布（或已到达）”的部分；magnitude/knots/expectation/
channel/rumor.truth（揭晓前）/未到达的 impacts/未揭示的 strength、lag 一律不输出。
事件不落库，全部由 (market_seed, events_ruleset, clock_rules, trading_day) 确定性重建。

关闭事件模式的存档：所有公开函数先检查 `save.events_enabled`，为假即抛 EVENTS_DISABLED；
行情推进侧（drift_for / news_for_tick）由 `market._run_ticks` 只在开启时调用。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.clock import (
    CLOCK_RULES_V1,
    CLOCK_RULES_V2,
    TimeBase,
    is_trading_time,
    timebase,
    v2_expected_offset,
    v2_minute_of_offset,
    v2_tick_of,
)
from stocksim.domain.events import (
    EVENT_RULESET_VERSION,
    EventRuleset,
    GameEvent,
    NewsItem,
    SaveParams,
    build_day_plan,
    build_ruleset,
    event_phase,
    generate_day,
    news_at,
    news_between,
    news_window,
    plan_window,
    render_news_title,
    rumor_status,
    save_params,
)
from stocksim.domain.events import rumor_hint as domain_rumor_hint
from stocksim.domain.events.constants import LOOKBACK_DAYS, RUMOR_HINT_ACCURACY_PCT
from stocksim.domain.events.plan import DayPlan
from stocksim.domain.money import BP_DENOMINATOR, round_half_up_div
from stocksim.models import Candle, MarketState, Save, WatchlistItem
from stocksim.services import event_hooks
from stocksim.services.market import current_trading_tick, market_key, reject_replay
from stocksim.services.stocks import get_stock_info

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MAX_SCAN_DAYS = 400  # 单次列表请求最多向前扫描的交易日数（01 §8.1）
SCAN_BACK_DAYS = 3  # 快讯/事件可能早于其排期日：预期差 ≤2 日，传闻揭晓 ≤3 日
SCAN_AHEAD_DAYS = 2  # 预期铺垫可能早于排期日 2 日，故排期日可晚于当前日 2 日
WS_NEWS_PER_FRAME = 20  # WS news 帧最多条数（01 §8.2）
EVENT_ID_RE = re.compile(r"^e(\d{1,9})-(\d{1,2})$")
MARK_ROLES = ("source", "propagated", "market")


# ---------------------------------------------------------------- 规则集与缓存


def _json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def ruleset(
    version: int = EVENT_RULESET_VERSION, clock_rules: int = CLOCK_RULES_V1
) -> EventRuleset:
    """加载并缓存规则集（三份事件数据 + 行业 + 股票池）。时间基由 clock_rules 决定。"""
    return build_ruleset(
        supply_chain=_json("supply_chain.json"),
        exposure=_json("stock_exposure.json"),
        templates=_json("news_templates.json"),
        industries=_json("industries.json"),
        stock_pool=_json("stock_pool.json"),
        version=version,
        clock_rules=clock_rules,
    )


_ruleset = ruleset  # 原私有名的别名（01 §1.10）


@lru_cache(maxsize=256)
def _save_params(seed: int, version: int) -> SaveParams:
    # 存档抖动只依赖行业/股票/边的结构，与时间基无关，因此不带 clock_rules
    return save_params(seed, ruleset(version, CLOCK_RULES_V1))


@lru_cache(maxsize=4096)
def _day_events(seed: int, version: int, clock_rules: int, day: int) -> tuple[GameEvent, ...]:
    return generate_day(seed, day, ruleset(version, clock_rules), _save_params(seed, version))


def day_events(seed: int, version: int, clock_rules: int, day: int) -> tuple[GameEvent, ...]:
    """公开：某种子与规则集下排期日 day 的全部事件（服务端完整对象，含未发布事件）。

    只供挑战的生成、出题与判定使用（03 §4.3、§7.5）；结果绝不能原样外发。
    """
    return _day_events(seed, version, clock_rules, day)


def _build_plan(seed: int, version: int, clock_rules: int, day: int) -> DayPlan:
    rs = ruleset(version, clock_rules)
    events = [e for d in plan_window(day) for e in _day_events(seed, version, clock_rules, d)]
    return build_day_plan(day, events, rs, _save_params(seed, version))


@lru_cache(maxsize=64)  # v1：每个计划约 0.5 MB，64 个够覆盖常用窗口
def _plan_v1(seed: int, version: int, day: int) -> DayPlan:
    return _build_plan(seed, version, CLOCK_RULES_V1, day)


@lru_cache(maxsize=8)  # v2：每个计划约 6 MB（01 §5.6），缓存只留 8 个
def _plan_v2(seed: int, version: int, day: int) -> DayPlan:
    return _build_plan(seed, version, CLOCK_RULES_V2, day)


def _day_plan(seed: int, version: int, clock_rules: int, day: int) -> DayPlan:
    if clock_rules == CLOCK_RULES_V2:
        return _plan_v2(seed, version, day)
    return _plan_v1(seed, version, day)


@dataclass(frozen=True)
class Ctx:
    seed: int
    version: int
    rules: int
    rs: EventRuleset
    tb: TimeBase
    params: SaveParams


def _ctx(save: Save) -> Ctx:
    version = save.events_ruleset or EVENT_RULESET_VERSION
    rules = save.clock_rules
    seed = save.market_seed
    return Ctx(
        seed=seed,
        version=version,
        rules=rules,
        rs=ruleset(version, rules),
        tb=timebase(rules),
        params=_save_params(seed, version),
    )


def _require_enabled(save: Save) -> None:
    if not save.events_enabled:
        raise AppError(ErrorCode.EVENTS_DISABLED, {"save_id": str(save.id)})


def _events_in(c: Ctx, lo_day: int, top_day: int) -> list[GameEvent]:
    """排期日在 [lo_day-3, top_day+2] 内的全部事件（快讯与首见时间可能早于排期日）。"""
    first = max(0, lo_day - SCAN_BACK_DAYS)
    return [
        e
        for d in range(first, top_day + SCAN_AHEAD_DAYS + 1)
        for e in _day_events(c.seed, c.version, c.rules, d)
    ]


# ---------------------------------------------------------------- 行情侧入口（_run_ticks 调用）


def drift_for(save: Save, trading_tick: int) -> Mapping[int, int]:
    """第 trading_tick 个交易 tick 的个股漂移 {stock_idx: ppm}。关闭事件时返回空映射。"""
    if not save.events_enabled:
        return {}
    c = _ctx(save)
    day = c.tb.day_of(trading_tick)
    offset = c.tb.offset_of(trading_tick)
    return _day_plan(c.seed, c.version, c.rules, day)[offset]


def news_for_tick(
    save: Save, trading_tick: int
) -> tuple[tuple[GameEvent, ...], tuple[NewsItem, ...]]:
    """本交易 tick 发布的快讯及其所属事件（钩子上下文用）。"""
    c = _ctx(save)
    day = c.tb.day_of(trading_tick)
    events = [e for d in news_window(day) for e in _day_events(c.seed, c.version, c.rules, d)]
    pairs = news_at(events, trading_tick)
    if not pairs:
        return (), ()
    owners: list[GameEvent] = []
    for ev, _ in pairs:
        if not any(ev is o for o in owners):
            owners.append(ev)
    return tuple(owners), tuple(item for _, item in pairs)


# ---------------------------------------------------------------- 时钟倒推（展示用，01 §6.5）


def clock_of(save: Save, trading_tick: int, cur_tt: int) -> tuple[int, int] | None:
    """交易 tick 对应的 (全局 tick, 游戏分钟)；无法推算时 None。

    v2 且对齐不变量成立时用闭式；否则（v1，或手工改库破坏对齐）从存档当前时钟倒推：
    1440 分钟内恰有 242 个交易分钟，整日可直接跳过。
    """
    if trading_tick < 1 or trading_tick > cur_tt:
        return None
    tb = timebase(save.clock_rules)
    if save.clock_rules == CLOCK_RULES_V2 and v2_expected_offset_ok(save, tb, cur_tt):
        day, offset = tb.day_of(trading_tick), tb.offset_of(trading_tick)
        return v2_tick_of(day, offset), v2_minute_of_offset(offset)
    return _walk_back(save, trading_tick, cur_tt)


def v2_expected_offset_ok(save: Save, tb: TimeBase, cur_tt: int) -> bool:
    return tb.offset_of(cur_tt) == v2_expected_offset(save.clock_minute)


def _walk_back(save: Save, trading_tick: int, cur_tt: int) -> tuple[int, int] | None:
    minute, tick = save.clock_minute, save.tick
    while not is_trading_time(minute):  # 回到最近的交易分钟（对应 cur_tt）
        minute = (minute - 1) % 1440
        tick -= 1
        if tick < 0:
            return None
    gap = cur_tt - trading_tick
    full_days, rem = divmod(gap, 242)
    tick -= 1440 * full_days  # 同一分钟数的 1440 分钟前恰好少 242 个交易分钟
    if tick < 0:
        return None
    found = 0
    while found < rem:
        minute = (minute - 1) % 1440
        tick -= 1
        if tick < 0:
            return None
        if is_trading_time(minute):
            found += 1
    return tick, minute


# ---------------------------------------------------------------- 游标


def _encode_cursor(parts: list[Any]) -> str:
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        tick, ident = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise ValueError
        if not isinstance(ident, str):
            raise ValueError
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc
    return tick, ident


# ---------------------------------------------------------------- 过滤与公开形态


def _check_filters(rs: EventRuleset, code: str | None, industry: str | None) -> None:
    if industry is not None and industry not in rs.industry_index:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "industry"})
    if code is not None and code not in rs.stock_index:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "code"})


def _watch_codes(db: Session, save: Save) -> list[str]:
    return list(
        db.scalars(select(WatchlistItem.stock_code).where(WatchlistItem.save_id == save.id))
    )


def _matches(
    rs: EventRuleset,
    ev: GameEvent,
    *,
    major: bool | None,
    code: str | None,
    industry: str | None,
    watched: list[str] | None,
) -> bool:
    if major is not None and ev.major != major:
        return False
    if industry is not None and ev.source_industry != industry:
        return False
    if code is not None and not _code_relevant(rs, ev, code):
        return False
    return watched is None or any(_code_relevant(rs, ev, c) for c in watched)


def _code_relevant(rs: EventRuleset, ev: GameEvent, code: str) -> bool:
    """code 相关：源股票即该股，或源行业是其主行业，或 scope=market（01 §8.1）。"""
    if ev.scope == "market":
        return True
    if ev.scope == "stock" and ev.source_code == code:
        return True
    info = rs.stocks[rs.stock_index[code]]
    return ev.source_industry == rs.industries[info.industry]


def _first_news(ev: GameEvent) -> NewsItem:
    return min(ev.news, key=lambda n: n.trading_tick)


def _event_dict(c: Ctx, ev: GameEvent, cur: int, lang: str) -> dict[str, Any]:
    published = ev.publish_trading_tick <= cur
    rumor = ev.rumor
    return {
        "event_id": ev.event_id,
        "trading_day": ev.trading_day,
        "slot": ev.slot,
        "kind": ev.kind,
        "subtype": ev.subtype if ev.kind == "announcement" else None,
        "scope": ev.scope,
        "source_industry": ev.source_industry,
        "source_code": ev.source_code,
        "major": ev.major,
        "sentiment": ev.sentiment,
        "title": render_news_title(c.rs, ev, _first_news(ev), lang),
        "first_seen_trading_tick": ev.first_seen_trading_tick,
        "publish_trading_tick": ev.publish_trading_tick if published else None,
        "phase": event_phase(ev, cur),
        "rumor_status": rumor_status(ev, cur),
        "resolved_trading_tick": (
            rumor.resolve_trading_tick
            if rumor is not None and cur >= rumor.resolve_trading_tick
            else None
        ),
    }


def _news_dict(
    c: Ctx, save: Save, ev: GameEvent, item: NewsItem, cur: int, lang: str
) -> dict[str, Any]:
    clock = clock_of(save, item.trading_tick, cur)
    stock_name = None
    if ev.source_stock_idx is not None:
        stock_name = c.rs.stocks[ev.source_stock_idx].name
    return {
        "news_id": f"{ev.event_id}:{item.stage}",
        "event_id": ev.event_id,
        "stage": item.stage,
        "kind": ev.kind,
        "subtype": ev.subtype if ev.kind == "announcement" else None,
        "scope": ev.scope,
        "major": item.major,
        "sentiment": item.sentiment,
        "title": render_news_title(c.rs, ev, item, lang),
        "industry": ev.source_industry,
        "code": ev.source_code,
        "stock_name": stock_name,
        "trading_day": c.tb.day_of(item.trading_tick),
        "trading_tick": item.trading_tick,
        "day_offset": c.tb.offset_of(item.trading_tick),
        "tick": clock[0] if clock else None,
        "clock_minute": clock[1] if clock else None,
    }


# ---------------------------------------------------------------- 快讯 / 事件列表


def _page(
    items: list[tuple[tuple[int, str], Any]], limit: int, lo_day: int, lo_tick: int, key_of
) -> tuple[list[Any], str | None]:
    """items 已按键升序；返回本页与 next_cursor（扫描边界或末项）。"""
    page = [it for _, it in items[:limit]]
    if len(items) > limit:
        tick, ident = key_of(items[limit - 1][1])
        return page, _encode_cursor([tick, ident])
    if lo_day > 0:  # 扫满窗口但条数不够：指向扫描边界，由调用方继续
        return page, _encode_cursor([lo_tick - 1, ""])
    return page, None


def news_list(
    db: Session,
    save: Save,
    *,
    limit: int,
    cursor: str | None,
    major: bool | None,
    code: str | None,
    industry: str | None,
    watchlisted: bool | None,
    lang: str,
) -> dict[str, Any]:
    """快讯列表：按 (trading_tick 降序, news_id 升序) 排序，只含 tick ≤ 当前的快讯。"""
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    _check_filters(c.rs, code, industry)
    cursor_key = _decode_cursor(cursor) if cursor is not None else None
    top = cur if cursor_key is None else min(cur, cursor_key[0])
    lo_day = max(0, c.tb.day_of(top) - MAX_SCAN_DAYS)
    top_day = c.tb.day_of(top)
    lo_tick = c.tb.first_tt(lo_day)
    watched = _watch_codes(db, save) if watchlisted else None

    items: list[tuple[tuple[int, str], tuple[GameEvent, NewsItem]]] = []
    for ev in _events_in(c, lo_day, top_day):
        if not _matches(c.rs, ev, major=major, code=code, industry=industry, watched=watched):
            continue
        for item in ev.news:
            if not lo_tick <= item.trading_tick <= top:
                continue
            key = (-item.trading_tick, f"{ev.event_id}:{item.stage}")
            if cursor_key is not None and key <= (-cursor_key[0], cursor_key[1]):
                continue
            items.append((key, (ev, item)))
    items.sort(key=lambda pair: pair[0])
    page, next_cursor = _page(
        items,
        limit,
        lo_day,
        lo_tick,
        lambda pair: (pair[1].trading_tick, f"{pair[0].event_id}:{pair[1].stage}"),
    )
    return {
        "items": [_news_dict(c, save, ev, item, cur, lang) for ev, item in page],
        "next_cursor": next_cursor,
    }


def events_list(
    db: Session,
    save: Save,
    *,
    limit: int,
    cursor: str | None,
    major: bool | None,
    code: str | None,
    industry: str | None,
    phase: str | None,
    lang: str,
) -> dict[str, Any]:
    """事件列表：按 (first_seen 降序, event_id 升序) 排序，只含 first_seen ≤ 当前的事件。"""
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    _check_filters(c.rs, code, industry)
    cursor_key = _decode_cursor(cursor) if cursor is not None else None
    top = cur if cursor_key is None else min(cur, cursor_key[0])
    top_day = c.tb.day_of(top)
    lo_day = max(0, top_day - MAX_SCAN_DAYS)
    lo_tick = c.tb.first_tt(lo_day)

    items: list[tuple[tuple[int, str], GameEvent]] = []
    for ev in _events_in(c, lo_day, top_day):
        first = ev.first_seen_trading_tick
        if not lo_tick <= first <= top:
            continue
        if not _matches(c.rs, ev, major=major, code=code, industry=industry, watched=None):
            continue
        if phase is not None and event_phase(ev, cur) != phase:
            continue
        key = (-first, ev.event_id)
        if cursor_key is not None and key <= (-cursor_key[0], cursor_key[1]):
            continue
        items.append((key, ev))
    items.sort(key=lambda pair: pair[0])
    page, next_cursor = _page(
        items, limit, lo_day, lo_tick, lambda ev: (ev.first_seen_trading_tick, ev.event_id)
    )
    return {"items": [_event_dict(c, ev, cur, lang) for ev in page], "next_cursor": next_cursor}


def ws_news(
    db: Session, save: Save, after_tt: int, upto_tt: int, lang: str
) -> list[dict[str, Any]]:
    """WS 推送用：发布 tick 在 (after_tt, upto_tt] 内的快讯，按时间升序。"""
    _require_enabled(save)
    if upto_tt <= after_tt:
        return []
    c = _ctx(save)
    evs = _events_in(c, c.tb.day_of(after_tt + 1), c.tb.day_of(upto_tt))
    return [
        _news_dict(c, save, ev, item, upto_tt, lang)
        for ev, item in news_between(evs, after_tt, upto_tt)
    ]


# ---------------------------------------------------------------- 单个事件详情与传导回放


def _find_event(c: Ctx, event_id: str, cur: int) -> GameEvent | None:
    m = EVENT_ID_RE.fullmatch(event_id)
    if m is None:
        return None
    day, slot = int(m.group(1)), int(m.group(2))
    if day > c.tb.day_of(cur) + SCAN_AHEAD_DAYS:
        return None
    for ev in _day_events(c.seed, c.version, c.rules, day):
        if ev.slot == slot:
            return ev
    return None


def industry_change_bp(
    db: Session, save: Save, industry: str, from_day: int, to_day: int
) -> int | None:
    """行业等权平均涨跌幅（bp）：从 from_day-1 的收盘到 to_day 的收盘；to_day 为当日时用现价。

    行业无股票或日期越界（from_day<0、to_day<from_day、to_day 晚于当前日）返回 None。
    """
    c = _ctx(save)
    node = c.rs.industry_index.get(industry)
    if node is None or from_day < 0 or to_day < from_day:
        return None
    members = c.rs.industry_stocks[node]
    cur_day = c.tb.day_of(current_trading_tick(db, save))
    if not members or to_day > cur_day:
        return None
    mk = market_key(save)
    codes = [c.rs.stocks[i].code for i in members]
    wanted = {from_day - 1}
    if to_day < cur_day:
        wanted.add(to_day)
    closes: dict[tuple[str, int], int] = {}
    if wanted - {cur_day}:
        rows = db.execute(
            select(Candle.stock_code, Candle.trading_day, Candle.close_cents).where(
                Candle.save_id == mk,
                Candle.stock_code.in_(codes),
                Candle.trading_day.in_(sorted(wanted - {cur_day})),
            )
        ).all()
        closes = {(code, day): int(close) for code, day, close in rows}
    payload = db.get(MarketState, mk).payload  # 当前价：to_day 为当日时使用

    def close_of(code: str, day: int) -> int | None:
        if day == cur_day:
            return int(payload[code][0])
        return closes.get((code, day))

    changes: list[int] = []
    for code in codes:
        base = close_of(code, from_day - 1)
        last = close_of(code, to_day)
        if base is None or last is None or base <= 0:
            continue
        changes.append(round_half_up_div((last - base) * BP_DENOMINATOR, base))
    if not changes:
        return None
    return round_half_up_div(sum(changes), len(changes))


def _propagation(db: Session, save: Save, c: Ctx, ev: GameEvent, cur: int) -> list[dict[str, Any]]:
    cur_day = c.tb.day_of(cur)
    steps: list[dict[str, Any]] = []
    for imp in ev.impacts:
        arrive = ev.publish_trading_tick + imp.delay_ticks
        if arrive > cur:
            continue  # 只列出已到达的节点（01 §8.1）
        arr_day = c.tb.day_of(arrive)
        steps.append(
            {
                "industry": imp.industry,
                "hop": imp.hop,
                "via_industry": imp.via_industry,
                "relation": imp.relation,
                "arrived_trading_tick": arrive,
                "arrived_trading_day": arr_day,
                "change_bp": industry_change_bp(
                    db, save, imp.industry, arr_day, min(cur_day, arr_day + 2)
                ),
            }
        )
    steps.sort(key=lambda s: (s["arrived_trading_tick"], s["hop"]))
    return steps


def event_out(
    db: Session, save: Save, event_id: str, lang: str, *, at_tt: int | None = None
) -> dict[str, Any] | None:
    """事件的公开简要形态（EventOut，01 §1.10 ③）。事件不存在或尚未首见返回 None。

    at_tt 缺省为当前交易 tick；phase / rumor_status 按该时刻计算。
    """
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    at = cur if at_tt is None else at_tt
    ev = _find_event(c, event_id, cur)
    if ev is None or ev.first_seen_trading_tick > at:
        return None
    return _event_dict(c, ev, at, lang)


def event_detail(db: Session, save: Save, event_id: str, lang: str) -> dict[str, Any]:
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    ev = _find_event(c, event_id, cur)
    # 可见性与 /events 列表一致（01 §1.8：first_seen ≤ 当前）；priced_in 的预期事件只含铺垫快讯，
    # publish_trading_tick 为 null，详情 news 只列已发布的快讯
    if ev is None or ev.first_seen_trading_tick > cur:
        raise AppError(ErrorCode.EVENT_NOT_FOUND, {"event_id": event_id})
    news = sorted(
        (_news_dict(c, save, ev, item, cur, lang) for item in ev.news if item.trading_tick <= cur),
        key=lambda n: (n["trading_tick"], n["news_id"]),
    )
    return {
        **_event_dict(c, ev, cur, lang),
        "news": news,
        "propagation": _propagation(db, save, c, ev, cur),
    }


# ---------------------------------------------------------------- 个股事件标记


def event_marks(db: Session, save: Save, code: str, days: int, lang: str) -> dict[str, Any]:
    """个股的事件标记（01 §8.1）：source / propagated / market，取发布或到达时点，且 ≤ 当前。"""
    _require_enabled(save)
    if get_stock_info(code) is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    cur_day = c.tb.day_of(cur)
    lo_day = max(0, cur_day - days)
    lo_tick = c.tb.first_tt(lo_day)
    stock = c.rs.stocks[c.rs.stock_index[code]]
    own_nodes = {stock.industry} | {n for n, _ in stock.extra}
    main_name = c.rs.industries[stock.industry]

    items: list[tuple[tuple[int, str], dict[str, Any]]] = []
    first_day = max(0, lo_day - LOOKBACK_DAYS)
    for d in range(first_day, cur_day + 1):
        for ev in _day_events(c.seed, c.version, c.rules, d):
            tick, role = _mark_tick(c, ev, code, main_name, own_nodes, cur)
            if tick is None or not lo_tick <= tick <= cur:
                continue
            mark = {
                "event_id": ev.event_id,
                "trading_day": ev.trading_day,
                "trading_tick": tick,
                "role": role,
                "major": ev.major,
                "kind": ev.kind,
                "sentiment": ev.sentiment,
                "title": render_news_title(c.rs, ev, _first_news(ev), lang),
            }
            items.append(((-tick, ev.event_id), mark))
    items.sort(key=lambda pair: pair[0])
    return {"code": code, "items": [m for _, m in items]}


def _mark_tick(
    c: Ctx, ev: GameEvent, code: str, main_name: str, own_nodes: set[int], cur: int
) -> tuple[int | None, str]:
    if ev.scope == "market":
        return (ev.publish_trading_tick, "market") if ev.publish_trading_tick <= cur else (None, "")
    if (ev.scope == "stock" and ev.source_code == code) or ev.source_industry == main_name:
        return (ev.publish_trading_tick, "source") if ev.publish_trading_tick <= cur else (None, "")
    best: int | None = None
    for imp in ev.impacts:
        if imp.hop == 0 or c.rs.industry_index[imp.industry] not in own_nodes:
            continue
        arrive = ev.publish_trading_tick + imp.delay_ticks
        if arrive <= cur and (best is None or arrive < best):
            best = arrive
    return (best, "propagated") if best is not None else (None, "")


# ---------------------------------------------------------------- 产业链结构与揭示（01 §1.6、§1.7）


def supply_chain(db: Session, save: Save) -> dict[str, Any]:
    """产业链结构（静态，关闭事件的存档同样返回）。强度/滞后只对已揭示的边给出。
    复盘存档不提供（决策 16）：leaders 含真实龙头代码，拒绝为 REPLAY_UNSUPPORTED。
    """
    reject_replay(save, "supply_chain")
    rs = ruleset(EVENT_RULESET_VERSION, save.clock_rules)
    levels: Mapping[str, int] = event_hooks.reveal_levels(db, save) if save.events_enabled else {}
    leaders: dict[int, list[str]] = {}
    for s in rs.stocks:
        if s.leader:
            leaders.setdefault(s.industry, []).append(s.code)
    nodes = [
        {
            "id": name,
            "layer": rs.layers[i],
            "stock_count": rs.stock_counts[i],
            "leaders": leaders.get(i, []),
        }
        for i, name in enumerate(rs.industries)
    ]
    edges = []
    for e in rs.edges:
        frm, to = rs.industries[e.from_idx], rs.industries[e.to_idx]
        level = max(0, min(2, int(levels.get(f"{frm}>{to}", 0))))
        edges.append(
            {
                "id": f"{frm}>{to}",
                "from_industry": frm,
                "to_industry": to,
                "relation": e.relation,
                "sign": e.sign,
                "strength": e.strength if level >= 1 else None,
                "lag_days": e.lag_days if level >= 2 else None,
                "revealed_level": level,
            }
        )
    return {"ruleset": EVENT_RULESET_VERSION, "nodes": nodes, "edges": edges}


def reveal_edge(save: Save, edge_id: str, level: int) -> dict[str, Any]:
    """情报卡揭示（服务层函数，B 扣积分后调用）。level=1 揭示强度档位，level=2 加揭示滞后天数。"""
    _require_enabled(save)
    if level not in (1, 2):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "level"})
    rs = ruleset(EVENT_RULESET_VERSION, save.clock_rules)
    edge = rs.edge_by_id(edge_id)
    if edge is None:
        raise AppError(ErrorCode.SUPPLY_EDGE_NOT_FOUND, {"edge_id": edge_id})
    return {
        "edge_id": edge_id,
        "from_industry": rs.industries[edge.from_idx],
        "to_industry": rs.industries[edge.to_idx],
        "relation": edge.relation,
        "sign": edge.sign,
        "strength": edge.strength,
        "lag_days": edge.lag_days if level == 2 else None,
        "level": level,
    }


def rumor_hint(db: Session, save: Save, event_id: str) -> dict[str, Any]:
    """传闻情报提示：未揭晓时 80% 与真值一致；揭晓后返回真值（accuracy_pct=100）。"""
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    ev = _find_event(c, event_id, cur)
    # 可见性与列表 / 详情一致（01 §1.8：first_seen ≤ 当前）。priced_in 的铺垫快讯发布后事件已可见，
    # 此时它不是传闻，应返回 not_rumor 而不是 EVENT_NOT_FOUND；传闻的 first_seen 即发布 tick。
    if ev is None or ev.first_seen_trading_tick > cur:
        raise AppError(ErrorCode.EVENT_NOT_FOUND, {"event_id": event_id})
    if ev.rumor is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "event_id", "reason": "not_rumor"})
    if cur >= ev.rumor.resolve_trading_tick:
        hint = "likely_true" if ev.rumor.truth else "likely_false"
        accuracy = 100
    else:
        hint = domain_rumor_hint(c.seed, ev)
        accuracy = RUMOR_HINT_ACCURACY_PCT
    return {"event_id": event_id, "hint": hint, "accuracy_pct": accuracy}


def events_for_days(
    db: Session,
    save: Save,
    from_day: int,
    to_day: int,
    *,
    include_unpublished: bool = False,
) -> list[GameEvent]:
    """排期日在 [from_day, to_day] 内的服务端完整事件。只有出题/结算才可 include_unpublished=True，
    结果绝不能原样外发。默认只含已正式发布（publish ≤ 当前）的事件。"""
    _require_enabled(save)
    c = _ctx(save)
    cur = current_trading_tick(db, save)
    out: list[GameEvent] = []
    for d in range(max(0, from_day), to_day + 1):
        for ev in _day_events(c.seed, c.version, c.rules, d):
            if include_unpublished or ev.publish_trading_tick <= cur:
                out.append(ev)
    return out


__all__ = [
    "MAX_SCAN_DAYS",
    "WS_NEWS_PER_FRAME",
    "clock_of",
    "day_events",
    "drift_for",
    "event_detail",
    "event_marks",
    "event_out",
    "events_for_days",
    "events_list",
    "industry_change_bp",
    "news_for_tick",
    "news_list",
    "reveal_edge",
    "ruleset",
    "rumor_hint",
    "supply_chain",
    "ws_news",
]
