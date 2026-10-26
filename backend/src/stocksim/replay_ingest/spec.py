"""关卡规格（作者手写）的加载与校验，以及“规格 + 日历 -> 窗口”的计算。只用标准库。

规格格式见 docs/10.26-plan/05-真实复盘.md §3.1。
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import SpecError

PHASES = ("pre_open", "open", "close", "post_close")
ROLES = ("focus", "peer", "upstream", "downstream")
EVENT_KINDS = ("policy", "announcement", "company_event", "news", "flash")
QUESTION_KINDS = ("direction_bucket", "rank")
LEVEL_KINDS = ("curated", "generated")
EVENT_LOOKBACK_DAYS = 10  # 非手写事件只收回看期最后 N 个交易日起的（05 §2.6）
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,46}$")
CODE_RE = re.compile(r"^\d{6}$")
QID_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


def check_date(text: Any, field: str) -> str:
    if not isinstance(text, str):
        raise SpecError(f"{field}: 需要 YYYY-MM-DD 字符串")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise SpecError(f"{field}: 日期格式不对 {text!r}") from exc
    return text


def _req_str(d: Mapping[str, Any], key: str, where: str, *, max_len: int | None = None) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise SpecError(f"{where}.{key}: 必须是非空字符串")
    if max_len is not None and len(v) > max_len:
        raise SpecError(f"{where}.{key}: 超过 {max_len} 字")
    return v


def _opt_str(d: Mapping[str, Any], key: str, where: str, default: str = "") -> str:
    v = d.get(key, default)
    if not isinstance(v, str):
        raise SpecError(f"{where}.{key}: 必须是字符串")
    return v


def _int_in(
    d: Mapping[str, Any], key: str, where: str, lo: int, hi: int, default: int | None = None
) -> int:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise SpecError(f"{where}.{key}: 需要 {lo}..{hi} 的整数")
    return v


@dataclass(frozen=True)
class StockSpec:
    code: str
    role: str
    industry: str
    name: str  # 可为空：构建时回退到原始数据里的简称
    redact_terms: tuple[str, ...]


@dataclass(frozen=True)
class Spec:
    slug: str
    title: str
    title_masked: str
    teaser: str
    teaser_masked: str
    tags: tuple[str, ...]
    difficulty: int
    kind: str
    d0: str
    lookback_days: int
    play_days: int
    reveal_days: int
    benchmark_symbol: str
    benchmark_name: str
    masked_allowed: bool
    stocks: tuple[StockSpec, ...]
    sources: Mapping[str, Any]
    manual_events: tuple[dict[str, Any], ...]
    questions: tuple[dict[str, Any], ...]
    commentary: str

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(s.code for s in self.stocks)

    @property
    def total_days(self) -> int:
        return self.lookback_days + self.play_days + self.reveal_days


def load_spec(path: Path | str, *, industries: Collection[str] | None = None) -> Spec:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"规格不是合法 JSON: {exc}") from exc
    return parse_spec(raw, industries=industries)


def parse_spec(raw: Any, *, industries: Collection[str] | None = None) -> Spec:
    """校验并规范化。``industries`` 给定时，股票 ``industry`` 必须属于它（82 个行业标签）。"""
    if not isinstance(raw, dict):
        raise SpecError("规格顶层必须是对象")
    slug = _req_str(raw, "slug", "spec")
    if not SLUG_RE.match(slug):
        raise SpecError("spec.slug: 仅允许小写字母、数字、连字符，≤47 字符")
    masked_allowed = raw.get("masked_allowed", True)
    if not isinstance(masked_allowed, bool):
        raise SpecError("spec.masked_allowed: 必须是布尔值")
    title = _req_str(raw, "title", "spec", max_len=64)
    title_masked = (
        _req_str(raw, "title_masked", "spec", max_len=64)
        if masked_allowed
        else _opt_str(raw, "title_masked", "spec")
    )
    teaser = _req_str(raw, "teaser", "spec", max_len=500)
    teaser_masked = (
        _req_str(raw, "teaser_masked", "spec", max_len=500)
        if masked_allowed
        else _opt_str(raw, "teaser_masked", "spec")
    )
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
        raise SpecError("spec.tags: 必须是字符串列表")
    kind = raw.get("kind", "curated")
    if kind not in LEVEL_KINDS:
        raise SpecError(f"spec.kind: 必须是 {LEVEL_KINDS}")
    d0 = check_date(raw.get("d0"), "spec.d0")
    lookback = _int_in(raw, "lookback_days", "spec", 5, 250, 60)
    play = _int_in(raw, "play_days", "spec", 1, 60, 10)
    reveal = _int_in(raw, "reveal_days", "spec", 0, 60, 10)
    bench = raw.get("benchmark")
    if not isinstance(bench, dict):
        raise SpecError("spec.benchmark: 缺失")
    bsym = _req_str(bench, "symbol", "spec.benchmark")
    bname = _req_str(bench, "name", "spec.benchmark")

    raw_stocks = raw.get("stocks")
    if not isinstance(raw_stocks, list) or not 2 <= len(raw_stocks) <= 12:
        raise SpecError("spec.stocks: 需要 2–12 只股票")
    stocks: list[StockSpec] = []
    for i, s in enumerate(raw_stocks):
        where = f"spec.stocks[{i}]"
        if not isinstance(s, dict):
            raise SpecError(f"{where}: 必须是对象")
        code = _req_str(s, "code", where)
        if not CODE_RE.match(code):
            raise SpecError(f"{where}.code: 需要 6 位数字")
        role = s.get("role", "peer")
        if role not in ROLES:
            raise SpecError(f"{where}.role: 必须是 {ROLES}")
        industry = _req_str(s, "industry", where)
        if industries is not None and industry not in industries:
            raise SpecError(f"{where}.industry: {industry!r} 不是已知行业标签")
        if s.get("is_st", False):
            raise SpecError(f"{where}.is_st: MVP 不收 ST 股（05 Q8）")
        terms = s.get("redact_terms", [])
        if not isinstance(terms, list) or not all(isinstance(t, str) and t for t in terms):
            raise SpecError(f"{where}.redact_terms: 必须是字符串列表")
        stocks.append(StockSpec(code, role, industry, _opt_str(s, "name", where), tuple(terms)))
    codes = [s.code for s in stocks]
    if len(set(codes)) != len(codes):
        raise SpecError("spec.stocks: 代码重复")

    sources = raw.get("sources", {})
    if not isinstance(sources, dict):
        raise SpecError("spec.sources: 必须是对象")
    for k in sources:
        if k not in ("cninfo", "gsrl", "cctv", "cls", "em_news"):
            raise SpecError(f"spec.sources.{k}: 未知来源")

    manual = tuple(
        _parse_manual_event(e, i, set(codes)) for i, e in enumerate(raw.get("manual_events", []))
    )
    ids = [e["id"] for e in manual]
    if len(set(ids)) != len(ids):
        raise SpecError("spec.manual_events: id 重复")
    questions = tuple(
        _parse_question(q, i, set(codes), play, reveal)
        for i, q in enumerate(raw.get("questions", []))
    )
    qids = [q["id"] for q in questions]
    if len(set(qids)) != len(qids):
        raise SpecError("spec.questions: id 重复")
    commentary = _opt_str(raw, "commentary", "spec")
    if len(commentary) > 2000:
        raise SpecError("spec.commentary: 超过 2000 字")
    return Spec(
        slug=slug,
        title=title,
        title_masked=title_masked,
        teaser=teaser,
        teaser_masked=teaser_masked,
        tags=tuple(tags),
        difficulty=_int_in(raw, "difficulty", "spec", 1, 3, 1),
        kind=kind,
        d0=d0,
        lookback_days=lookback,
        play_days=play,
        reveal_days=reveal,
        benchmark_symbol=bsym,
        benchmark_name=bname,
        masked_allowed=masked_allowed,
        stocks=tuple(stocks),
        sources=sources,
        manual_events=manual,
        questions=questions,
        commentary=commentary,
    )


def _parse_manual_event(e: Any, i: int, codes: set[str]) -> dict[str, Any]:
    where = f"spec.manual_events[{i}]"
    if not isinstance(e, dict):
        raise SpecError(f"{where}: 必须是对象")
    out: dict[str, Any] = {"id": _req_str(e, "id", where, max_len=16)}
    lt = _req_str(e, "local_time", where)
    try:
        datetime.strptime(lt.strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise SpecError(f"{where}.local_time: 需要 'YYYY-MM-DD HH:MM'") from exc
    out["local_time"] = lt.strip()[:16]
    kind = e.get("kind", "news")
    if kind not in EVENT_KINDS:
        raise SpecError(f"{where}.kind: 必须是 {EVENT_KINDS}")
    out["kind"] = kind
    out["category"] = _opt_str(e, "category", where, kind)
    out["importance"] = _int_in(e, "importance", where, 1, 3, 3)
    ecodes = e.get("codes", [])
    if not isinstance(ecodes, list) or not set(ecodes) <= codes:
        raise SpecError(f"{where}.codes: 必须是 stocks 里的代码")
    out["codes"] = list(ecodes)
    inds = e.get("industries", [])
    if not isinstance(inds, list) or not all(isinstance(x, str) for x in inds):
        raise SpecError(f"{where}.industries: 必须是字符串列表")
    out["industries"] = list(inds)
    out["title"] = _req_str(e, "title", where)
    out["title_masked"] = _opt_str(e, "title_masked", where)
    out["body"] = _opt_str(e, "body", where)
    out["body_masked"] = _opt_str(e, "body_masked", where)
    out["url"] = _opt_str(e, "url", where)
    hide = e.get("hide_in_masked", False)
    if not isinstance(hide, bool):
        raise SpecError(f"{where}.hide_in_masked: 必须是布尔值")
    out["hide_in_masked"] = hide
    return out


def _check_pos(p: Any, where: str) -> dict[str, Any]:
    if (
        not isinstance(p, dict)
        or isinstance(p.get("day"), bool)
        or not isinstance(p.get("day"), int)
        or p.get("phase") not in PHASES
    ):
        raise SpecError(f"{where}: 需要 {{day:int, phase:{PHASES}}}")
    return {"day": p["day"], "phase": p["phase"]}


def pos_key(p: Mapping[str, Any]) -> tuple[int, int]:
    return p["day"], PHASES.index(p["phase"])


def _parse_question(
    q: Any, i: int, codes: set[str], play_days: int, reveal_days: int
) -> dict[str, Any]:
    where = f"spec.questions[{i}]"
    if not isinstance(q, dict):
        raise SpecError(f"{where}: 必须是对象")
    qid = _req_str(q, "id", where)
    if not QID_RE.match(qid):
        raise SpecError(f"{where}.id: 仅允许字母数字下划线，≤16")
    kind = q.get("kind")
    if kind not in QUESTION_KINDS:
        raise SpecError(f"{where}.kind: 必须是 {QUESTION_KINDS}")
    out: dict[str, Any] = {"id": qid, "kind": kind}
    opens = _check_pos(q.get("opens"), f"{where}.opens")
    closes = _check_pos(q.get("closes"), f"{where}.closes")
    if not 0 <= opens["day"] < play_days:
        raise SpecError(f"{where}.opens.day: 必须落在 [0, {play_days}) 内")
    if pos_key(closes) < pos_key(opens):
        raise SpecError(f"{where}: closes 不能早于 opens")
    if closes["day"] >= play_days:
        raise SpecError(f"{where}.closes.day: 必须落在游戏期内")
    horizon = _int_in(q, "horizon_days", where, 1, 60)
    if opens["day"] + horizon - 1 > play_days + reveal_days - 1:
        raise SpecError(f"{where}: opens.day + horizon_days - 1 超出游戏期 + 揭示期")
    if pos_key(closes) > (opens["day"] + horizon - 1, PHASES.index("close")):
        raise SpecError(f"{where}: closes 晚于 resolves")
    out.update(opens=opens, closes=closes, horizon_days=horizon)
    out["prompt"] = _req_str(q, "prompt", where)
    out["prompt_masked"] = _opt_str(q, "prompt_masked", where)
    if kind == "direction_bucket":
        code = _req_str(q, "code", where)
        if code not in codes:
            raise SpecError(f"{where}.code: 不在 stocks 里")
        if q.get("base", "prev_close") != "prev_close":
            raise SpecError(f"{where}.base: 目前只支持 prev_close")
        edges = q.get("edges_bp", "auto")
        if edges != "auto" and (
            not isinstance(edges, list)
            or len(edges) < 1
            or not all(isinstance(x, int) and not isinstance(x, bool) for x in edges)
            or edges != sorted(set(edges))
        ):
            raise SpecError(f"{where}.edges_bp: 需要 'auto' 或严格升序的整数列表")
        out.update(code=code, base="prev_close", edges_bp=edges)
    else:
        qcodes = q.get("codes")
        top_k = _int_in(q, "top_k", where, 1, 3, 3)
        if (
            not isinstance(qcodes, list)
            or len(set(qcodes)) != len(qcodes)
            or not set(qcodes) <= codes
            or len(qcodes) < top_k
        ):
            raise SpecError(f"{where}.codes: 需要 ≥ top_k 个互不相同且在 stocks 里的代码")
        out.update(codes=list(qcodes), top_k=top_k)
    return out


# ---------- 窗口 ----------


@dataclass(frozen=True)
class Window:
    """完整日历中截出的窗口：回看期 + 游戏期 + 揭示期。"""

    calendar: tuple[str, ...]  # 完整交易日历
    i0: int  # 第 0 日在完整日历中的下标
    lookback: int
    play: int
    reveal: int

    @property
    def start(self) -> int:
        return self.i0 - self.lookback

    @property
    def end(self) -> int:  # 不含
        return self.i0 + self.play + self.reveal

    @property
    def dates(self) -> tuple[str, ...]:
        return self.calendar[self.start : self.end]

    @property
    def anchor_date(self) -> str:
        """T0：第 0 日的前一交易日（复权锚点）。"""
        return self.calendar[self.i0 - 1]

    @property
    def prev_start_date(self) -> str:
        """窗口首日的前一交易日（算首日的除权参考价与涨跌停需要）。"""
        return self.calendar[max(self.start - 1, 0)]

    def day_idx(self, iso_date: str) -> int:
        """交易日 -> 以第 0 日为 0 的下标（回看期为负）。不在日历内会抛 ValueError。"""
        i = bisect_left(self.calendar, iso_date)
        if i >= len(self.calendar) or self.calendar[i] != iso_date:
            raise ValueError(f"{iso_date} 不是交易日")
        return i - self.i0

    def event_start_date(self) -> str:
        """非手写事件的起点：回看期最后 N 个交易日的首日。"""
        return self.calendar[self.i0 - min(EVENT_LOOKBACK_DAYS, self.lookback)]


def compute_window(calendar: Sequence[str], spec: Spec) -> Window:
    cal = tuple(calendar)
    if list(cal) != sorted(set(cal)):
        raise SpecError("交易日历必须升序且无重复")
    i = bisect_left(cal, spec.d0)
    if i >= len(cal) or cal[i] != spec.d0:
        raise SpecError(f"d0 {spec.d0} 不是交易日（或日历未覆盖）")
    if i - spec.lookback_days < 1:
        raise SpecError("日历在回看期之前的数据不足（至少需要多一个交易日）")
    if i + spec.play_days + spec.reveal_days > len(cal):
        raise SpecError("日历在揭示期末之后的数据不足（日历需要刷新，或缩短 reveal_days）")
    return Window(cal, i, spec.lookback_days, spec.play_days, spec.reveal_days)
