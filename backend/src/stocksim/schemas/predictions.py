"""预测卡的请求与响应模型（02 §10.2）。只做形状校验；业务校验在 domain.validate_answers。"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from stocksim.schemas.events import EventOut
from stocksim.schemas.market import ClockOut


class BucketQuestionOut(BaseModel):
    qid: Literal["dir"]
    kind: Literal["bucket"]
    target_kind: Literal["industry", "stock", "market"]
    target: str | None
    target_name: str | None
    edges_bp: list[int]
    from_day: int
    to_day: int


class RankQuestionOut(BaseModel):
    qid: Literal["rank"]
    kind: Literal["rank"]
    k: int
    exclude: str
    candidates: list[str]
    at_day: int


class BinaryQuestionOut(BaseModel):
    qid: Literal["rumor"]
    kind: Literal["binary"]


QuestionOut = Annotated[
    BucketQuestionOut | RankQuestionOut | BinaryQuestionOut, Field(discriminator="kind")
]


class AnswerOut(BaseModel):
    qid: str
    probs: list[int] | None
    order: list[str] | None
    pick: int | None
    claimed_pct: int | None


class QuestionResultOut(BaseModel):
    qid: str
    resolved: bool
    void: bool = False
    outcome_bucket: int | None = None
    change_bp: int | None = None
    true_top: list[str] | None = None
    relevance: dict[str, int] | None = None
    candidate_change_bp: dict[str, int | None] | None = None
    truth: bool | None = None
    score: int | None = None
    uniform_score: int | None = None
    baseline: int | None = None
    points: int | None = None
    hit: bool | None = None


class PredictionCardOut(BaseModel):
    id: uuid.UUID
    save_id: uuid.UUID
    event_id: str
    event: EventOut | None
    status: Literal["open", "answered", "settled", "expired", "void"]
    opened_trading_tick: int
    opened_trading_day: int
    deadline_trading_tick: int
    window_days: int
    questions: list[QuestionOut]
    answers: list[AnswerOut]
    results: list[QuestionResultOut]
    points: int | None
    points_capped: bool
    answered_at: datetime | None
    settled_at: datetime | None
    created_at: datetime


class PredictionCardPageOut(BaseModel):
    items: list[PredictionCardOut]
    next_cursor: str | None


class BucketAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probs: list[StrictInt]


class RankAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: list[str]


class PredictionAnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dir: BucketAnswerIn | None = None
    rank: RankAnswerIn | None = None
    rumor: BucketAnswerIn | None = None


class PredictionAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: PredictionAnswersIn
    resume: bool = True


class PredictionSkipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume: bool = True


class PredictionAnswerOut(BaseModel):
    card: PredictionCardOut
    clock: ClockOut


class PredictionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["pause", "off"]


class PredictionSettingsOut(BaseModel):
    mode: Literal["pause", "off"]
    forced: bool


__all__: list[str] = [
    "AnswerOut",
    "BinaryQuestionOut",
    "BucketAnswerIn",
    "BucketQuestionOut",
    "PredictionAnswerIn",
    "PredictionAnswerOut",
    "PredictionAnswersIn",
    "PredictionCardOut",
    "PredictionCardPageOut",
    "PredictionSettingsIn",
    "PredictionSettingsOut",
    "PredictionSkipIn",
    "QuestionOut",
    "QuestionResultOut",
    "RankAnswerIn",
    "RankQuestionOut",
]
