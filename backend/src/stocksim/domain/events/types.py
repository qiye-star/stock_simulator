"""事件行情的数据类型（01 §1.3、§6.6）。全部不可变；金额/比例一律整数。

``EventRuleset`` 由 ``ruleset.build_ruleset`` 从已解析的 JSON 构造（domain 不读文件）。
``GameEvent`` 是服务端完整形态，任何字段都不得原样经 API 输出（保密规则见 01 §1.8）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Kind = Literal["announcement", "news", "policy", "sudden", "rumor"]
Scope = Literal["stock", "industry", "market"]
Channel = Literal["demand", "cost", "sentiment"]
Relation = Literal["supply", "demand", "substitute", "same_theme"]
Stage = Literal["precursor", "publish", "confirm", "deny"]
Expectation = Literal["surprise", "priced_in"]
Phase = Literal["expected", "active", "settled"]
RumorStatus = Literal["unresolved", "confirmed", "denied"]

LangText = Mapping[str, str | None]  # {"zh-CN": "...", "en-US": None}
Knot = tuple[int, int]  # (τ 相对正式发布的交易 tick, 满幅的 ppm 比例)


@dataclass(frozen=True)
class Template:
    id: str
    kind: str
    subtype: str | None
    scope: str
    tiers: tuple[str, ...]  # "major" / "minor"
    channel: str
    sign: int  # -1 / 0（由 RNG 定）/ 1
    industries: tuple[str, ...] | None  # 源行业白名单，None = 全部
    can_price_in: bool
    weight: int
    tilts: tuple[tuple[str, int], ...] | None  # (行业, 带符号 ppm)，仅 market
    title: LangText
    precursor: LangText | None
    confirm: LangText | None
    deny: LangText | None


@dataclass(frozen=True)
class StockInfo:
    idx: int
    code: str
    name: str
    industry: int  # 行业下标
    profile: str
    leader: bool
    extra: tuple[tuple[int, int], ...]  # (行业下标, 暴露度 ppm)


@dataclass(frozen=True)
class SupplyEdge:
    """supply_chain.json 的一条边（from=上游列，to=下游列），下标为行业下标。"""

    from_idx: int
    to_idx: int
    relation: str
    sign: int
    strength: int
    lag_days: int
    note: str = ""


@dataclass(frozen=True)
class TransmissionEdge:
    """展开后的有向传导边。key=(from_idx, to_idx) 是原始边的标识，用于存档抖动。"""

    src: int
    dst: int
    relation: str
    sign: int
    strength: int
    lag_days: int
    key: tuple[int, int]


@dataclass(frozen=True, eq=False)
class EventRuleset:
    """一个规则集版本的全部静态数据。eq=False：按身份比较/哈希，可作 lru_cache 参数。"""

    version: int
    industries: tuple[str, ...]
    industry_index: Mapping[str, int]
    layers: tuple[int, ...]
    stock_counts: tuple[int, ...]
    stocks: tuple[StockInfo, ...]
    stock_index: Mapping[str, int]
    industry_stocks: tuple[tuple[int, ...], ...]  # 主行业成分股下标
    industry_members: tuple[tuple[tuple[int, int], ...], ...]  # (股票下标, 暴露度 ppm)，含 extra
    edges: tuple[SupplyEdge, ...]
    out_edges: tuple[tuple[TransmissionEdge, ...], ...]
    degree: tuple[int, ...]
    templates: tuple[Template, ...]
    templates_by_kind_tier: Mapping[tuple[str, str], tuple[Template, ...]]
    template_index: Mapping[str, Template]
    slot_options: Mapping[
        str, tuple[LangText, ...]
    ]  # 键如 "region" / "product@新能源" / "product@*"
    pick_names: tuple[str, ...]  # 文案槽位名（排序），下标 j 对应 k=100+j
    default_beta_ppm: int = 1_000_000
    leader_beta_ppm: int = 1_200_000
    ticks_per_day: int = 20  # 每交易日 tick 数；所有 tick 常量据此换算（timing.py）
    clock_rules: int = 1  # 时钟规则版本（domain.clock.CLOCK_RULES_*）：按版本取的 v2 常量据此选择

    def edge_by_id(self, edge_id: str) -> SupplyEdge | None:
        for e in self.edges:
            if f"{self.industries[e.from_idx]}>{self.industries[e.to_idx]}" == edge_id:
                return e
        return None


@dataclass(frozen=True)
class SaveParams:
    """按存档（seed）抖动的参数。"""

    beta_jitter_ppm: tuple[int, ...]  # 每只股票一个
    edge_jitter_ppm: Mapping[tuple[int, int], int]  # (from_idx, to_idx) -> ppm


@dataclass(frozen=True)
class RumorInfo:
    truth: bool
    resolve_trading_tick: int
    credibility_ppm: int


@dataclass(frozen=True)
class NodeImpact:
    industry: str
    hop: int
    scale_ppm: int  # 相对源节点满幅的带符号比例
    delay_ticks: int  # 相对源节点的累计延迟
    via_industry: str | None
    relation: str | None


@dataclass(frozen=True)
class NewsItem:
    stage: str
    trading_tick: int
    major: bool
    sentiment: int


@dataclass(frozen=True)
class GameEvent:
    event_id: str
    trading_day: int
    slot: int
    kind: str
    subtype: str | None
    scope: str
    source_industry: str | None
    source_code: str | None
    major: bool
    sentiment: int
    channel: str
    template_id: str
    slot_values: tuple[tuple[str, int], ...]
    expectation: str
    magnitude_ppm: int
    publish_trading_tick: int
    knots: tuple[Knot, ...]
    rumor: RumorInfo | None
    impacts: tuple[NodeImpact, ...]
    news: tuple[NewsItem, ...]
    source_stock_idx: int | None = None

    @property
    def first_seen_trading_tick(self) -> int:
        return min(n.trading_tick for n in self.news)

    @property
    def lifetime_end_tick(self) -> int:
        """源节点曲线走完的交易 tick。"""
        return self.publish_trading_tick + self.knots[-1][0]
