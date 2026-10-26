"""关卡包（构建产物，05 §3.2）的模型与一致性校验。

pydantic 模型 `extra="forbid"`：字段与 replay_ingest 构建器的输出逐字段一致。
`check_pack` 做跨字段校验（日历长度、位置范围、题目与事件引用等）。
sha256 对原始 JSON 的规范化形式计算。
"""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from stocksim.domain.replay import PHASES, SLOT_VISIBLE_FROM, phase_tick

FORMAT = "stocksim-replay-pack"
FORMAT_VERSION = 1
ROLES = ("focus", "peer", "upstream", "downstream")
EVENT_KINDS = ("policy", "announcement", "company_event", "news", "flash")
EVENT_SOURCES = ("manual", "cninfo", "gsrl", "cctv", "cls", "em_news")
SCOPES = ("market", "industry", "stock")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackPosition(_Strict):
    day: int
    phase: Literal["pre_open", "open", "close", "post_close"]


class PackBenchmark(_Strict):
    symbol: str
    name: str
    closes_adj: list[int]


class PackStock(_Strict):
    key: str
    real_code: str
    real_name: str
    industry: str
    alias_code: str
    alias_name: str
    mask_scale_ppm: int = Field(ge=1)
    role: Literal["focus", "peer", "upstream", "downstream"]


class PackImpact(_Strict):
    ar_1d_bp: int
    ar_5d_bp: int


class PackEvent(_Strict):
    id: str
    day_idx: int
    slot: Literal["pre_open", "intraday", "post_close"]
    local_time: str
    published_at: str
    source: Literal["manual", "cninfo", "gsrl", "cctv", "cls", "em_news"]
    kind: Literal["policy", "announcement", "company_event", "news", "flash"]
    category: str
    scope: Literal["market", "industry", "stock"]
    stock_keys: list[str]
    industries: list[str]
    importance: int = Field(ge=1, le=3)
    title: str
    title_masked: str
    body: str
    body_masked: str
    url: str
    hide_in_masked: bool
    impact: PackImpact | None = None
    sentiment: dict[str, Any] | None = None


class PackQuestion(_Strict):
    id: str
    kind: Literal["direction_bucket", "rank"]
    opens: PackPosition
    closes: PackPosition
    resolves: PackPosition
    prompt: str
    prompt_masked: str
    answer: dict[str, Any]
    # direction_bucket 专用
    base: str | None = None
    edges_bp: list[int] | None = None
    stock_key: str | None = None
    # rank 专用
    stock_keys: list[str] | None = None
    top_k: int | None = None


class ReplayPack(_Strict):
    format: Literal["stocksim-replay-pack"]
    format_version: Literal[1]
    slug: str
    version: int = Field(ge=1)
    title: str
    title_masked: str
    teaser: str
    teaser_masked: str
    tags: list[str]
    difficulty: int = Field(ge=1, le=3)
    kind: Literal["curated", "generated", "custom"]
    masked_allowed: bool
    calendar: list[str]
    lookback_days: int = Field(ge=1)
    play_days: int = Field(ge=1)
    reveal_days: int = Field(ge=0)
    anchor_date: str
    benchmark: PackBenchmark
    stocks: list[PackStock]
    bars: dict[str, list[list[int]]]
    events: list[PackEvent]
    questions: list[PackQuestion]
    commentary: str
    provenance: dict[str, Any]
    redaction_report: list[dict[str, Any]]

    @property
    def total_days(self) -> int:
        return self.lookback_days + self.play_days + self.reveal_days

    def stock(self, key: str) -> PackStock:
        for s in self.stocks:
            if s.key == key:
                return s
        raise KeyError(key)


def check_pack(pack: ReplayPack) -> None:
    """跨字段校验，失败抛 ValueError（消息给作者看）。"""

    def fail(msg: str) -> None:
        raise ValueError(f"{pack.slug} v{pack.version}: {msg}")

    n = pack.total_days
    if len(pack.calendar) != n:
        fail(f"calendar 长度 {len(pack.calendar)} != {n}")
    if any(b <= a for a, b in itertools.pairwise(pack.calendar)):
        fail("calendar 必须严格递增")
    if pack.calendar[pack.lookback_days - 1] != pack.anchor_date:
        fail("anchor_date 必须是游戏第 0 日的前一交易日")
    if len(pack.benchmark.closes_adj) != n:
        fail("benchmark.closes_adj 长度与 calendar 不一致")

    keys = [s.key for s in pack.stocks]
    if not 2 <= len(keys) <= 12 or len(set(keys)) != len(keys):
        fail("stocks 数量须在 2–12 且 key 唯一")
    for field in ("alias_code", "real_code"):
        values = [getattr(s, field) for s in pack.stocks]
        if len(set(values)) != len(values):
            fail(f"{field} 重复")
    if {s.alias_code for s in pack.stocks} & {s.real_code for s in pack.stocks}:
        fail("别名代码不得与真实代码相同")

    if set(pack.bars) != set(keys):
        fail("bars 的键必须与 stocks 一致")
    for key, rows in pack.bars.items():
        if len(rows) != n:
            fail(f"bars[{key}] 行数 {len(rows)} != {n}")
        for row in rows:
            if len(row) != 7:
                fail(f"bars[{key}] 每行须为 7 项")
            o, h, lo, c, vol, lim, _flags = row
            if min(o, h, lo, c) <= 0 or vol < 0:
                fail(f"bars[{key}] 价格须为正、量非负")
            if not (lo <= o <= h and lo <= c <= h):
                fail(f"bars[{key}] 开高低收关系错误")
            if lim not in (500, 1000, 2000, 3000):
                fail(f"bars[{key}] 涨跌幅 {lim} 不在允许的取值内")

    lo_day, hi_day = -pack.lookback_days, pack.play_days + pack.reveal_days - 1
    ids = [e.id for e in pack.events]
    if len(set(ids)) != len(ids):
        fail("事件 id 重复")
    for e in pack.events:
        if not lo_day <= e.day_idx <= hi_day:
            fail(f"事件 {e.id} 的 day_idx 超出范围")
        if e.slot not in SLOT_VISIBLE_FROM:
            fail(f"事件 {e.id} 的 slot 非法")
        if set(e.stock_keys) - set(keys):
            fail(f"事件 {e.id} 引用了未知股票")

    qids = [q.id for q in pack.questions]
    if len(set(qids)) != len(qids):
        fail("题目 id 重复")
    for q in pack.questions:
        for name, pos in (("opens", q.opens), ("closes", q.closes), ("resolves", q.resolves)):
            if not -pack.lookback_days <= pos.day <= hi_day:
                fail(f"题目 {q.id} 的 {name} 超出范围")
        if not 0 <= q.opens.day < pack.play_days:
            fail(f"题目 {q.id} 的 opens.day 须在游戏期内")
        t_open = phase_tick(q.opens.day, q.opens.phase)
        if (
            not t_open
            <= phase_tick(q.closes.day, q.closes.phase)
            <= phase_tick(q.resolves.day, q.resolves.phase)
        ):
            fail(f"题目 {q.id} 的时点顺序错误")
        if q.kind == "direction_bucket":
            if q.stock_key is None or q.stock_key not in keys or not q.edges_bp:
                fail(f"题目 {q.id} 缺少 stock_key 或 edges_bp")
            edges = q.edges_bp
            if any(b <= a for a, b in itertools.pairwise(edges)):
                fail(f"题目 {q.id} 的 edges_bp 必须严格递增")
            bucket = q.answer.get("bucket")
            if not isinstance(bucket, int) or not 0 <= bucket <= len(edges):
                fail(f"题目 {q.id} 的 answer.bucket 越界")
        else:
            cands = q.stock_keys or []
            if not cands or set(cands) - set(keys) or not q.top_k:
                fail(f"题目 {q.id} 的 stock_keys/top_k 非法")
            if not 1 <= q.top_k <= len(cands):
                fail(f"题目 {q.id} 的 top_k 越界")
            rel = q.answer.get("relevance", {})
            if set(rel) - set(cands):
                fail(f"题目 {q.id} 的相关度引用了候选之外的股票")


def canonical_json(raw: dict[str, Any]) -> bytes:
    """规范化序列化：键排序、紧凑分隔符、UTF-8。sha256 与导入幂等键均基于它。"""
    text = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


def pack_sha256(raw: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(raw)).hexdigest()


def parse_pack(raw: dict[str, Any]) -> ReplayPack:
    """校验并解析；失败抛 pydantic.ValidationError 或 ValueError。"""
    pack = ReplayPack.model_validate(raw)
    check_pack(pack)
    return pack


__all__ = [
    "EVENT_KINDS",
    "EVENT_SOURCES",
    "FORMAT",
    "FORMAT_VERSION",
    "PHASES",
    "ROLES",
    "SCOPES",
    "PackEvent",
    "PackQuestion",
    "PackStock",
    "ReplayPack",
    "canonical_json",
    "check_pack",
    "pack_sha256",
    "parse_pack",
]
