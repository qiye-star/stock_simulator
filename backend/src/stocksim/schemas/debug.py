"""调试接口请求体（仅 ENABLE_DEBUG_API=true 时可用）。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DebugFundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cash_cents: int = Field(ge=0, le=10_000_000_000_000)


class DebugTimeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minute_of_day: int = Field(ge=0, lt=1440)


class DebugAchievementsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["unlock", "lock", "unlock_all", "clear_all"]
    ids: list[str] = Field(default_factory=list, max_length=200)


class DebugResultOut(BaseModel):
    action: str
    cash_cents: int
    clock_minute: int
    trading_day: int
    changed: int
