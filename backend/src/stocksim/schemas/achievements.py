"""成就的响应模型。名称与描述由前端 i18n 提供。"""

from datetime import datetime

from pydantic import BaseModel


class AchievementDefOut(BaseModel):
    id: str
    level: str
    category: str
    stat: str
    threshold: int
    hidden: bool
    hidden_reason: str
    op: str


class SaveAchievementOut(BaseModel):
    achievement_id: str
    unlocked_at: datetime
