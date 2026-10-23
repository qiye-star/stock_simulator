"""应用配置，由环境变量或 `backend/.env` 读取（pydantic-settings）。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-insecure-change-me-please"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库：sqlite（默认）/ postgresql+psycopg:// / mysql+pymysql://...charset=utf8mb4
    DATABASE_URL: str = "sqlite:///./data/stocksim.db"
    # 用于对会话 token 做 HMAC；生产环境必须覆盖
    SECRET_KEY: str = Field(default=DEV_SECRET_KEY, min_length=16)
    SESSION_TTL_HOURS: int = Field(default=168, ge=1)
    COOKIE_SECURE: bool = False
    ENABLE_DEBUG_API: bool = False
    # 行情补偿：离线/暂停后最多补推的 tick 数
    TICK_CATCHUP_MAX: int = Field(default=300, ge=1)
    # 每个交易日的 tick 数（legacy 为 20）
    TICKS_PER_TRADING_DAY: int = Field(default=20, ge=1)

    @property
    def uses_dev_secret(self) -> bool:
        return self.SECRET_KEY == DEV_SECRET_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()
