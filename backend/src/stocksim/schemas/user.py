"""用户与偏好设置的响应/请求模型（对应 legacy 的 theme/lang/refreshRate/tutorialCompleted）。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    theme: str
    lang: str
    refresh_rate_ms: int
    tutorial_completed: bool
    created_at: datetime


class MePatch(BaseModel):
    """PATCH /me 的部分更新：只处理请求中显式给出的字段。"""

    theme: Literal["dark", "light", "festival"] | None = None
    lang: Literal["zh-CN", "en-US"] | None = None
    refresh_rate_ms: int | None = Field(default=None, ge=500, le=60000)
    tutorial_completed: bool | None = None
