"""应用配置，由环境变量或 `backend/.env` 读取（pydantic-settings）。"""

from functools import lru_cache
from typing import Literal

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
    # 行情补偿：离线/暂停后最多补推的 tick 数（v1 按分钟 tick 计；v2 按交易 tick 计）
    TICK_CATCHUP_MAX: int = Field(default=300, ge=1)
    # v2 停留时长（毫秒）：11:30 午间停留、15:00 收盘小结停留；e2e 可设为 0 加速
    CLOCK_LUNCH_DWELL_MS: int = Field(default=5_000, ge=0, le=600_000)
    CLOCK_CLOSE_DWELL_MS: int = Field(default=15_000, ge=0, le=600_000)

    # 每日挑战（03 §11.1）
    CHALLENGE_ENABLED: bool = True
    # seed 派生密钥（UTF-8）；空则由 SECRET_KEY 派生（见 services/challenges/generate.seed_key）
    CHALLENGE_SEED_KEY: str = ""
    # daily：按 CHALLENGE_SLOTS（北京时间）停顿；compact：仅开发/e2e，要求 ENABLE_DEBUG_API=true
    CHALLENGE_SCHEDULE: Literal["daily", "compact"] = "daily"
    # UTC+8 的时段，个数 = 回合数 + 1，严格递增
    CHALLENGE_SLOTS: str = "07:00,12:00,17:00,20:30,23:00"
    CHALLENGE_TICK_MS: int = Field(default=750, ge=1, le=826)
    CHALLENGE_HOLD_POLL_MS: int = Field(default=5_000, ge=100)
    CHALLENGE_COMPACT_SLOT_SECONDS: int = Field(default=30, ge=10)
    CHALLENGE_COMPACT_TICK_MS: int = Field(default=10, ge=1)
    # 合格门槛：账号创建早于开局这么多小时才合格（e2e 设 0）
    CHALLENGE_MIN_ACCOUNT_AGE_HOURS: int = Field(default=72, ge=0)
    CHALLENGE_PLAYER_RETENTION_DAYS: int = Field(default=14, ge=0)
    CHALLENGE_MARKET_RETENTION_DAYS: int = Field(default=30, ge=0)
    CHALLENGE_RUN_DUE_MIN_INTERVAL_S: int = Field(default=10, ge=0)
    # 预测市场（04 §8.1）：进程内 Hub 轮询与 sweeper；测试关闭后台任务后由用例直接调用
    PM_BACKGROUND_ENABLED: bool = True
    PM_POLL_MS: int = Field(default=1000, ge=100)
    PM_SWEEP_MS: int = Field(default=10_000, ge=100)

    # 真实复盘（05 §5.10）：关卡包目录（空 = 包内 backend/replay/packs）；启动时导入
    REPLAY_PACKS_DIR: str = ""
    REPLAY_IMPORT_ON_STARTUP: bool = True
    MAX_REPLAY_SESSIONS_PER_USER: int = Field(default=10, ge=1)

    @property
    def uses_dev_secret(self) -> bool:
        return self.SECRET_KEY == DEV_SECRET_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()
