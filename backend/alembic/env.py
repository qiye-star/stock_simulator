"""Alembic 迁移环境：连接串来自 `DATABASE_URL`，sqlite 必须 render_as_batch。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

import stocksim.models  # noqa: F401  注册全部表到 metadata
from stocksim.core.config import get_settings
from stocksim.db.base import Base
from stocksim.db.session import make_engine

config = context.config

# 测试或脚本可通过 config.attributes["sqlalchemy.url"] 覆盖连接串
_url = config.attributes.get("sqlalchemy.url") or get_settings().DATABASE_URL
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 复用应用的引擎工厂，保证 sqlite 的 pragma（WAL/foreign_keys）一致
    engine = make_engine(_url)
    try:
        with engine.connect() as connection:
            _do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
