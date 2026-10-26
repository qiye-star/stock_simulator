"""挑战的时间工具（03 §7.1）。

挑战逻辑取“当前时间”只经 `now()`：测试 monkeypatch 本模块的 `now` 即可统一控制时间。
时区一律固定 UTC+8 偏移（中国无夏令时），不用 zoneinfo（部署镜像不保证 tzdata）。
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

from stocksim.db.base import utcnow
from stocksim.domain.challenge.constants import UTC_OFFSET_MINUTES
from stocksim.domain.challenge.ranking import iso_week_key

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
LOCAL_OFFSET = timedelta(minutes=UTC_OFFSET_MINUTES)


def now() -> datetime:
    """当前 UTC 时间（带时区）。挑战所有时间判断的唯一来源。"""
    return utcnow()


def to_ms(value: datetime) -> int:
    """aware datetime → epoch 毫秒（整数）。naive 时间抛 ValueError。"""
    if value.tzinfo is None:
        raise ValueError("naive datetime")
    return (value - EPOCH) // timedelta(milliseconds=1)


def from_ms(ms: int) -> datetime:
    return EPOCH + timedelta(milliseconds=ms)


def local_date(at: datetime) -> date:
    """UTC+8 日历日（挑战的 challenge_date 口径）。"""
    return (at.astimezone(UTC) + LOCAL_OFFSET).date()


def slot_to_utc(day: date, hhmm: str) -> datetime:
    """UTC+8 日历日 day 的 'HH:MM' 时刻换算为 UTC。"""
    hour, minute = parse_hhmm(hhmm)
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
    return local - LOCAL_OFFSET


def parse_hhmm(text: str) -> tuple[int, int]:
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"invalid slot {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"invalid slot {text!r}")
    return hour, minute


def parse_slots(text: str) -> tuple[str, ...]:
    """解析 CHALLENGE_SLOTS：逗号分隔的 HH:MM，要求严格递增（配置校验用）。"""
    slots = tuple(p.strip() for p in text.split(",") if p.strip())
    minutes = [parse_hhmm(s)[0] * 60 + parse_hhmm(s)[1] for s in slots]
    if not slots or any(b <= a for a, b in itertools.pairwise(minutes)):
        raise ValueError("CHALLENGE_SLOTS must be strictly increasing HH:MM list")
    return slots


def ceil_5s(at: datetime) -> datetime:
    """向上取整到 5 秒边界（compact 模式的开局对齐）。"""
    step = 5_000
    ms = to_ms(at)
    return from_ms(-(-ms // step) * step)


def iso_week(day: date) -> str:
    """ISO 周键 'YYYY-Www'，入参为 UTC+8 日历日。"""
    return iso_week_key(day)
