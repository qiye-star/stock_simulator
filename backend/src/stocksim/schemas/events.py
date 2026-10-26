"""事件行情的响应模型（01 §1.3–§1.7、§8.1）。字段与服务层输出一一对应；只含公开字段。"""

from typing import Literal

from pydantic import BaseModel

Kind = Literal["announcement", "news", "policy", "sudden", "rumor"]
Scope = Literal["stock", "industry", "market"]
Stage = Literal["precursor", "publish", "confirm", "deny"]
Phase = Literal["expected", "active", "settled"]
RumorStatus = Literal["unresolved", "confirmed", "denied"]
Relation = Literal["supply", "demand", "substitute", "same_theme"]
MarkRole = Literal["source", "propagated", "market"]
Hint = Literal["likely_true", "likely_false"]


class NewsOut(BaseModel):
    news_id: str
    event_id: str
    stage: Stage
    kind: Kind
    subtype: str | None
    scope: Scope
    major: bool
    sentiment: Literal[1, -1]
    title: str
    industry: str | None
    code: str | None
    stock_name: str | None
    trading_day: int
    trading_tick: int
    day_offset: int
    tick: int | None
    clock_minute: int | None


class NewsPageOut(BaseModel):
    items: list[NewsOut]
    next_cursor: str | None


class EventOut(BaseModel):
    event_id: str
    trading_day: int
    slot: int
    kind: Kind
    subtype: str | None
    scope: Scope
    source_industry: str | None
    source_code: str | None
    major: bool
    sentiment: Literal[1, -1]
    title: str
    first_seen_trading_tick: int
    publish_trading_tick: int | None
    phase: Phase
    rumor_status: RumorStatus | None
    resolved_trading_tick: int | None


class EventPageOut(BaseModel):
    items: list[EventOut]
    next_cursor: str | None


class PropagationStepOut(BaseModel):
    industry: str
    hop: int
    via_industry: str | None
    relation: Relation | None
    arrived_trading_tick: int
    arrived_trading_day: int
    change_bp: int | None


class EventDetailOut(EventOut):
    news: list[NewsOut]
    propagation: list[PropagationStepOut]


class EventMarkOut(BaseModel):
    event_id: str
    trading_day: int
    trading_tick: int
    role: MarkRole
    major: bool
    kind: Kind
    sentiment: Literal[1, -1]
    title: str


class EventMarksOut(BaseModel):
    code: str
    items: list[EventMarkOut]


class SupplyNodeOut(BaseModel):
    id: str
    layer: int
    stock_count: int
    leaders: list[str]


class SupplyEdgeOut(BaseModel):
    id: str
    from_industry: str
    to_industry: str
    relation: Relation
    sign: Literal[1, -1]
    strength: int | None
    lag_days: int | None
    revealed_level: Literal[0, 1, 2]


class SupplyChainOut(BaseModel):
    ruleset: int
    nodes: list[SupplyNodeOut]
    edges: list[SupplyEdgeOut]


class EdgeRevealOut(BaseModel):
    edge_id: str
    from_industry: str
    to_industry: str
    relation: Relation
    sign: Literal[1, -1]
    strength: int
    lag_days: int | None
    level: Literal[1, 2]


class RumorHintOut(BaseModel):
    event_id: str
    hint: Hint
    accuracy_pct: Literal[80, 100]
