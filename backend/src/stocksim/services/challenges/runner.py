"""每日挑战的触发与维护（03 §11.2、§6.3）。

- run_due(session_factory, now)：六步（生成 → 开始 → 推进 → 关闭钩子 → 结算 → 清理），
  每步独立短事务，全部幂等；单步失败记日志并计入 RunReport.errors，不影响其它步。
- maybe_run_due(db_or_factory, now)：懒触发，进程内 time.monotonic 节流
  （CHALLENGE_RUN_DUE_MIN_INTERVAL_S），失败只记日志、不抛。
- CHALLENGE_ENABLED=false 时 run_due 空转。

domain 禁止 time 模块，节流在本服务层。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from stocksim.core.config import Settings
from stocksim.db.session import make_session_factory
from stocksim.domain.challenge.constants import CHALLENGE_CLOSE_LEAD_MS
from stocksim.models import Challenge, ChallengeEntry, ChallengeRound, Save
from stocksim.models.save import SAVE_MODE_CHALLENGE, SAVE_MODE_CHALLENGE_MARKET
from stocksim.services.challenges import generate, hooks, registry, settle, sync
from stocksim.services.challenges.config import current_settings
from stocksim.services.challenges.timeutil import (
    LOCAL_OFFSET,
    local_date,
    parse_slots,
    slot_to_utc,
    to_ms,
)

logger = logging.getLogger(__name__)

CLEANUP_BATCH = 50  # 每次 run_due 最多清理的存档数（玩家 + master 合计，03 §6.3）
LOCAL_LAZY_GENERATE_TIME = dtime(12, 0)  # 本地 12:00 起提前生成明天的挑战（03 §11.2 第 1 步）
_monotonic: Callable[[], float] = time.monotonic
_throttle_lock = threading.Lock()
_last_run_mono: float | None = None


@dataclass
class RunReport:
    """一次 run_due 的摘要（CLI 与测试用；不含 seed）。"""

    generated: int = 0  # 缺失时尝试生成的天数（并发下可能含被他人抢先的，行数以唯一键为准）
    promoted: int = 0
    advanced: int = 0
    closed_hooks: int = 0
    settled: int = 0
    cleaned_saves: int = 0
    errors: int = 0


def run_due(session_factory: sessionmaker[Session], now: datetime) -> RunReport:
    """按 03 §11.2 的六步推进全部挑战。可被多实例并发调用，靠唯一键与条件更新保证幂等。"""
    report = RunReport()
    settings = current_settings()
    if not settings.CHALLENGE_ENABLED:
        return report
    steps: tuple[tuple[str, Callable[[], int]], ...] = (
        ("ensure", lambda: _ensure_days(session_factory, now, settings)),
        ("promote", lambda: _promote(session_factory, now)),
        ("advance", lambda: _advance(session_factory, now)),
        ("closed_hooks", lambda: _closed_hooks(session_factory, now)),
        ("settle", lambda: _settle(session_factory, now)),
        ("cleanup", lambda: _cleanup(session_factory, now, settings)),
    )
    for name, step in steps:
        try:
            count = step()
        except Exception:
            report.errors += 1
            logger.exception("challenge run_due step failed: %s", name)
            continue
        if name == "ensure":
            report.generated += count
        elif name == "promote":
            report.promoted += count
        elif name == "advance":
            report.advanced += count
        elif name == "closed_hooks":
            report.closed_hooks += count
        elif name == "settle":
            report.settled += count
        else:
            report.cleaned_saves += count
    return report


def maybe_run_due(db_or_factory: Session | sessionmaker[Session], now: datetime) -> bool:
    """懒触发（节流）：距上次执行不足 CHALLENGE_RUN_DUE_MIN_INTERVAL_S 秒则跳过。
    返回本次是否真的执行。失败只记日志。"""
    global _last_run_mono
    settings = current_settings()
    if not settings.CHALLENGE_ENABLED:
        return False
    interval = float(settings.CHALLENGE_RUN_DUE_MIN_INTERVAL_S)
    with _throttle_lock:
        mono = _monotonic()
        if _last_run_mono is not None and mono - _last_run_mono < interval:
            return False
        _last_run_mono = mono
    try:
        run_due(_factory_of(db_or_factory), now)
    except Exception:
        logger.exception("challenge lazy run_due failed")
        return False
    return True


def reset_throttle() -> None:
    """重置懒触发节流（create_app 与测试用）。"""
    global _last_run_mono
    with _throttle_lock:
        _last_run_mono = None


def _factory_of(db_or_factory: Session | sessionmaker[Session]) -> sessionmaker[Session]:
    if isinstance(db_or_factory, Session):
        return make_session_factory(db_or_factory.get_bind())
    return db_or_factory


# ---------------------------------------------------------------- 六步


def _ensure_days(factory: sessionmaker[Session], now: datetime, settings: Settings) -> int:
    """①今天（缺且未过 entry_closes_at）；本地 ≥ 12:00 时提前生成明天（仅 daily）。"""
    count = 0
    today = local_date(now)
    with factory() as db:
        if (
            registry.challenge_for_date(db, today) is None
            and _may_generate_today(now, today, settings)
        ):
            generate.ensure_challenge(db, today, now=now, settings=settings)
            count += 1
    if settings.CHALLENGE_SCHEDULE == "daily" and _local_time(now) >= LOCAL_LAZY_GENERATE_TIME:
        tomorrow = today + timedelta(days=1)
        with factory() as db:
            if registry.challenge_for_date(db, tomorrow) is None:
                generate.ensure_challenge(db, tomorrow, now=now, settings=settings)
                count += 1
    return count  # 本次看到“缺失”而尝试生成的天数；并发抢先时唯一键保证只落一行


def _may_generate_today(now: datetime, day: date, settings: Settings) -> bool:
    if settings.CHALLENGE_SCHEDULE == "compact":
        return True  # 开发/e2e：开局相对 now 计算，不受截止时刻约束
    last_slot = parse_slots(settings.CHALLENGE_SLOTS)[-1]
    entry_closes_ms = to_ms(slot_to_utc(day, last_slot)) - CHALLENGE_CLOSE_LEAD_MS
    return to_ms(now) < entry_closes_ms


def _promote(factory: sessionmaker[Session], now: datetime) -> int:
    """②scheduled 且 now ≥ starts_at → running（条件更新，懒迁移同一实现）。"""
    with factory() as db:
        ids = list(db.scalars(select(Challenge.id).where(Challenge.status == "scheduled")))
    count = 0
    for cid in ids:
        with factory() as db:
            ch = db.get(Challenge, cid)
            if registry.promote_if_due(db, ch, now):
                count += 1
            db.commit()
    return count


def _advance(factory: sessionmaker[Session], now: datetime) -> int:
    """③每个 running：推进 master 到 tt(now)（途经检查点，出题与判定在推进事务内）。"""
    with factory() as db:
        ids = list(db.scalars(select(Challenge.id).where(Challenge.status == "running")))
    count = 0
    for cid in ids:
        with factory() as db:
            ch = db.get(Challenge, cid)
            if ch is None or ch.status != "running":
                continue
            count += sync.advance_master(db, ch, now)
    return count


def _closed_hooks(factory: sessionmaker[Session], now: datetime) -> int:
    """④closes_at ≤ now 且 closed_hooked_at 为空的回合：条件更新抢占后跑 RoundClosedHook。"""
    with factory() as db:
        pending = [
            (r.id, r.closes_at)
            for r in db.execute(
                select(ChallengeRound)
                .join(Challenge, Challenge.id == ChallengeRound.challenge_id)
                .where(
                    Challenge.status.in_(("running", "settled")),
                    ChallengeRound.closed_hooked_at.is_(None),
                )
            ).scalars()
        ]
    count = 0
    for rid, closes_at in pending:
        if _aware(closes_at) > now:
            continue
        with factory() as db:
            rnd = db.get(ChallengeRound, rid)
            claimed = db.execute(
                update(ChallengeRound)
                .where(ChallengeRound.id == rid, ChallengeRound.closed_hooked_at.is_(None))
                .values(closed_hooked_at=now)
                .execution_options(synchronize_session=False)
            ).rowcount
            if claimed != 1:
                db.rollback()
                continue
            db.refresh(rnd)
            ch = db.get(Challenge, rnd.challenge_id)
            hooks.run_round_closed(db, ch, rnd)
            db.commit()
            count += 1
    return count


def _settle(factory: sessionmaker[Session], now: datetime) -> int:
    """⑤到期的 running 挑战结算（settle_if_due 幂等，未到期返回 False）。"""
    with factory() as db:
        ids = list(db.scalars(select(Challenge.id).where(Challenge.status == "running")))
    count = 0
    for cid in ids:
        with factory() as db:
            ch = db.get(Challenge, cid)
            if ch is not None and settle.settle_if_due(db, ch, now):
                count += 1
    return count


def _cleanup(factory: sessionmaker[Session], now: datetime, settings: Settings) -> int:
    """⑥清理（03 §6.3）：先删玩家挑战存档（成绩保留，save_id 置 NULL），再删 master。
    每次合计 ≤ CLEANUP_BATCH 个存档，分批、每批一个事务，可重跑。"""
    budget = CLEANUP_BATCH
    removed = 0
    player_cutoff = now - timedelta(days=settings.CHALLENGE_PLAYER_RETENTION_DAYS)
    while budget > 0:
        with factory() as db:
            rows = db.execute(
                select(ChallengeEntry.id, ChallengeEntry.save_id)
                .join(Challenge, Challenge.id == ChallengeEntry.challenge_id)
                .where(
                    Challenge.status == "settled",
                    Challenge.settled_at <= player_cutoff,
                    ChallengeEntry.save_id.is_not(None),
                )
                .limit(budget)
            ).all()
            if not rows:
                break
            save_ids = [save_id for _, save_id in rows]
            db.execute(
                update(ChallengeEntry)
                .where(ChallengeEntry.save_id.in_(save_ids))
                .values(save_id=None)
                .execution_options(synchronize_session=False)
            )
            db.execute(
                delete(Save).where(Save.id.in_(save_ids), Save.mode == SAVE_MODE_CHALLENGE)
            )
            db.commit()
        removed += len(save_ids)
        budget -= len(save_ids)

    market_cutoff = now - timedelta(days=settings.CHALLENGE_MARKET_RETENTION_DAYS)
    with factory() as db:
        masters = db.execute(
            select(Challenge.id, Challenge.master_save_id)
            .where(
                Challenge.status == "settled",
                Challenge.settled_at <= market_cutoff,
                Challenge.master_save_id.is_not(None),
            )
            .limit(budget)
        ).all()
    for cid, master_id in masters:
        if budget <= 0:
            break
        with factory() as db:
            players_left = db.scalar(
                select(func.count(Save.id)).where(
                    Save.market_source_id == master_id, Save.mode == SAVE_MODE_CHALLENGE
                )
            )
            if players_left:  # 玩家存档尚未清理完（应被上一步清掉），本次跳过
                db.rollback()
                continue
            db.execute(
                update(Challenge)
                .where(Challenge.id == cid)
                .values(master_save_id=None)
                .execution_options(synchronize_session=False)
            )
            db.execute(
                delete(Save).where(
                    Save.id == master_id, Save.mode == SAVE_MODE_CHALLENGE_MARKET
                )
            )
            db.commit()
        removed += 1
        budget -= 1
    return removed


# ---------------------------------------------------------------- 工具


def _local_time(now: datetime) -> dtime:
    return (now.astimezone(UTC) + LOCAL_OFFSET).time()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["RunReport", "maybe_run_due", "reset_throttle", "run_due"]

