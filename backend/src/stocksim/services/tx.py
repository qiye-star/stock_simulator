"""事务辅助（02 §1.1）：执行一段记账/状态变更后提交；乐观锁或唯一约束冲突时回滚、刷新对象并重做。

fn 必须每次都从数据库当前状态重新计算（重做时幂等键会命中已提交的流水）。
"""

from collections.abc import Callable, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.errors import AppError


def run_in_transaction[T](
    db: Session,
    fn: Callable[[], T],
    *,
    refresh: Sequence[object] = (),
    attempts: int = 3,
) -> T:
    """执行 fn() 后 commit。

    StaleDataError / IntegrityError 回滚、refresh 后重试；AppError 回滚并上抛；
    最后一次仍冲突则上抛。
    """
    for attempt in range(attempts):
        try:
            result = fn()
            db.commit()
            return result
        except AppError:
            db.rollback()
            raise
        except (StaleDataError, IntegrityError):
            db.rollback()
            for obj in refresh:
                db.refresh(obj)
            if attempt == attempts - 1:
                raise
        except Exception:
            db.rollback()
            raise
    raise AssertionError("unreachable")  # pragma: no cover
