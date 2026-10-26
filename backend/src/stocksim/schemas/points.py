"""积分账本、预测统计与称号的响应模型（02 §10.1–§10.2）。"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class PointsOut(BaseModel):
    balance: int
    lifetime_earned: int
    lifetime_spent: int
    equipped_title: str | None
    today_prediction_points: int
    daily_cap: int


class LedgerEntryOut(BaseModel):
    seq: int
    delta: int
    balance_after: int
    reason: str
    ref: str
    save_id: uuid.UUID | None
    meta: dict[str, Any] | None
    created_at: datetime


class LedgerPageOut(BaseModel):
    items: list[LedgerEntryOut]
    next_cursor: str | None


class CalibrationBinOut(BaseModel):
    lo_pct: int
    hi_pct: int
    n: int
    hits: int
    avg_claimed_pct: int | None
    hit_rate_pct: int | None


class KindStatsOut(BaseModel):
    answered: int
    scored: int
    avg_score: int | None
    avg_baseline: int | None


class RecentCardOut(BaseModel):
    card_id: uuid.UUID
    event_id: str
    settled_at: datetime | None
    avg_score: int | None
    avg_baseline: int | None
    points: int | None


class PredictionStatsOut(BaseModel):
    cards_answered: int
    cards_settled: int
    cards_expired: int
    total_points: int
    by_kind: dict[str, KindStatsOut]
    calibration: list[CalibrationBinOut]
    calibration_error_bp: int | None
    recent: list[RecentCardOut]


class TitleOut(BaseModel):
    id: str
    level: Literal["bronze", "silver", "gold", "legend"]
    unlocked_at: datetime | None


class TitlesOut(BaseModel):
    items: list[TitleOut]
    equipped: str | None


class TitlePutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_id: str | None = None
