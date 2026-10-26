"""事件行情纯函数包（零 I/O）。详见 CLAUDE.md；契约见 docs/10.26-plan/01-事件行情.md。"""

from .constants import EVENT_RULESET_VERSION
from .generate import day_slots, generate_day, generate_event, major_days, minor_count
from .graph import build_out_edges, build_transmission, save_params, stock_beta_ppm
from .news import render_news_title, render_title
from .path import eval_path, max_step
from .plan import (
    DayPlan,
    build_day_plan,
    news_at,
    news_between,
    news_id,
    news_window,
    plan_window,
)
from .propagation import propagate
from .reveal import event_phase, rumor_hint, rumor_status
from .ruleset import build_ruleset
from .types import (
    EventRuleset,
    GameEvent,
    NewsItem,
    NodeImpact,
    RumorInfo,
    SaveParams,
    SupplyEdge,
    Template,
    TransmissionEdge,
)

__all__ = [
    "EVENT_RULESET_VERSION",
    "DayPlan",
    "EventRuleset",
    "GameEvent",
    "NewsItem",
    "NodeImpact",
    "RumorInfo",
    "SaveParams",
    "SupplyEdge",
    "Template",
    "TransmissionEdge",
    "build_day_plan",
    "build_out_edges",
    "build_ruleset",
    "build_transmission",
    "day_slots",
    "eval_path",
    "event_phase",
    "generate_day",
    "generate_event",
    "major_days",
    "max_step",
    "minor_count",
    "news_at",
    "news_between",
    "news_id",
    "news_window",
    "plan_window",
    "propagate",
    "render_news_title",
    "render_title",
    "rumor_hint",
    "rumor_status",
    "save_params",
    "stock_beta_ppm",
]
