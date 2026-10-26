"""调试操作（仅 ENABLE_DEBUG_API=true 时由路由暴露）。对应 legacy/game.js 4449-4837。

这些操作直接改写存档数据，只用于本地调试与测试，不做业务规则校验。
"""

import secrets
import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.achievements.catalog import CATALOG, CATALOG_BY_ID
from stocksim.domain.clock import CLOCK_RULES_V2, V2_START_MINUTE
from stocksim.models import (
    Candle,
    Holding,
    MarketState,
    Save,
    SaveAchievement,
    SaveSector,
    SaveStats,
    Trade,
)
from stocksim.services import event_hooks
from stocksim.services.market import (
    advance_ticks,
    init_market_for_save,
    reject_challenge,
    reject_replay,
)

ACHIEVEMENT_ACTIONS = ("unlock", "lock", "unlock_all", "clear_all")


def set_cash(db: Session, save: Save, cash_cents: int) -> int:
    reject_challenge(save, "debug")
    reject_replay(save, "debug")
    save.cash_cents = cash_cents
    db.commit()
    return 1


def set_clock(db: Session, save: Save, minute_of_day: int) -> int:
    """v1 直接改分钟（旧行为）。v2 只能向前推进（经 advance_ticks 逐分钟推进，保持对齐不变量，
    见 07 §6.6）；返回推进的分钟数（可能被钩子截停）。"""
    reject_challenge(save, "debug")
    reject_replay(save, "debug")
    if save.clock_rules == CLOCK_RULES_V2:
        n = (minute_of_day - save.clock_minute) % 1440
        return advance_ticks(db, save, n) if n > 0 else 0
    save.clock_minute = minute_of_day
    db.commit()
    return 1


def achievements(db: Session, save: Save, action: str, ids: list[str]) -> int:
    """unlock/lock 针对 ids；unlock_all/clear_all 作用于全部目录。返回受影响行数。"""
    reject_challenge(save, "debug")
    reject_replay(save, "debug")
    if action not in ACHIEVEMENT_ACTIONS:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "action"})
    if action in ("unlock", "lock"):
        unknown = [i for i in ids if i not in CATALOG_BY_ID]
        if unknown:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "ids", "unknown": unknown[:5]})
    target = ids if action in ("unlock", "lock") else [a.id for a in CATALOG]
    if action in ("unlock", "unlock_all"):
        existing = set(
            db.scalars(
                select(SaveAchievement.achievement_id).where(
                    SaveAchievement.save_id == save.id,
                    SaveAchievement.achievement_id.in_(target),
                )
            )
        )
        new = [i for i in dict.fromkeys(target) if i not in existing]
        db.add_all(
            SaveAchievement(
                id=uuid.uuid4(), save_id=save.id, achievement_id=i, unlocked_at=utcnow()
            )
            for i in new
        )
        db.commit()
        return len(new)
    stmt = delete(SaveAchievement).where(SaveAchievement.save_id == save.id)
    if action == "lock":
        stmt = stmt.where(SaveAchievement.achievement_id.in_(target))
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def reset_market(db: Session, save: Save) -> int:
    """对应 legacy debugResetMarket：换新的行情种子并重建行情与历史 K（持仓与成交保留）。"""
    reject_challenge(save, "debug")  # reset_market 永不作用于挑战（03 §5 #10）
    reject_replay(save, "debug")
    if save.events_enabled:
        # 换 seed 之前让 B/C/D 清理自己的派生数据（01 §1.5）
        event_hooks.run_reset_hooks(db, save)
    row = db.get(MarketState, save.id)
    as_of = date.fromisoformat(row.payload["_meta"]["as_of"]) if row else utcnow().date()
    db.execute(delete(Candle).where(Candle.save_id == save.id))
    if row is not None:
        db.delete(row)
        db.flush()
    save.market_seed = secrets.randbelow(2**63)
    save.tick = 0
    save.trading_day = 0
    if save.clock_rules == CLOCK_RULES_V2:
        # v2 的全局 tick 与分钟从开局 9:30 对齐，重置行情时一并回到开盘（否则破坏对齐不变量）
        save.clock_minute = V2_START_MINUTE
        save.last_tick_at = utcnow()
    else:
        save.last_tick_at = None
    init_market_for_save(db, save, as_of)
    db.commit()
    return 1


def clear_game(db: Session, save: Save) -> int:
    """对应 legacy debugClearGame：资金回到初始值，清空持仓与成交，统计归零。

    自选、成就、自动交易配置保留（legacy 同样不清）。
    """
    reject_challenge(save, "debug")
    reject_replay(save, "debug")
    removed = db.execute(delete(Trade).where(Trade.save_id == save.id)).rowcount or 0
    db.execute(delete(Holding).where(Holding.save_id == save.id))
    db.execute(delete(SaveSector).where(SaveSector.save_id == save.id))
    stats = db.get(SaveStats, save.id)
    if stats is not None:
        stats.trade_count = 0
        stats.profit_count = 0
        stats.loss_count = 0
        stats.max_holdings = 0
    save.cash_cents = save.initial_fund_cents
    save.trade_seq = 0
    db.commit()
    return removed
