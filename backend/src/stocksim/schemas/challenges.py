"""每日挑战的请求与响应模型（03 §10.2）。字段以本文件为准；前端 typedef 必须与之一致。

约定：金额为整数分；时间为带时区的 datetime（JSON 为 ISO 8601，UTC）；
seed 等大整数在 JSON 中为十进制字符串。ChallengeOut 与 ChallengeRoundOut 不含
end_tt、ends_at、seed、salt、commitment_input（结算前保密，03 §5）。
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from stocksim.schemas.events import EventOut
from stocksim.schemas.predictions import (
    AnswerOut,
    PredictionAnswersIn,
    QuestionOut,
    QuestionResultOut,
)

ChallengeStatus = Literal["scheduled", "running", "settled", "void"]
ChallengePhase = Literal["before", "burst", "hold", "final", "ended"]
RoundStateName = Literal["pending", "burst", "open", "closed", "resolved"]


class ChallengeRoundOut(BaseModel):
    round_index: int
    state: RoundStateName
    resume_at: datetime
    closes_at: datetime
    hold_at: datetime | None  # 未到停顿时刻为 null（03 §5 #8）
    event_id: str | None  # 未到停顿时刻为 null


class EntryResultOut(BaseModel):
    final_equity_cents: int | None
    return_bp: int | None
    forecast_score: int
    trade_score: int
    total_score: int
    rank: int | None
    eligible_count: int
    points_awarded: int


class ChallengeEntryOut(BaseModel):
    entry_id: uuid.UUID
    challenge_id: uuid.UUID
    save_id: uuid.UUID | None  # 玩家存档被清理后为 null（03 §6.3）
    eligible: bool
    joined_at: datetime
    answered_rounds: int
    result: EntryResultOut | None


class ChallengeOut(BaseModel):
    id: uuid.UUID
    challenge_date: date
    status: ChallengeStatus
    phase: ChallengePhase
    round_index: int | None
    rounds_total: int
    schedule_mode: Literal["daily", "compact"]
    starts_at: datetime
    entry_closes_at: datetime
    settle_expected_at: datetime  # 结算时间的上界（03 §5 #8），不是精确的结算时刻
    next_change_at: datetime | None
    server_time: datetime
    tick_ms: int
    clock_rules: Literal["v2"]
    events_ruleset: int
    seed_commitment: str
    commitment_scheme: str
    participant_count: int
    public_trading_tick: int
    rounds: list[ChallengeRoundOut]
    my_entry: ChallengeEntryOut | None


class ChallengeListOut(BaseModel):
    items: list[ChallengeOut]
    next_cursor: str | None


class ChallengeRoundCrowdBucketOut(BaseModel):
    mean_probs: list[int]


class ChallengeRoundCrowdRankOut(BaseModel):
    top3_counts: dict[str, int]


class CrowdOut(BaseModel):
    n: int
    by_qid: dict[str, ChallengeRoundCrowdBucketOut | ChallengeRoundCrowdRankOut]


class ChallengeQuestionResultOut(QuestionResultOut):
    """02 的 QuestionResultOut 加上挑战独有的同伴分信息（03 §8.1）。"""

    peer: int | None = None
    used: Literal["peer", "baseline"] | None = None


class ChallengeRoundCardOut(BaseModel):
    round_index: int
    state: RoundStateName
    event: EventOut | None
    closes_at: datetime
    questions: list[QuestionOut]
    my_answers: list[AnswerOut]
    my_revision: int
    results: list[ChallengeQuestionResultOut]
    my_round_score: int | None
    crowd: CrowdOut | None  # 截止后才出现


class ChallengeRoundListOut(BaseModel):
    items: list[ChallengeRoundCardOut]


class LeaderboardItemOut(BaseModel):
    rank: int
    username: str
    equipped_title: str | None
    total_score: int
    forecast_score: int
    trade_score: int
    return_bp: int | None  # 日榜才有
    answered_rounds: int | None  # 日榜才有
    days_played: int | None  # 周/总榜才有
    is_me: bool


class LeaderboardOut(BaseModel):
    scope: Literal["day", "week", "all"]
    key: str
    board: str
    eligible_count: int
    items: list[LeaderboardItemOut]
    me: LeaderboardItemOut | None
    next_cursor: str | None


class RevealRoundOut(BaseModel):
    round_index: int
    event_id: str
    hold_tt: int
    resolve_tts: dict[str, int]
    resume_at: datetime
    hold_at: datetime
    closes_at: datetime


class RevealOut(BaseModel):
    challenge_id: uuid.UUID
    challenge_date: date
    status: Literal["settled", "void"]
    market_seed: str  # 十进制字符串
    seed_salt: str
    seed_commitment: str
    commitment_input: str
    events_ruleset: int
    clock_rules: Literal["v2"]
    format_version: int
    start_minute: int
    tick_ms: int
    end_tt: int | None  # void 为 null
    rounds: list[RevealRoundOut]
    review_available: bool


class ReviewOut(BaseModel):
    challenge: ChallengeOut
    entry: ChallengeEntryOut
    rounds: list[ChallengeRoundCardOut]
    save_available: bool


class ChallengeAnswerIn(BaseModel):
    """作答请求体（03 §10.1）：与 02 的 PredictionAnswersIn 同形，不含 resume。"""

    model_config = ConfigDict(extra="forbid")
    answers: PredictionAnswersIn


class DebugChallengeEnsureIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # JSON 键为 date（UTC+8 日历日）；字段名避开与类型名 date 冲突
    day: date | None = Field(default=None, alias="date")


class DebugChallengeShiftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: Annotated[StrictInt, Field(ge=1, le=86400)]


__all__ = [
    "ChallengeAnswerIn",
    "ChallengeEntryOut",
    "ChallengeListOut",
    "ChallengeOut",
    "ChallengeQuestionResultOut",
    "ChallengeRoundCardOut",
    "ChallengeRoundListOut",
    "ChallengeRoundOut",
    "CrowdOut",
    "DebugChallengeEnsureIn",
    "DebugChallengeShiftIn",
    "EntryResultOut",
    "LeaderboardItemOut",
    "LeaderboardOut",
    "RevealOut",
    "RevealRoundOut",
    "ReviewOut",
]
