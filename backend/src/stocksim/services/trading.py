"""交易服务：下单（手动与自动交易共用）、成交流水的快照与分页、持仓同步。

撮合规则全部在 domain.matching.execute_order；本模块负责：
- 从库加载行情/持仓/当日成交 -> domain 输入；
- 把 DomainError 映射为 AppError；
- 在存档乐观锁内分配 trade seq、写 trades/holdings/save_stats/save_sectors/save_achievements。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.errors import DomainError
from stocksim.domain.market_engine import to_quote
from stocksim.domain.matching import execute_order
from stocksim.domain.types import Account, OrderRequest, TradeSettings
from stocksim.domain.types import Holding as DomainHolding
from stocksim.models import Holding, Save, SaveSector, SaveStats, Trade
from stocksim.services import achievements as achievements_service
from stocksim.services.market import load_market
from stocksim.services.stocks import get_stock_info

MAX_ATTEMPTS = 3
PAGE_SIZE = 50


@dataclass(frozen=True)
class PlacedOrder:
    trade: Trade
    unlocked_achievement_ids: tuple[str, ...]
    cash_cents: int
    replayed: bool = False


def trade_to_dict(trade: Trade) -> dict[str, Any]:
    """成交行 -> API 输出字典（不含 fund_before 等内部快照）。"""
    info = get_stock_info(trade.stock_code)
    return {
        "id": trade.id,
        "seq": trade.seq,
        "code": trade.stock_code,
        "name": info.name if info else "",
        "side": trade.side,
        "source": trade.source,
        "price_type": trade.price_type,
        "limit_price_cents": trade.limit_price_cents,
        "price_cents": trade.price_cents,
        "quantity": trade.quantity,
        "gross_cents": trade.gross_cents,
        "fee_cents": trade.fee_cents,
        "cash_delta_cents": trade.cash_delta_cents,
        "realized_pnl_cents": trade.realized_pnl_cents,
        "prev_close_cents": trade.prev_close_cents,
        "tick": trade.tick,
        "trading_day": trade.trading_day,
        "clock_minute": trade.clock_minute,
        "auto_config_id": trade.auto_config_id,
        "created_at": trade.created_at,
    }


def _record_for_stats(trade: Trade) -> dict[str, Any]:
    """成交行 -> domain 成就统计输入（TradeRecord 形态）。"""
    info = get_stock_info(trade.stock_code)
    return {
        "code": trade.stock_code,
        "name": info.name if info else "",
        "industry": info.industry if info else "",
        "side": trade.side,
        "price_type": trade.price_type,
        "quantity": trade.quantity,
        "price_cents": trade.price_cents,
        "amount_cents": trade.gross_cents,
        "fee_cents": trade.fee_cents,
        "cash_cents": trade.cash_delta_cents,
        "pnl_cents": trade.realized_pnl_cents,
        "trading_day": trade.trading_day,
        "minute_of_day": trade.clock_minute,
        "prev_close_cents": trade.prev_close_cents,
        "fund_before_cents": trade.fund_before_cents,
        "source": trade.source,
    }


def today_trade_refs(db: Session, save: Save, trading_day: int) -> list[dict[str, Any]]:
    """当日成交的最小字段（T+1 推导用）。"""
    rows = db.execute(
        select(Trade.stock_code, Trade.side, Trade.quantity, Trade.trading_day).where(
            Trade.save_id == save.id, Trade.trading_day == trading_day
        )
    ).all()
    return [
        {"code": code, "side": side, "quantity": qty, "trading_day": day}
        for code, side, qty, day in rows
    ]


def load_holdings(db: Session, save: Save) -> dict[str, DomainHolding]:
    out: dict[str, DomainHolding] = {}
    for row in db.scalars(select(Holding).where(Holding.save_id == save.id)):
        info = get_stock_info(row.stock_code)
        out[row.stock_code] = DomainHolding(
            code=row.stock_code,
            name=info.name if info else "",
            quantity=row.quantity,
            total_cost_cents=row.total_cost_cents,
        )
    return out


def find_by_idempotency_key(db: Session, save_id: uuid.UUID, key: str) -> Trade | None:
    return db.scalar(select(Trade).where(Trade.save_id == save_id, Trade.idempotency_key == key))


def _sync_holding(
    db: Session, save_id: uuid.UUID, code: str, holding: DomainHolding | None
) -> None:
    row = db.scalar(select(Holding).where(Holding.save_id == save_id, Holding.stock_code == code))
    if holding is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        row = Holding(id=uuid.uuid4(), save_id=save_id, stock_code=code)
        db.add(row)
    row.quantity = holding.quantity
    row.avg_price_cents = holding.avg_cost_cents
    row.total_cost_cents = holding.total_cost_cents
    row.updated_at = utcnow()


def _bump_stats(db: Session, save_id: uuid.UUID, side: str, pnl: int, holding_count: int) -> None:
    stats = db.get(SaveStats, save_id)
    if stats is None:
        stats = SaveStats(save_id=save_id)
        db.add(stats)
    stats.trade_count = (stats.trade_count or 0) + 1
    if side == "sell":
        if pnl > 0:
            stats.profit_count = (stats.profit_count or 0) + 1
        elif pnl < 0:
            stats.loss_count = (stats.loss_count or 0) + 1
    stats.max_holdings = max(stats.max_holdings or 0, holding_count)


def _add_sector(db: Session, save_id: uuid.UUID, sector: str) -> None:
    exists = db.scalar(
        select(SaveSector.id).where(SaveSector.save_id == save_id, SaveSector.sector == sector)
    )
    if exists is None:
        db.add(SaveSector(id=uuid.uuid4(), save_id=save_id, sector=sector))


def _place_once(
    db: Session,
    save: Save,
    *,
    code: str,
    side: Literal["buy", "sell"],
    quantity: int,
    price_type: Literal["market", "limit"],
    limit_price_cents: int | None,
    source: str,
    confirm_deviation: bool,
    auto_config_id: uuid.UUID | None,
    idempotency_key: str | None,
) -> PlacedOrder:
    if idempotency_key is not None:
        existing = find_by_idempotency_key(db, save.id, idempotency_key)
        if existing is not None:
            return PlacedOrder(existing, (), save.cash_cents, replayed=True)

    state, _ = load_market(db, save)
    quote = to_quote(state, code)
    if quote is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})

    trading_day = int(state["trading_day"])
    settings = TradeSettings(
        buy_fee_rate=save.buy_fee_rate,
        sell_fee_rate=save.sell_fee_rate,
        trade_unit=save.trade_unit,
        t0_mode=save.t0_mode,
    )
    request = OrderRequest(
        code=code,
        side=side,
        quantity=quantity,
        price_type=price_type,
        limit_price_cents=limit_price_cents,
        confirm_deviation=confirm_deviation,
    )
    try:
        result = execute_order(
            request,
            account=Account(fund_cents=save.cash_cents, holdings=load_holdings(db, save)),
            quote=quote,
            settings=settings,
            trades=today_trade_refs(db, save, trading_day),
            trading_day=trading_day,
            minute_of_day=save.clock_minute,
            source=source,
        )
    except DomainError as exc:
        raise AppError(ErrorCode(exc.code), exc.params) from exc

    snapshot = result.trade
    trade = Trade(
        id=uuid.uuid4(),
        save_id=save.id,
        seq=save.trade_seq + 1,
        stock_code=code,
        side=side,
        source=source,
        price_type=price_type,
        limit_price_cents=limit_price_cents if price_type == "limit" else None,
        price_cents=result.fill_price_cents,
        quantity=quantity,
        gross_cents=result.amount_cents,
        fee_cents=result.fee_cents,
        cash_delta_cents=int(snapshot["cash_cents"]),
        realized_pnl_cents=result.pnl_cents,
        prev_close_cents=quote.prev_close_cents,
        fund_before_cents=int(snapshot["fund_before_cents"]),
        tick=save.tick,
        trading_day=trading_day,
        clock_minute=save.clock_minute,
        auto_config_id=auto_config_id,
        idempotency_key=idempotency_key,
        created_at=utcnow(),
    )
    db.add(trade)
    save.trade_seq = trade.seq
    save.cash_cents = result.account.fund_cents
    _sync_holding(db, save.id, code, result.account.holdings.get(code))
    _bump_stats(db, save.id, side, result.pnl_cents, len(result.account.holdings))
    _add_sector(db, save.id, quote.industry)
    db.flush()

    all_trades = [
        _record_for_stats(t)
        for t in db.scalars(select(Trade).where(Trade.save_id == save.id).order_by(Trade.seq))
    ]
    prices = {
        s["code"]: int(s["price"]) for s in state["stocks"] if s["code"] in result.account.holdings
    }
    new_ids = achievements_service.record_unlocks(
        db, save, trades=all_trades, holdings=result.account.holdings, prices=prices
    )
    db.commit()
    return PlacedOrder(trade, tuple(new_ids), save.cash_cents)


def place_order_detailed(
    db: Session,
    save: Save,
    user_id: uuid.UUID,
    *,
    code: str,
    side: Literal["buy", "sell"],
    quantity: int,
    price_type: Literal["market", "limit"] = "market",
    limit_price_cents: int | None = None,
    source: str = "manual",
    confirm_deviation: bool = False,
    auto_config_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> PlacedOrder:
    """下单并返回成交与新解锁成就。调用前应已 advance_to_now。失败抛 AppError。"""
    if save.user_id != user_id:
        raise AppError(ErrorCode.SAVE_NOT_FOUND, {"save_id": str(save.id)})
    kwargs = {
        "code": code,
        "side": side,
        "quantity": quantity,
        "price_type": price_type,
        "limit_price_cents": limit_price_cents,
        "source": source,
        "confirm_deviation": confirm_deviation,
        "auto_config_id": auto_config_id,
        "idempotency_key": idempotency_key,
    }
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _place_once(db, save, **kwargs)  # type: ignore[arg-type]
        except IntegrityError:
            # 并发同一 Idempotency-Key：另一请求已写入，回放其结果
            db.rollback()
            if idempotency_key is None:
                raise
            existing = find_by_idempotency_key(db, save.id, idempotency_key)
            if existing is None:
                raise
            db.refresh(save)
            return PlacedOrder(existing, (), save.cash_cents, replayed=True)
        except StaleDataError:
            db.rollback()
            db.refresh(save)
            if attempt == MAX_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def place_order(
    db: Session,
    save: Save,
    user_id: uuid.UUID,
    *,
    code: str,
    side: Literal["buy", "sell"],
    quantity: int,
    price_type: Literal["market", "limit"],
    limit_price_cents: int | None = None,
    source: Literal["manual", "auto"] = "manual",
    confirm_deviation: bool = False,
    auto_config_id: uuid.UUID | None = None,
) -> Trade:
    """手动/自动交易共用的下单入口（签名由 auto-trade 线依赖，勿改）。返回成交记录。"""
    return place_order_detailed(
        db,
        save,
        user_id,
        code=code,
        side=side,
        quantity=quantity,
        price_type=price_type,
        limit_price_cents=limit_price_cents,
        source=source,
        confirm_deviation=confirm_deviation,
        auto_config_id=auto_config_id,
    ).trade


def list_trades(db: Session, save: Save, cursor: str | None) -> tuple[list[Trade], str | None]:
    """按 seq 倒序分页；cursor 为上一页最后一条的 seq（取更小的记录）。"""
    query = select(Trade).where(Trade.save_id == save.id)
    if cursor is not None:
        if not cursor.isdigit():
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"})
        query = query.where(Trade.seq < int(cursor))
    rows = list(db.scalars(query.order_by(desc(Trade.seq)).limit(PAGE_SIZE + 1)))
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    next_cursor = str(rows[-1].seq) if has_more and rows else None
    return rows, next_cursor


__all__ = [
    "PlacedOrder",
    "find_by_idempotency_key",
    "list_trades",
    "place_order",
    "place_order_detailed",
    "trade_to_dict",
]
