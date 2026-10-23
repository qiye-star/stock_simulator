"""自定义列类型：整数分金额、UTC 时间、JSON（postgresql 用 JSONB）。"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class Money(TypeDecorator[int]):
    """金额，底层 BigInteger，单位为**整数分**。拒绝 float/Decimal，防止精度漂移。"""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Money 只接受 int（分），收到 {type(value).__name__}")
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> int | None:
        return None if value is None else int(value)


class UTCDateTime(TypeDecorator[datetime]):
    """DateTime(timezone=True)，写入统一转 UTC；sqlite 读回时补上 UTC 时区。"""

    impl = DateTime
    cache_ok = True

    def __init__(self, timezone: bool = True) -> None:
        super().__init__(timezone=timezone)

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime 必须带时区")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def json_column_type() -> JSON:
    """JSON 列：通用为 JSON，postgresql 下变体为 JSONB。每列调用一次获取新实例。"""
    return JSON().with_variant(JSONB(), "postgresql")
