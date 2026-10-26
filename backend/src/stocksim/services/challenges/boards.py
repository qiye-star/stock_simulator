"""排行（03 §8.3）：日榜、周榜、总榜。只含公开字段；名次在服务层算（标准竞赛排名 1,2,2,4）。

- 日榜 day_board：挑战 settled 后可看，只含合格报名，按所选分数降序，同分按 username 升序。
- 周榜 / 总榜 period_board：settled 挑战的合格报名 total_score 求和（缺席计 0），附 days_played。
  sort=avg 时按平均分（四舍五入），且只含 days_played ≥ AVG_MIN_DAYS 的用户。
- 游标 = base64url(JSON [score, username])；`me` 为当前用户所在行，不论是否在本页。
- 聚合用 SQL GROUP BY user_id；不用 points.totals_by_user（那是积分流水口径）。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.ranking import iso_week_key
from stocksim.domain.money import round_half_up_div
from stocksim.models import Challenge, ChallengeEntry, PointAccount, User
from stocksim.services.challenges.timeutil import local_date

BOARDS = ("total", "forecast", "trade")
AVG_MIN_DAYS = 5  # sort=avg 的最少出场天数
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
MAX_LIMIT = 100


@dataclass(frozen=True)
class _Row:
    user_id: uuid.UUID
    username: str
    equipped_title: str | None
    total: int
    forecast: int
    trade: int
    return_bp: int | None  # 日榜才有
    answered_rounds: int | None  # 日榜才有
    days_played: int | None  # 周/总榜才有
    score: int  # 排序键（日榜=所选分数，周/总榜=sum 或 avg）
    score_avg: int = 0  # 周/总榜：平均分（四舍五入）


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_LIMIT:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "limit"})


def _encode_cursor(score: int, username: str) -> str:
    raw = json.dumps([score, username], separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        score, username = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if isinstance(score, bool) or not isinstance(score, int) or not isinstance(username, str):
            raise ValueError
        return score, username
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


def _sort_and_rank(rows: list[_Row]) -> tuple[list[_Row], list[int]]:
    """按 (分数降序, username 升序) 排序，并给出标准竞赛排名。"""
    ordered = sorted(rows, key=lambda r: (-r.score, r.username))
    ranks: list[int] = []
    prev_score: int | None = None
    prev_rank = 0
    for i, row in enumerate(ordered):
        if row.score != prev_score:
            prev_rank, prev_score = i + 1, row.score
        ranks.append(prev_rank)
    return ordered, ranks


def _page(
    ordered: Sequence[_Row], ranks: Sequence[int], limit: int, cursor: str | None
) -> tuple[list[tuple[int, _Row]], str | None]:
    start = 0
    if cursor is not None:
        key = _decode_cursor(cursor)
        keys = [(-r.score, r.username) for r in ordered]
        start = bisect_right(keys, (-key[0], key[1]))
    window = [(ranks[i], ordered[i]) for i in range(start, min(start + limit, len(ordered)))]
    more = start + limit < len(ordered)
    next_cursor = _encode_cursor(window[-1][1].score, window[-1][1].username) if more else None
    return window, next_cursor


def _item(rank: int, row: _Row, viewer_id: uuid.UUID | None, *, day: bool) -> dict[str, Any]:
    return {
        "rank": rank,
        "username": row.username,
        "equipped_title": row.equipped_title,
        "total_score": row.total,
        "forecast_score": row.forecast,
        "trade_score": row.trade,
        "return_bp": row.return_bp if day else None,
        "answered_rounds": row.answered_rounds if day else None,
        "days_played": row.days_played,
        "avg_score": None if day else row.score_avg,
        "is_me": viewer_id is not None and row.user_id == viewer_id,
    }


def day_board(
    db: Session,
    ch: Challenge,
    *,
    board: Literal["total", "forecast", "trade"],
    limit: int,
    cursor: str | None,
    viewer_id: uuid.UUID | None,
) -> dict[str, Any]:
    """日榜。未结算返回 409 CHALLENGE_NOT_SETTLED。"""
    if board not in BOARDS:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "board"})
    _check_limit(limit)
    row_ch = db.get(Challenge, ch.id)
    if row_ch is None:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {"challenge_id": str(ch.id)})
    if row_ch.status != "settled":
        raise AppError(ErrorCode.CHALLENGE_NOT_SETTLED, {"challenge_id": str(row_ch.id)})

    score_col = {"total": 0, "forecast": 1, "trade": 2}[board]
    rows: list[_Row] = []
    for uid, name, title, total, forecast, trade, ret, answered in db.execute(
        select(
            ChallengeEntry.user_id,
            User.username,
            PointAccount.equipped_title,
            ChallengeEntry.total_score,
            ChallengeEntry.forecast_score,
            ChallengeEntry.trade_score,
            ChallengeEntry.return_bp,
            ChallengeEntry.answered_rounds,
        )
        .join(User, User.id == ChallengeEntry.user_id)
        .outerjoin(PointAccount, PointAccount.user_id == ChallengeEntry.user_id)
        .where(ChallengeEntry.challenge_id == row_ch.id, ChallengeEntry.eligible.is_(True))
    ).all():
        values = (int(total), int(forecast), int(trade))
        rows.append(
            _Row(
                user_id=uid,
                username=name,
                equipped_title=title,
                total=values[0],
                forecast=values[1],
                trade=values[2],
                return_bp=int(ret) if ret is not None else None,
                answered_rounds=int(answered),
                days_played=None,
                score=values[score_col],
            )
        )
    ordered, ranks = _sort_and_rank(rows)
    window, next_cursor = _page(ordered, ranks, limit, cursor)
    me = _find_me(ordered, ranks, viewer_id, day=True)
    return {
        "scope": "day",
        "key": row_ch.challenge_date.isoformat(),
        "board": board,
        "eligible_count": row_ch.eligible_count,
        "items": [_item(rank, r, viewer_id, day=True) for rank, r in window],
        "me": me,
        "next_cursor": next_cursor,
    }


def period_board(
    db: Session,
    *,
    scope: Literal["week", "all"],
    week: str | None,
    sort: Literal["sum", "avg"],
    limit: int,
    cursor: str | None,
    viewer_id: uuid.UUID | None,
    now: datetime,
) -> dict[str, Any]:
    """周榜（scope=week，ISO 周按 UTC+8 日期）或总榜（scope=all）。"""
    if sort not in ("sum", "avg"):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "sort"})
    if scope not in ("week", "all"):
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "scope"})
    _check_limit(limit)

    stmt = (
        select(
            ChallengeEntry.user_id,
            User.username,
            PointAccount.equipped_title,
            func.sum(ChallengeEntry.total_score),
            func.sum(ChallengeEntry.forecast_score),
            func.sum(ChallengeEntry.trade_score),
            func.count(ChallengeEntry.id),
        )
        .join(Challenge, Challenge.id == ChallengeEntry.challenge_id)
        .join(User, User.id == ChallengeEntry.user_id)
        .outerjoin(PointAccount, PointAccount.user_id == ChallengeEntry.user_id)
        .where(Challenge.status == "settled", ChallengeEntry.eligible.is_(True))
        .group_by(ChallengeEntry.user_id, User.username, PointAccount.equipped_title)
    )
    key: str
    if scope == "week":
        key = week or iso_week_key(local_date(now))
        lo, hi = _week_range(key)
        stmt = stmt.where(Challenge.challenge_date >= lo, Challenge.challenge_date <= hi)
    else:
        key = "all"

    rows: list[_Row] = []
    for uid, name, title, total, forecast, trade, days in db.execute(stmt).all():
        days = int(days)
        total = int(total or 0)
        avg = round_half_up_div(total, days) if days > 0 else 0
        if sort == "avg" and days < AVG_MIN_DAYS:
            continue
        rows.append(
            _Row(
                user_id=uid,
                username=name,
                equipped_title=title,
                total=total,
                forecast=int(forecast or 0),
                trade=int(trade or 0),
                return_bp=None,
                answered_rounds=None,
                days_played=days,
                score=total if sort == "sum" else avg,
                score_avg=avg,
            )
        )
    ordered, ranks = _sort_and_rank(rows)
    window, next_cursor = _page(ordered, ranks, limit, cursor)
    me = _find_me(ordered, ranks, viewer_id, day=False)
    return {
        "scope": scope,
        "key": key,
        "board": sort,
        "eligible_count": len(ordered),
        "items": [_item(rank, r, viewer_id, day=False) for rank, r in window],
        "me": me,
        "next_cursor": next_cursor,
    }


def _find_me(
    ordered: Sequence[_Row], ranks: Sequence[int], viewer_id: uuid.UUID | None, *, day: bool
) -> dict[str, Any] | None:
    if viewer_id is None:
        return None
    for i, row in enumerate(ordered):
        if row.user_id == viewer_id:
            return _item(ranks[i], row, viewer_id, day=day)
    return None


def _week_range(week: str) -> tuple[date, date]:
    """'YYYY-Www' → 周一与周日（ISO 周，UTC+8 日历日）。非法周返回 422。"""
    match = WEEK_RE.match(week)
    if match is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "week"})
    try:
        monday = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "week"}) from exc
    return monday, date.fromordinal(monday.toordinal() + 6)


__all__ = ["AVG_MIN_DAYS", "BOARDS", "day_board", "period_board"]
