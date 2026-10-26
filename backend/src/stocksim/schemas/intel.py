"""情报卡的请求与响应模型（02 §10.1）。EdgeRevealOut / RumorHintOut 复用 schemas/events.py。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stocksim.schemas.events import EdgeRevealOut, RumorHintOut


class EdgeRevealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str = Field(min_length=1, max_length=40)
    level: Literal[1, 2]


class RumorHintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=r"^e\d{1,9}-\d{1,2}$")


class IntelPrices(BaseModel):
    edge_l1: int
    edge_l2: int
    rumor_hint: int


class IntelStateOut(BaseModel):
    edges: list[EdgeRevealOut]
    rumor_hints: list[RumorHintOut]
    prices: IntelPrices
    daily_limit: int
    used_today: int
    balance: int


class IntelPurchaseOut(BaseModel):
    charged: int
    balance: int
    edge: EdgeRevealOut | None
    hint: RumorHintOut | None
