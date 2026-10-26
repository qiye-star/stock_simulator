"""复盘事件流（05 §5.7）。`to_feed_item` 是唯一的 A 快讯适配点，字段名与 A 的 NewsOut 同名。

可见性：`event_visible`（domain）按 (日, 阶段) 过滤；匿名模式去掉 hide_in_masked；
回看期只展示最后 10 日的事件，更早的仅重要度 3（05 §1.2）。
事件顺序固定为 (day_idx, slot 序号, id)；游标为该顺序下的序号，新的在前。
"""

from __future__ import annotations

from typing import Any

from stocksim.domain.replay import (
    PHASE_MINUTE,
    SLOT_VISIBLE_FROM,
    event_visible,
    first_visible_phase,
    phase_index,
    phase_tick,
)
from stocksim.services.replay.pack import PackEvent, ReplayPack
from stocksim.services.replay.state import Ctx, date_label, stock_view

LOOKBACK_EVENT_WINDOW = 10
KIND_MAP = {
    "policy": "policy",
    "announcement": "announcement",
    "company_event": "announcement",
    "news": "news",
    "flash": "news",
}


def ordered_events(pack: ReplayPack) -> list[PackEvent]:
    return sorted(pack.events, key=lambda e: (e.day_idx, SLOT_VISIBLE_FROM[e.slot], e.id))


def is_shown(pack: ReplayPack, e: PackEvent, *, masked: bool, day: int, phase: str) -> bool:
    if masked and e.hide_in_masked:
        return False
    if e.day_idx < -LOOKBACK_EVENT_WINDOW and e.importance < 3:
        return False
    return event_visible(e.day_idx, e.slot, day, phase)


def visible_at(
    pack: ReplayPack, *, masked: bool, day: int, phase: str
) -> list[tuple[int, PackEvent]]:
    """(序号, 事件) 列表，按事件顺序升序；序号即游标。"""
    out: list[tuple[int, PackEvent]] = []
    for i, e in enumerate(ordered_events(pack)):
        if is_shown(pack, e, masked=masked, day=day, phase=phase):
            out.append((i, e))
    return out


def _time_label(local_time: str) -> str | None:
    """'2023-07-05 16:20' -> '16:20'；只有日期（无时刻）返回 None。"""
    if len(local_time) >= 16 and local_time[10] == " ":
        return local_time[11:16]
    return None


def to_feed_item(ev: PackEvent, ctx: Ctx, *, reveal: bool = False) -> dict[str, Any]:
    """事件 -> ReplayFeedItemOut。reveal=True 时给真实标题与正文（揭示页）。"""
    masked = ctx.masked and not reveal
    first = first_visible_phase(ev.slot)
    tick = phase_tick(ev.day_idx, first)
    targets: list[str] = []
    codes: list[tuple[str, str]] = []
    for key in ev.stock_keys:
        stock = ctx.pack.stock(key)
        code, name = stock_view(stock, masked)
        codes.append((code, name))
        targets.append(code)
    targets.extend(ev.industries)
    industry = ev.industries[0] if ev.industries else None
    code, name = codes[0] if codes else (None, None)
    return {
        "news_id": f"replay:{ev.id}",
        "event_id": f"replay:{ev.id}",
        "stage": "publish",
        "kind": KIND_MAP[ev.kind],
        "subtype": None,
        "scope": ev.scope,
        "major": ev.importance == 3,
        "sentiment": None,
        "title": ev.title_masked if masked else ev.title,
        "industry": industry,
        "code": code,
        "stock_name": name,
        "trading_day": ev.day_idx,
        "trading_tick": tick,
        "day_offset": phase_index(first),
        "tick": tick,
        "clock_minute": PHASE_MINUTE[first],
        "slot": ev.slot,
        "time_label": _time_label(ev.local_time),
        "date_label": (
            date_label(ctx, ev.day_idx) if masked else ctx.pack.calendar[ctx.index(ev.day_idx)]
        ),
        "targets": targets,
        "importance": ev.importance,
        "body": ev.body_masked if masked else ev.body,
        "source": ev.source,
        "url": None if masked or not ev.url else ev.url,
    }


def feed_page(
    ctx: Ctx, *, cursor: int | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """当前可见事件，新的在前；cursor 为上一页最后一条的序号（取更小的）。"""
    shown = visible_at(ctx.pack, masked=ctx.masked, day=ctx.day, phase=ctx.phase)
    if cursor is not None:
        shown = [(i, e) for i, e in shown if i < cursor]
    newest_first = list(reversed(shown))
    page = newest_first[:limit]
    next_cursor = str(page[-1][0]) if len(newest_first) > limit and page else None
    return [to_feed_item(e, ctx) for _, e in page], next_cursor


__all__ = [
    "LOOKBACK_EVENT_WINDOW",
    "feed_page",
    "is_shown",
    "ordered_events",
    "to_feed_item",
    "visible_at",
]
