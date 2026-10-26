"""事件时间归属（05 §2.6）：把上海本地时间换算成 ``(交易日, slot)``。只用标准库。

| 情况                                   | 归属                         |
| -------------------------------------- | ---------------------------- |
| 发布日不是交易日                       | 下一交易日 ``pre_open``      |
| 时刻未知（只有日期或 00:00:00）        | 当日 ``pre_open``            |
| t < 09:30                              | 当日 ``pre_open``            |
| 09:30 <= t < 15:00                     | 当日 ``intraday``            |
| t >= 15:00                             | 当日 ``post_close``          |
| 新闻联播（``cctv=True``）              | 当日 ``post_close``；非交易日则下一交易日 ``pre_open`` |
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

SLOTS = ("pre_open", "intraday", "post_close")
SLOT_ORDER = {s: i for i, s in enumerate(SLOTS)}

OPEN_MINUTE = 9 * 60 + 30
CLOSE_MINUTE = 15 * 60
SHANGHAI_OFFSET = timedelta(hours=8)  # 上海无夏令时，固定 UTC+8


def parse_local(text: str) -> tuple[str, str | None]:
    """``"2023-08-27 18:00[:00]"`` / ``"2023-08-27"`` / ``"...T18:00"`` -> (日期, 时刻或 None)。

    ``00:00`` 与 ``00:00:00`` 视为“时刻未知”（巨潮把日期补成零点，05 §2.1）。
    """
    text = text.strip()
    date_part, sep, time_part = text.replace("T", " ").partition(" ")
    datetime.strptime(date_part, "%Y-%m-%d")  # 校验格式
    if not sep or not time_part.strip():
        return date_part, None
    hhmm = time_part.strip()[:5]
    datetime.strptime(hhmm, "%H:%M")
    if hhmm == "00:00":
        return date_part, None
    return date_part, hhmm


def assign_slot(
    local_date: str,
    local_hhmm: str | None,
    trading_days: Sequence[str],
    *,
    cctv: bool = False,
) -> tuple[str, str] | None:
    """返回 ``(交易日 ISO, slot)``；发布日晚于日历末日（找不到下一交易日）返回 None。

    ``trading_days`` 为升序 ISO 日期列表。
    """
    i = bisect_left(trading_days, local_date)
    is_trading = i < len(trading_days) and trading_days[i] == local_date
    if not is_trading:
        return (trading_days[i], "pre_open") if i < len(trading_days) else None
    if cctv:
        return local_date, "post_close"
    if local_hhmm is None:
        return local_date, "pre_open"
    minute = int(local_hhmm[:2]) * 60 + int(local_hhmm[3:5])
    if minute < OPEN_MINUTE:
        return local_date, "pre_open"
    if minute < CLOSE_MINUTE:
        return local_date, "intraday"
    return local_date, "post_close"


def to_utc_iso(local_date: str, local_hhmm: str | None) -> str:
    """上海本地时间 -> UTC ISO（``...Z``）；时刻未知按 00:00 算。"""
    hhmm = local_hhmm or "00:00"
    local = datetime.strptime(f"{local_date} {hhmm}", "%Y-%m-%d %H:%M")
    return (local - SHANGHAI_OFFSET).replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
