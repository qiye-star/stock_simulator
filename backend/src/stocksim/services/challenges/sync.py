"""推进与镜像（03 §7.3、§3.2）：master 按公共时间线推进；玩家存档只镜像 master，永不超前。

- advance_master：在每个 hold_k 与每题 resolve_tt 处精确停下（同一事务），出题/判定后推到 tt(now)。
- sync_entry_save：挑战玩家存档的行情入口（market._advance_to_now_once 分发到此；推进后镜像）。
- before_trade：下单前同步镜像；phase ended 或挑战已结束抛 CHALLENGE_ENDED（03 §3.2）。

推进只经 market._run_ticks（唯一的 tick 推进路径，见 services/CLAUDE.md 不变量）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.timeline import minutes_to_tt, target_tt
from stocksim.models import Challenge, MarketState, Save
from stocksim.services import market as market_service
from stocksim.services.challenges import clock, hooks, registry, rounds, timeutil
from stocksim.services.challenges.timeutil import to_ms

# 快放段（burst/final）玩家可以“走表”；其余阶段（before/hold/ended）时钟停住（03 §3.2 paused 规则）
RUNNING_PHASES = ("burst", "final")


def advance_master(db: Session, ch: Challenge, now: datetime) -> int:
    """把 master 推进到 tt(now)，途经每个检查点。返回推进的分钟数（已 commit）。"""
    master = registry.market_save_for(db, ch)
    return market_service._retrying(db, master, lambda: _advance_once(db, ch.id, master.id, now))


def _advance_once(db: Session, challenge_id: uuid.UUID, master_id: uuid.UUID, now: datetime) -> int:
    # 每次尝试都从库里重读（冲突回滚后对象已过期；首次尝试可能拿到会话中的旧对象）
    master = db.get(Save, master_id)
    db.refresh(master)
    state_row = db.get(MarketState, master.id)
    if state_row is not None:
        db.refresh(state_row)
    ch = db.get(Challenge, challenge_id)
    db.refresh(ch)
    if ch.status == "void":
        db.commit()
        return 0
    timeline = clock.timeline_of(db, ch)
    target = target_tt(timeline, to_ms(now))
    cur = market_service.current_trading_tick(db, master)
    if target <= cur:
        db.commit()
        return 0
    rows = registry.rounds_of(db, ch)
    checkpoints = {r.hold_tt for r in rows} | {target}
    for r in rows:
        checkpoints.update(int(tt) for tt in (r.resolve_tts or {}).values())
    done = 0
    for cp in sorted(c for c in checkpoints if cur < c <= target):
        steps = minutes_to_tt(master.clock_minute, cur, cp)
        moved = market_service._run_ticks(db, master, steps)
        if moved != steps:
            # master 的出卡策略已关闭，不会被发布钩子截停；出现即为配置错误
            raise RuntimeError("challenge master was paused by a publish hook")
        done += moved
        cur = cp
        for r in rows:
            if r.hold_tt == cp and rounds.materialize_round(db, ch, master, r, now):
                hooks.run_round_open(db, ch, r)
        for r in rows:
            for qid, tt in (r.resolve_tts or {}).items():
                if int(tt) == cp and qid not in (r.outcomes or {}):
                    rounds.resolve_question(db, ch, r, qid, master, now=now)
                    hooks.run_question_resolved(db, ch, r, qid)
    db.commit()
    return done


def sync_entry_save(db: Session, save: Save, now: datetime) -> int:
    """挑战玩家存档的行情同步：推进 master，再把 tick/clock_minute/trading_day/paused 镜像。

    返回 master 本次推进的分钟数（WS advanced 字段）。仅在字段有变化时写玩家存档。
    """
    from stocksim.services.challenges import runner  # 延迟导入：runner 依赖本模块的上游

    ch = registry.challenge_of_save(db, save)
    runner.maybe_run_due(db, now)
    done = advance_master(db, ch, now)
    master = registry.market_save_for(db, ch)
    phase = clock.phase_at(db, ch, now).phase
    values = {
        "tick": master.tick,
        "clock_minute": master.clock_minute,
        "trading_day": master.trading_day,
        "paused": phase not in RUNNING_PHASES,
    }
    if any(getattr(save, k) != v for k, v in values.items()):
        for k, v in values.items():
            setattr(save, k, v)
    db.commit()
    return done


def before_trade(db: Session, save: Save) -> None:
    """挑战玩家下单前：同步镜像；挑战未在进行或 phase 为 ended 时抛 CHALLENGE_ENDED（03 §3.2）。"""
    now = timeutil.now()
    sync_entry_save(db, save, now)
    ch = registry.challenge_of_save(db, save)
    if ch.status != "running" or clock.phase_at(db, ch, now).phase == "ended":
        raise AppError(ErrorCode.CHALLENGE_ENDED, {"challenge_id": str(ch.id)})


__all__ = ["advance_master", "before_trade", "sync_entry_save"]
