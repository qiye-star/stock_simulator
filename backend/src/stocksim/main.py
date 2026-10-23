"""FastAPI 应用工厂。开发启动见 README；生产用 uvicorn --factory。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import Engine

from stocksim.api.routers import api_router
from stocksim.core.config import Settings, get_settings
from stocksim.core.errors import register_error_handlers
from stocksim.db.session import make_engine, make_session_factory
from stocksim.services.seed import seed_on_startup

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    """构建应用。测试可注入 settings 与已迁移好的 engine。"""
    settings = settings or get_settings()
    if settings.uses_dev_secret:
        logger.warning("正在使用开发用 SECRET_KEY，生产环境请在 .env 中覆盖")
    owns_engine = engine is None
    db_engine = engine if engine is not None else make_engine(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        seed_on_startup(app.state.session_factory)
        yield
        if owns_engine:
            db_engine.dispose()

    app = FastAPI(title="股市模拟器 API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)

    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


def run() -> None:
    """`stocksim` 命令行入口：以开发模式启动 uvicorn。"""
    uvicorn.run("stocksim.main:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
