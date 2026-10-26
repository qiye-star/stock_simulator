from __future__ import annotations

import pytest

from stocksim.replay_ingest.slots import assign_slot, parse_local, to_utc_iso

# 2023-08-25 周五 / 08-28 周一；周末不是交易日
CAL = ["2023-08-24", "2023-08-25", "2023-08-28", "2023-08-29"]


@pytest.mark.parametrize(
    ("local_date", "hhmm", "cctv", "expected"),
    [
        ("2023-08-26", "10:00", False, ("2023-08-28", "pre_open")),  # 周六 -> 下一交易日盘前
        ("2023-08-27", None, True, ("2023-08-28", "pre_open")),  # 周日新闻联播 -> 下一交易日盘前
        ("2023-08-25", None, False, ("2023-08-25", "pre_open")),  # 时刻未知 -> 当日盘前
        ("2023-08-25", "09:29", False, ("2023-08-25", "pre_open")),
        ("2023-08-25", "09:30", False, ("2023-08-25", "intraday")),
        ("2023-08-25", "14:59", False, ("2023-08-25", "intraday")),
        ("2023-08-25", "15:00", False, ("2023-08-25", "post_close")),
        ("2023-08-25", "23:10", False, ("2023-08-25", "post_close")),
        ("2023-08-25", None, True, ("2023-08-25", "post_close")),  # 交易日新闻联播 -> 盘后
    ],
)
def test_assign_slot_table(
    local_date: str, hhmm: str | None, cctv: bool, expected: tuple[str, str]
) -> None:
    assert assign_slot(local_date, hhmm, CAL, cctv=cctv) == expected


def test_assign_slot_after_calendar_end_is_none() -> None:
    assert assign_slot("2023-09-02", "10:00", CAL) is None


def test_parse_local_variants() -> None:
    assert parse_local("2023-08-27") == ("2023-08-27", None)
    assert parse_local("2023-08-27 00:00:00") == ("2023-08-27", None)  # 巨潮零点 = 时刻未知
    assert parse_local("2023-08-27 18:00") == ("2023-08-27", "18:00")
    assert parse_local("2023-08-27T18:05:09") == ("2023-08-27", "18:05")
    with pytest.raises(ValueError, match="does not match"):
        parse_local("27/08/2023")


def test_to_utc_iso_shanghai_offset() -> None:
    assert to_utc_iso("2023-08-27", "18:00") == "2023-08-27T10:00:00Z"
    assert to_utc_iso("2023-08-27", None) == "2023-08-26T16:00:00Z"
