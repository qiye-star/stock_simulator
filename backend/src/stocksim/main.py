"""FastAPI 应用工厂。开发启动见 README；生产用 uvicorn --factory。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import Engine

from stocksim.api.pm_ws import PmHub
from stocksim.api.routers import api_router
from stocksim.core.config import Settings, get_settings
from stocksim.core.errors import register_error_handlers
from stocksim.db.session import make_engine, make_session_factory
from stocksim.domain.challenge.constants import CHALLENGE_ROUNDS
from stocksim.services import intel as intel_service
from stocksim.services import pm_lifecycle as pm_lifecycle
from stocksim.services import predictions as predictions_service
from stocksim.services.challenges import config as challenge_config
from stocksim.services.challenges import hooks as challenge_hooks
from stocksim.services.challenges import policy as challenge_policy
from stocksim.services.challenges import runner as challenge_runner
from stocksim.services.challenges.timeutil import parse_slots
from stocksim.services.replay import levels as replay_levels
from stocksim.services.seed import seed_on_startup

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def _check_challenge_settings(settings: Settings) -> None:
    """每日挑战的启动检查（03 §11.1）：compact 只允许开发/e2e；时段个数须为回合数 + 1。"""
    if settings.CHALLENGE_SCHEDULE == "compact" and not settings.ENABLE_DEBUG_API:
        raise RuntimeError("CHALLENGE_SCHEDULE=compact 仅用于开发/e2e，要求 ENABLE_DEBUG_API=true")
    if settings.CHALLENGE_SCHEDULE == "daily" and len(parse_slots(settings.CHALLENGE_SLOTS)) != (
        CHALLENGE_ROUNDS + 1
    ):
        raise ValueError(f"CHALLENGE_SLOTS 必须恰有 {CHALLENGE_ROUNDS + 1} 个严格递增的时段")


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    """构建应用。测试可注入 settings 与已迁移好的 engine。"""
    settings = settings or get_settings()
    if settings.uses_dev_secret:
        logger.warning("正在使用开发用 SECRET_KEY，生产环境请在 .env 中覆盖")
    _check_challenge_settings(settings)
    if settings.uses_dev_secret and not settings.CHALLENGE_SEED_KEY:
        logger.warning("挑战 seed 可预测：未设 CHALLENGE_SEED_KEY 且 SECRET_KEY 为开发默认值")
    challenge_config.use_settings(settings)
    owns_engine = engine is None
    db_engine = engine if engine is not None else make_engine(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        seed_on_startup(app.state.session_factory)
        # 真实复盘关卡包导入（05 §3.3）：失败只记日志，不阻断启动
        replay_levels.import_bundled_packs(app.state.session_factory, settings)
        # 预测市场 Hub 与 sweeper（04 §8.1）：进程内轮询，PM_BACKGROUND_ENABLED=false 时不启动
        if settings.PM_BACKGROUND_ENABLED:
            app.state.pm_hub.start()
        yield
        await app.state.pm_hub.stop()
        if owns_engine:
            db_engine.dispose()

    app = FastAPI(title="股市模拟器 API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.pm_hub = PmHub(
        app.state.session_factory, poll_ms=settings.PM_POLL_MS, sweep_ms=settings.PM_SWEEP_MS
    )

    register_error_handlers(app)
    # 事件扩展点（01 §1.5–§1.6）：预测卡的发布/reset 钩子与情报卡揭示 provider（幂等）
    predictions_service.register_hooks()
    intel_service.register_hooks()
    # 每日挑战（03 §7.1）：挑战存档不出预测卡（B 的钩子之后注册）；D 的钩子默认为空
    challenge_policy.register()
    challenge_hooks.register_defaults()
    # 预测市场（04 §1.3）：挑战生成时物化市场，作废时作废市场
    challenge_hooks.register_challenge_hooks(
        on_created=pm_lifecycle.materialize, on_revoked=pm_lifecycle.void_challenge
    )
    challenge_runner.reset_throttle()  # 懒触发节流按应用实例重新计时（03 §11.2）
    app.include_router(api_router, prefix=API_PREFIX)
    return app


def run() -> None:
    """`stocksim` 命令行入口：以开发模式启动 uvicorn。"""
    uvicorn.run("stocksim.main:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
