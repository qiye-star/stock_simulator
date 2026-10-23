"""股票表种子：把股票池写入 `stocks` 表。幂等，可在每次启动时执行。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from stocksim.models import Stock
from stocksim.services.stocks import stock_pool

logger = logging.getLogger(__name__)


def seed_stock_table(db: Session) -> int:
    """缺失的股票插入，名称/行业变化的更新。返回新插入的行数。"""
    existing = {row.code: row for row in db.scalars(select(Stock))}
    inserted = 0
    for info in stock_pool():
        row = existing.get(info.code)
        if row is None:
            db.add(Stock(id=uuid.uuid4(), code=info.code, name=info.name, industry=info.industry))
            inserted += 1
        elif row.name != info.name or row.industry != info.industry:
            row.name = info.name
            row.industry = info.industry
    db.commit()
    return inserted


def seed_on_startup(session_factory: Callable[[], Session] | sessionmaker[Session]) -> None:
    """应用启动钩子。数据库未迁移或不可用时只记录日志，不阻止启动（/readyz 会报告）。"""
    try:
        with session_factory() as db:
            count = seed_stock_table(db)
        if count:
            logger.info("股票表已写入 %d 条记录", count)
    except SQLAlchemyError:
        logger.exception("股票表种子写入失败，请检查数据库迁移状态")
