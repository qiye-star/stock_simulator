"""存档服务：归属校验、CRUD、导出、自选。

所有存档级读写入口统一用 `open_save`：先校验归属（他人存档一律 SAVE_NOT_FOUND），
再 advance_to_now 把行情推进到当前时刻。
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.clock import random_start_minute
from stocksim.models import (
    Save,
    SaveAchievement,
    SaveSector,
    SaveStats,
    Trade,
    User,
    WatchlistItem,
)
from stocksim.models.trading import Holding
from stocksim.services import trading as trading_service
from stocksim.services.market import advance_to_now, init_market_for_save
from stocksim.services.stocks import get_stock_info

MAX_SAVES_PER_USER = 10
RATE_QUANT = Decimal("0.000001")
EXPORT_FORMAT = "stocksim-save"
EXPORT_FORMAT_VERSION = 1


def list_saves(db: Session, user: User) -> list[Save]:
    return list(db.scalars(select(Save).where(Save.user_id == user.id).order_by(Save.created_at)))


def load_owned_save(db: Session, user: User, save_id: uuid.UUID) -> Save:
    save = db.scalar(select(Save).where(Save.id == save_id, Save.user_id == user.id))
    if save is None:
        raise AppError(ErrorCode.SAVE_NOT_FOUND, {"save_id": str(save_id)})
    return save


def open_save(db: Session, user: User, save_id: uuid.UUID) -> Save:
    """归属校验 + 行情推进到当前时刻。存档级读写接口统一使用。"""
    save = load_owned_save(db, user, save_id)
    advance_to_now(db, save)
    return save


def create_save(
    db: Session,
    user: User,
    *,
    name: str,
    initial_fund_cents: int,
    buy_fee_rate: Decimal,
    sell_fee_rate: Decimal,
    t0_mode: bool,
    trade_unit: int,
) -> Save:
    count = db.scalar(select(func.count()).select_from(Save).where(Save.user_id == user.id)) or 0
    if count >= MAX_SAVES_PER_USER:
        raise AppError(ErrorCode.SAVE_LIMIT_REACHED, {"limit": MAX_SAVES_PER_USER})
    seed = secrets.randbits(63)  # [0, 2^63-1]
    now = utcnow()
    save = Save(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        mode="normal",
        initial_fund_cents=initial_fund_cents,
        cash_cents=initial_fund_cents,
        buy_fee_rate=buy_fee_rate.quantize(RATE_QUANT),
        sell_fee_rate=sell_fee_rate.quantize(RATE_QUANT),
        t0_mode=t0_mode,
        trade_unit=trade_unit,
        market_seed=seed,
        tick=0,
        trade_seq=0,
        trading_day=0,
        clock_minute=random_start_minute(seed),
        paused=False,
        last_tick_at=now,
        auto_enabled=False,
        auto_paused=False,
        auto_max_total_trades=100,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(save)
        db.flush()
        db.add(SaveStats(save_id=save.id))
        init_market_for_save(db, save, now.astimezone(UTC).date())
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return save


def update_save_name(db: Session, save: Save, name: str) -> Save:
    save.name = name
    db.commit()
    return save


def delete_save(db: Session, save: Save) -> None:
    db.delete(save)
    db.commit()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def export_save(db: Session, save: Save) -> dict[str, Any]:
    """导出为 JSON（版本化格式）。包含行情种子，便于复现与审计。"""
    trades = list(db.scalars(select(Trade).where(Trade.save_id == save.id).order_by(Trade.seq)))
    holdings = list(db.scalars(select(Holding).where(Holding.save_id == save.id)))
    stats = db.get(SaveStats, save.id)
    sectors = list(db.scalars(select(SaveSector.sector).where(SaveSector.save_id == save.id)))
    achievements = list(
        db.scalars(select(SaveAchievement).where(SaveAchievement.save_id == save.id))
    )
    watch = list(
        db.scalars(select(WatchlistItem.stock_code).where(WatchlistItem.save_id == save.id))
    )
    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": _iso(utcnow()),
        "save": {
            "id": str(save.id),
            "name": save.name,
            "mode": save.mode,
            "initial_fund_cents": save.initial_fund_cents,
            "cash_cents": save.cash_cents,
            "buy_fee_rate": format(save.buy_fee_rate.normalize(), "f"),
            "sell_fee_rate": format(save.sell_fee_rate.normalize(), "f"),
            "t0_mode": save.t0_mode,
            "trade_unit": save.trade_unit,
            "market_seed": str(save.market_seed),
            "tick": save.tick,
            "trade_seq": save.trade_seq,
            "trading_day": save.trading_day,
            "clock_minute": save.clock_minute,
            "created_at": _iso(save.created_at),
        },
        "stats": {
            "trade_count": stats.trade_count if stats else 0,
            "profit_count": stats.profit_count if stats else 0,
            "loss_count": stats.loss_count if stats else 0,
            "max_holdings": stats.max_holdings if stats else 0,
        },
        "holdings": [
            {
                "code": h.stock_code,
                "quantity": h.quantity,
                "avg_price_cents": h.avg_price_cents,
                "total_cost_cents": h.total_cost_cents,
            }
            for h in holdings
        ],
        "trades": [trading_service.trade_to_dict(t) | {"id": str(t.id)} for t in trades],
        "sectors": sorted(sectors),
        "watchlist": sorted(watch),
        "achievements": [
            {"id": a.achievement_id, "unlocked_at": _iso(a.unlocked_at)} for a in achievements
        ],
    }


def add_watchlist(db: Session, save: Save, code: str) -> None:
    if get_stock_info(code) is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    exists = db.scalar(
        select(WatchlistItem.id).where(
            WatchlistItem.save_id == save.id, WatchlistItem.stock_code == code
        )
    )
    if exists is not None:
        return
    try:
        db.add(WatchlistItem(id=uuid.uuid4(), save_id=save.id, stock_code=code))
        db.commit()
    except IntegrityError:
        db.rollback()  # 并发重复添加：已存在即可


def remove_watchlist(db: Session, save: Save, code: str) -> None:
    db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.save_id == save.id, WatchlistItem.stock_code == code
        )
    )
    db.commit()


__all__ = [
    "MAX_SAVES_PER_USER",
    "add_watchlist",
    "create_save",
    "delete_save",
    "export_save",
    "list_saves",
    "load_owned_save",
    "open_save",
    "remove_watchlist",
    "update_save_name",
]
