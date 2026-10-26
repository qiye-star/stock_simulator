"""真实复盘（模式 E）的请求/响应模型（05 §5.8）。字段名即接口契约，前端 typedef 以此为准。

不含任何真实代码、真实名称（列表与会话）；揭示页（RevealOut）才给真名与真日期。
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from stocksim.schemas.market import CandleOut
from stocksim.schemas.portfolio import EquityPointOut

Phase = Literal["pre_open", "open", "close", "post_close"]
ReplayStatus = Literal["active", "settled"]
QuestionStatus = Literal["open", "answered", "closed", "skipped", "scored"]


class ReplayMyBestOut(BaseModel):
    sessions: int
    settled: int
    best_points: int | None = None
    best_excess_bp: int | None = None


class ReplayLevelOut(BaseModel):
    slug: str
    version: int
    title: str  # 匿名关卡给 title_masked；实名关卡给真实标题
    teaser: str
    title_real: str | None = None  # 仅 masked_allowed=false 时给真实标题
    tags: list[str]
    difficulty: int
    kind: Literal["curated", "generated", "custom"]
    play_days: int
    stock_count: int
    masked_allowed: bool
    my_best: ReplayMyBestOut | None = None


class ReplayLevelPageOut(BaseModel):
    items: list[ReplayLevelOut]
    next_cursor: str | None = None


class ReplayLevelRefOut(BaseModel):
    slug: str
    version: int
    title: str


class ReplaySettledOut(BaseModel):
    final_equity_cents: int | None = None
    return_bp: int | None = None
    benchmark_return_bp: int | None = None
    excess_bp: int | None = None
    points_total: int


class ReplaySessionOut(BaseModel):
    save_id: uuid.UUID
    name: str
    level: ReplayLevelRefOut
    masked: bool
    status: ReplayStatus
    day_idx: int
    play_days: int
    phase: Phase
    tick: int
    date: str  # 真实日期（实名）或假日历日期（匿名）
    date_label: str  # 匿名为 "T+3"，实名为真实日期
    cash_cents: int
    initial_fund_cents: int
    equity_cents: int
    pending_question_ids: list[str]
    open_question_ids: list[str]
    settled: ReplaySettledOut | None = None
    created_at: datetime


class ReplaySessionPageOut(BaseModel):
    items: list[ReplaySessionOut]


class ReplaySessionCreateIn(BaseModel):
    level_slug: str = Field(min_length=1, max_length=48)
    masked: bool = True
    name: str = Field(default="", max_length=20)


class AdvanceIn(BaseModel):
    to: Literal["next_phase", "next_day"] = "next_phase"
    expected_tick: int = Field(ge=0)
    skip_pending: bool = False


class ReplayFeedItemOut(BaseModel):
    """与 A 的 NewsOut（01 §1.4）同名字段，外加复盘字段（05 §5.7）。"""

    news_id: str
    event_id: str
    stage: Literal["publish"]
    kind: Literal["announcement", "news", "policy"]
    subtype: None = None
    scope: Literal["market", "industry", "stock"]
    major: bool
    sentiment: None = None
    title: str
    industry: str | None = None
    code: str | None = None
    stock_name: str | None = None
    trading_day: int
    trading_tick: int
    day_offset: int
    tick: int
    clock_minute: int
    slot: Literal["pre_open", "intraday", "post_close"]
    time_label: str | None = None
    date_label: str
    targets: list[str]
    importance: int
    body: str
    source: str
    url: str | None = None


class ReplayFeedPageOut(BaseModel):
    items: list[ReplayFeedItemOut]
    next_cursor: str | None = None


class AdvanceOut(BaseModel):
    session: ReplaySessionOut
    stale: bool
    stopped_reason: Literal["phase", "question_open", "question_due", "settled"] | None = None
    new_feed_items: list[ReplayFeedItemOut]
    scored_question_ids: list[str]


class ReplayBucketOut(BaseModel):
    label: str
    lo_bp: int | None = None
    hi_bp: int | None = None


class PositionOut(BaseModel):
    day_idx: int
    phase: Phase


class ReplayQuestionResultOut(BaseModel):
    outcome_bucket: int | None = None
    return_bp: int | None = None
    returns_bp: dict[str, int] | None = None
    true_top: list[str] | None = None
    score: int
    points: int


class ReplayQuestionOut(BaseModel):
    id: str
    kind: Literal["direction_bucket", "rank"]
    prompt: str
    codes: list[str]
    buckets: list[ReplayBucketOut] | None = None
    top_k: int | None = None
    opens: PositionOut
    closes: PositionOut
    resolves: PositionOut
    status: QuestionStatus
    my_answer: dict | None = None
    result: ReplayQuestionResultOut | None = None


class ReplayQuestionPageOut(BaseModel):
    items: list[ReplayQuestionOut]


class AnswerIn(BaseModel):
    probs: list[int] | None = Field(default=None, max_length=12)
    order: list[str] | None = Field(default=None, max_length=12)


class BenchmarkPointOut(BaseModel):
    trading_day: int
    date: str
    close: int


class ReplayBenchmarkOut(BaseModel):
    name: str
    points: list[BenchmarkPointOut]


class RevealStockOut(BaseModel):
    code: str  # 会话内代码（匿名时为别名）
    real_code: str
    real_name: str
    industry: str
    candles: list[CandleOut]  # 真实日期的完整 K 线（回看期 + 游戏期 + 揭示期）
    play_range: list[int]


class RevealEventOut(ReplayFeedItemOut):
    impact: dict | None = None  # {ar_1d_bp, ar_5d_bp}：相对基准的超额收益
    sentiment: dict | None = None  # E6 模型情绪；MVP 恒为 null


class RevealOut(BaseModel):
    session: ReplaySessionOut
    commentary: str
    stocks: list[RevealStockOut]
    benchmark: ReplayBenchmarkOut
    events: list[RevealEventOut]
    questions: list[ReplayQuestionOut]
    equity: list[EquityPointOut]
    trades_count: int
    hold_all_return_bp: int
    benchmark_return_bp: int | None = None
