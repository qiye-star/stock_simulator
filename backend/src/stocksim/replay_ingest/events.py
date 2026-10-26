"""事件收集、归属、脱敏、排序编号与影响（超额收益）计算（05 §2.6、§3.2）。只用标准库。

来源：手写 ``manual_events``、巨潮公告、东财公司动态、新闻联播、cls 快讯（抓存开始后才有）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

from . import rawstore
from .adjust import round_half_up
from .errors import BuildError
from .reader import RawReader
from .redact import StockMask, find_residuals, mask_text
from .rules import (
    CATEGORY_IMPORTANCE,
    CCTV_BODY_LIMIT,
    EVENT_BODY_LIMIT,
    CninfoRules,
    cctv_hit,
    cctv_keywords,
    classify_title,
)
from .slots import SLOT_ORDER, assign_slot, parse_local, to_utc_iso
from .spec import Spec, Window

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub("", text)


def natural_days(start: str, end: str) -> list[str]:
    """[start, end] 的每个自然日（新闻联播周末也播）。"""
    d, stop = date.fromisoformat(start), date.fromisoformat(end)
    out: list[str] = []
    while d <= stop:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _clip(text: str | None, limit: int) -> str:
    return (text or "").strip()[:limit]


def collect_candidates(
    spec: Spec,
    window: Window,
    reader: RawReader,
    key_of: Mapping[str, str],
    industry_of: Mapping[str, str],
    name_of: Mapping[str, str],
) -> list[dict[str, Any]]:
    """合并各来源，返回未编号、未脱敏的候选事件（含 ``day_idx``/``slot``）。"""
    cal = list(window.calendar)
    first_day = window.start
    last_date = window.dates[-1]
    event_start = window.event_start_date()
    cands: list[dict[str, Any]] = []

    def place(local_date: str, hhmm: str | None, *, cctv: bool = False) -> tuple[int, str] | None:
        slot = assign_slot(local_date, hhmm, cal, cctv=cctv)
        if slot is None:
            return None
        day_idx = window.day_idx(slot[0])
        return day_idx, slot[1]

    def in_range(day_idx: int, *, manual: bool) -> bool:
        lo = -window.lookback if manual else window.day_idx(event_start)
        return lo <= day_idx <= window.play + window.reveal - 1

    # 1. 手写事件
    for ev in spec.manual_events:
        local_date, hhmm = ev["local_time"][:10], ev["local_time"][11:16]
        placed = place(local_date, None if hhmm == "00:00" else hhmm)
        if placed is None or not in_range(placed[0], manual=True):
            raise BuildError(f"手写事件 {ev['id']} 不在关卡窗口内（{ev['local_time']}）")
        codes = ev["codes"]
        cands.append(
            {
                "day_idx": placed[0],
                "slot": placed[1],
                "local_date": local_date,
                "hhmm": None if hhmm == "00:00" else hhmm,
                "source": "manual",
                "kind": ev["kind"],
                "category": ev["category"],
                "scope": "stock" if codes else ("industry" if ev["industries"] else "market"),
                "stock_keys": sorted(key_of[c] for c in codes),
                "industries": sorted(ev["industries"]),
                "importance": ev["importance"],
                "title": ev["title"],
                "title_masked": ev["title_masked"],
                "body": _clip(ev["body"], EVENT_BODY_LIMIT),
                "body_masked": _clip(ev["body_masked"], EVENT_BODY_LIMIT),
                "url": ev["url"],
                "hide_in_masked": ev["hide_in_masked"],
            }
        )

    # 2. 巨潮公告
    cninfo = spec.sources.get("cninfo")
    if cninfo:
        rules = CninfoRules.from_spec(cninfo)
        seen: set[tuple[str, str, str]] = set()
        for code in spec.codes:
            for year, quarter in _quarters(event_start, last_date):
                for row in reader.rows(rawstore.cninfo_path(code, year, quarter)):
                    title = str(row.get("公告标题") or "").strip()
                    stamp = str(row.get("公告时间") or "").strip()
                    if not title or not stamp or rules.is_routine(title):
                        continue
                    local_date, hhmm = parse_local(stamp)
                    if not event_start <= local_date <= last_date:
                        continue
                    dedup = (code, local_date, _norm(title))
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    placed = place(local_date, hhmm)
                    if placed is None or not in_range(placed[0], manual=False):
                        continue
                    category = classify_title(title)
                    cands.append(
                        {
                            "day_idx": placed[0],
                            "slot": placed[1],
                            "local_date": local_date,
                            "hhmm": hhmm,
                            "source": "cninfo",
                            "kind": "announcement",
                            "category": category,
                            "scope": "stock",
                            "stock_keys": [key_of[code]],
                            "industries": [industry_of[code]],
                            "importance": CATEGORY_IMPORTANCE[category],
                            "title": title,
                            "body": "",
                            "url": str(row.get("公告链接") or ""),
                        }
                    )

    # 3. 东财公司动态
    if spec.sources.get("gsrl"):
        codes = set(spec.codes)
        for d in cal[window.i0 - min(10, window.lookback) : window.end]:
            for row in reader.rows(rawstore.gsrl_path(d)):
                code = str(row.get("代码") or "")
                if code not in codes:
                    continue
                placed = place(d, None)
                if placed is None or not in_range(placed[0], manual=False):
                    continue
                etype = str(row.get("事件类型") or "").strip()
                detail = str(row.get("具体事项") or "").strip()
                important = classify_title(f"{etype}{detail}") != "other"
                cands.append(
                    {
                        "day_idx": placed[0],
                        "slot": placed[1],
                        "local_date": d,
                        "hhmm": None,
                        "source": "gsrl",
                        "kind": "company_event",
                        "category": etype or "other",
                        "scope": "stock",
                        "stock_keys": [key_of[code]],
                        "industries": [industry_of[code]],
                        "importance": 2 if important else 1,
                        "title": f"{name_of[code]}：{etype}" if etype else name_of[code],
                        "body": _clip(detail, EVENT_BODY_LIMIT),
                        "url": "",
                    }
                )

    # 4. 新闻联播
    cctv = spec.sources.get("cctv")
    if cctv:
        keywords = cctv_keywords(cctv, sorted({s.industry for s in spec.stocks}))
        for d in natural_days(event_start, last_date):
            for row in reader.rows(rawstore.cctv_path(d)):
                title = str(row.get("title") or "").strip()
                content = str(row.get("content") or "").strip()
                if not title or not cctv_hit(title, content, keywords):
                    continue
                placed = place(d, None, cctv=True)
                if placed is None or not in_range(placed[0], manual=False):
                    continue
                cands.append(
                    {
                        "day_idx": placed[0],
                        "slot": placed[1],
                        "local_date": d,
                        "hhmm": "19:00",
                        "source": "cctv",
                        "kind": "policy",
                        "category": "policy",
                        "scope": "market",
                        "stock_keys": [],
                        "industries": [],
                        "importance": 2,
                        "title": title,
                        "body": _clip(content, CCTV_BODY_LIMIT),
                        "url": "",
                    }
                )

    # 5. cls 快讯（抓存开始以后的关卡才有）
    if spec.sources.get("em_news"):
        raise BuildError("sources.em_news 尚未实现（属于 E5 抓存），请先关闭")
    if spec.sources.get("cls"):
        seen_cls: set[str] = set()
        for d in natural_days(event_start, last_date):
            for row in reader.jsonl(rawstore.cls_path(d)):
                title = str(row.get("标题") or "").strip()
                content = str(row.get("内容") or "").strip()
                pub_date = str(row.get("发布日期") or d)
                pub_time = str(row.get("发布时间") or "")
                key = rawstore.cls_key(pub_date, pub_time, title, content)
                if key in seen_cls or not (title or content):
                    continue
                seen_cls.add(key)
                local_date, hhmm = parse_local(f"{pub_date} {pub_time}".strip())
                if not event_start <= local_date <= last_date:
                    continue
                placed = place(local_date, hhmm)
                if placed is None or not in_range(placed[0], manual=False):
                    continue
                text = f"{title}{content}"
                hit_codes = [c for c in spec.codes if name_of[c] and name_of[c] in text]
                cands.append(
                    {
                        "day_idx": placed[0],
                        "slot": placed[1],
                        "local_date": local_date,
                        "hhmm": hhmm,
                        "source": "cls",
                        "kind": "flash",
                        "category": "flash",
                        "scope": "stock" if hit_codes else "market",
                        "stock_keys": sorted(key_of[c] for c in hit_codes),
                        "industries": [],
                        "importance": 1,
                        "title": title or _clip(content, 40),
                        "body": _clip(content, EVENT_BODY_LIMIT),
                        "url": "",
                    }
                )
    del first_day
    return cands


def _quarters(start: str, end: str) -> list[tuple[int, int]]:
    """覆盖 [start, end] 的 (年, 季) 列表。"""
    ys, ms = int(start[:4]), int(start[5:7])
    ye, me = int(end[:4]), int(end[5:7])
    out: list[tuple[int, int]] = []
    y, q = ys, (ms - 1) // 3 + 1
    while (y, q) <= (ye, (me - 1) // 3 + 1):
        out.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def finalize_events(
    cands: list[dict[str, Any]],
    masks: Sequence[StockMask],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """排序、编号、脱敏，返回 (事件列表, 脱敏残留报告)。``impact``/``sentiment`` 由调用方补。"""
    cands = sorted(
        cands,
        key=lambda c: (
            c["day_idx"],
            SLOT_ORDER[c["slot"]],
            c["source"],
            c["local_date"],
            c["hhmm"] or "",
            c["title"],
            c["url"],
            c["body"],
        ),
    )
    events: list[dict[str, Any]] = []
    report: list[dict[str, str]] = []
    for i, c in enumerate(cands, start=1):
        eid = f"e{i:04d}"
        title_masked = mask_text(c.get("title_masked") or c["title"], masks)
        body_src = c.get("body_masked") or c["body"]
        body_masked = mask_text(body_src, masks) if body_src else ""
        for field, text in (("title_masked", title_masked), ("body_masked", body_masked)):
            for hit in find_residuals(text, masks):
                report.append({"event_id": eid, "field": field, "hit": hit})
        events.append(
            {
                "id": eid,
                "day_idx": c["day_idx"],
                "slot": c["slot"],
                "local_time": (f"{c['local_date']} {c['hhmm']}" if c["hhmm"] else c["local_date"]),
                "published_at": to_utc_iso(c["local_date"], c["hhmm"]),
                "source": c["source"],
                "kind": c["kind"],
                "category": c["category"],
                "scope": c["scope"],
                "stock_keys": c["stock_keys"],
                "industries": c["industries"],
                "importance": c["importance"],
                "title": c["title"],
                "title_masked": title_masked,
                "body": c["body"],
                "body_masked": body_masked,
                "url": c["url"],
                "hide_in_masked": bool(c.get("hide_in_masked", False)),
                "impact": None,
                "sentiment": None,
            }
        )
    report.sort(key=lambda r: (r["event_id"], r["field"], r["hit"]))
    return events, report


def _ret_bp(series: Sequence[int], a: int, b: int) -> Fraction:
    return Fraction((series[b] - series[a]) * 10_000, series[a])


def compute_impact(
    ev: Mapping[str, Any],
    window: Window,
    closes: Mapping[str, Sequence[int]],
    bench: Sequence[int],
    focus_keys: Sequence[str],
) -> dict[str, int | None]:
    """相对基准的超额收益（bp）。基准日：盘前/盘中事件取前一日收盘，盘后事件取当日收盘。

    ``ar_kd`` 为基准日起 k 个交易日后的收盘相对基准日收盘，股票减指数；
    取 ``stock_keys``（空则 focus，再空则全部）的算术平均；窗口末尾不足 k 日时为 None。
    """
    pos = ev["day_idx"] + window.lookback
    base = pos if ev["slot"] == "post_close" else pos - 1
    keys = list(ev["stock_keys"]) or list(focus_keys) or sorted(closes)
    out: dict[str, int | None] = {}
    for name, k in (("ar_1d_bp", 1), ("ar_5d_bp", 5)):
        end = base + k
        if base < 0 or end >= len(bench):
            out[name] = None
            continue
        ars = [_ret_bp(closes[key], base, end) - _ret_bp(bench, base, end) for key in keys]
        out[name] = round_half_up(sum(ars, Fraction(0)) / len(ars))
    return out
