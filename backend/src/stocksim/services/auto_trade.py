"""自动交易服务：条件单 CRUD、运行状态机、事件分页，以及 run_auto_trade 评估执行。

决策（触发/冷却/止损止盈）复用 domain.auto_trade 的纯函数；下单统一经
services.trading.place_order(source='auto')，由它负责落库 trades 与 T+1/手续费等规则。
运行时计数（每条件单成交次数、全局成功次数、冷却 tick）从 auto_trade_events 推导，
因此 reset 清空事件即清零计数；stop 不清（见 backend/src/stocksim/services/CLAUDE.md）。
"""

import base64
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.base import utcnow
from stocksim.domain.auto_trade.conditions import AutoTradeConfig as DomainConfig
from stocksim.domain.auto_trade.conditions import cooldown_ticks, should_trigger
from stocksim.domain.clock import is_order_time
from stocksim.domain.errors import DomainError
from stocksim.domain.money import round_half_up_div
from stocksim.domain.types import Holding as DomainHolding
from stocksim.domain.types import Quote
from stocksim.models import (
    AutoTradeConfig,
    AutoTradeEvent,
    Holding,
    MarketState,
    Save,
    SaveStats,
    Stock,
    Trade,
)
from stocksim.schemas.auto_trade import AutoConfigIn
from stocksim.services import trading as trading_service
from stocksim.services.market import market_key, reject_challenge, reject_replay

# 事件码（非 HTTP 错误）：与 docs/CONTRACT.md 的自动交易事件码一致
AUTO_MAX_AMOUNT_EXCEEDED = "AUTO_MAX_AMOUNT_EXCEEDED"
AUTO_LIMIT_REACHED = ErrorCode.AUTO_LIMIT_REACHED.value

RUN_ACTIONS = ("start", "pause", "resume", "stop", "reset")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------- 配置 CRUD


def _validate(body: AutoConfigIn) -> None:
    ctype = body.condition_type
    if body.price_type == "market" and body.limit_price_cents is not None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "limit_price_cents"})
    if ctype == "time":
        if body.condition_operator is not None or body.condition_value_cents is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "condition_operator"})
    else:
        if body.condition_operator is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "condition_operator"})
    if ctype in ("price", "profit") and body.condition_value_cents is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "condition_value_cents"})
    if ctype == "percentage" and body.condition_percent is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "condition_percent"})
    if ctype == "profit" and body.direction != "sell":
        raise AppError(
            ErrorCode.VALIDATION_ERROR, {"field": "condition_type", "reason": "sell_only"}
        )


def _pct100(percent: float | None) -> int | None:
    """百分比（2.5）-> 整数 ×100（250，即基点）。"""
    return None if percent is None else round(percent * 100)


def _apply(row: AutoTradeConfig, body: AutoConfigIn) -> None:
    row.stock_code = body.code
    row.direction = body.direction
    row.condition_type = body.condition_type
    # models 中 condition_operator 为 NOT NULL；time 条件不使用比较符，占位写 "above"（输出时屏蔽）
    row.condition_operator = body.condition_operator or "above"
    row.condition_value_cents = body.condition_value_cents
    row.condition_pct100 = _pct100(body.condition_percent)
    row.quantity = body.quantity
    row.price_type = body.price_type
    row.limit_price_cents = body.limit_price_cents
    row.stop_loss_pct100 = _pct100(body.stop_loss_percent)
    row.take_profit_pct100 = _pct100(body.take_profit_percent)
    row.max_trades = body.max_trades
    row.max_amount_cents = body.max_amount_cents
    row.enabled = body.enabled


def _require_stock(db: Session, code: str) -> Stock:
    stock = db.scalar(select(Stock).where(Stock.code == code))
    if stock is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    return stock


def _duplicate(body: AutoConfigIn) -> AppError:
    return AppError(
        ErrorCode.AUTO_CONFIG_DUPLICATE, {"code": body.code, "direction": body.direction}
    )


def _commit_config(db: Session, save: Save, body: AutoConfigIn, self_id: uuid.UUID | None) -> None:
    """唯一性先查后写；并发竞争时由数据库唯一约束兜底，二者都映射为 AUTO_CONFIG_DUPLICATE。"""
    clash = db.scalar(
        select(AutoTradeConfig.id).where(
            AutoTradeConfig.save_id == save.id,
            AutoTradeConfig.stock_code == body.code,
            AutoTradeConfig.direction == body.direction,
            AutoTradeConfig.id != self_id if self_id else True,
        )
    )
    if clash is not None:
        db.rollback()
        raise _duplicate(body)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        text = str(exc.orig).lower()
        if "auto_trade_configs" in text and ("unique" in text or "duplicate" in text):
            raise _duplicate(body) from None
        raise


def list_configs(db: Session, save: Save) -> list[tuple[AutoTradeConfig, str]]:
    """返回 (配置, 股票名称) 列表，按创建时间排序（执行顺序即此顺序）。"""
    rows = list(
        db.scalars(
            select(AutoTradeConfig)
            .where(AutoTradeConfig.save_id == save.id)
            .order_by(AutoTradeConfig.created_at, AutoTradeConfig.id)
        )
    )
    names = _stock_names(db, {r.stock_code for r in rows})
    return [(r, names.get(r.stock_code, "")) for r in rows]


def _stock_names(db: Session, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = db.execute(select(Stock.code, Stock.name).where(Stock.code.in_(codes))).all()
    return {code: name for code, name in rows}


def create_config(db: Session, save: Save, body: AutoConfigIn) -> tuple[AutoTradeConfig, str]:
    reject_challenge(save, "auto_trade")
    reject_replay(save, "auto_trade")
    _validate(body)
    stock = _require_stock(db, body.code)
    row = AutoTradeConfig(save_id=save.id)
    _apply(row, body)
    db.add(row)
    _commit_config(db, save, body, None)
    db.refresh(row)
    return row, stock.name


def update_config(
    db: Session, save: Save, config_id: uuid.UUID, body: AutoConfigIn
) -> tuple[AutoTradeConfig, str]:
    reject_challenge(save, "auto_trade")
    reject_replay(save, "auto_trade")
    _validate(body)
    row = _get_config(db, save, config_id)
    stock = _require_stock(db, body.code)
    _apply(row, body)
    _commit_config(db, save, body, row.id)
    db.refresh(row)
    return row, stock.name


def delete_config(db: Session, save: Save, config_id: uuid.UUID) -> None:
    row = _get_config(db, save, config_id)
    db.delete(row)
    db.commit()


def _get_config(db: Session, save: Save, config_id: uuid.UUID) -> AutoTradeConfig:
    row = db.get(AutoTradeConfig, config_id)
    if row is None or row.save_id != save.id:
        raise AppError(ErrorCode.AUTO_CONFIG_NOT_FOUND, {"config_id": str(config_id)})
    return row


# ---------------------------------------------------------------- 运行状态


def _stats(db: Session, save: Save) -> SaveStats:
    stats = db.get(SaveStats, save.id)
    if stats is None:
        stats = SaveStats(save_id=save.id)
        db.add(stats)
        db.flush()
    return stats


def status(db: Session, save: Save) -> dict[str, Any]:
    stats = _stats(db, save)
    return {
        "enabled": save.auto_enabled,
        "paused": save.auto_paused,
        "max_total_trades": save.auto_max_total_trades,
        "total_trades": stats.auto_total_trades,
        "success_trades": stats.auto_success_trades,
        "failed_trades": stats.auto_failed_trades,
        "total_pnl_cents": stats.auto_total_pnl_cents,
    }


def run_action(db: Session, save: Save, action: str) -> dict[str, Any]:
    """start | pause | resume | stop | reset。pause/resume 只改暂停标记，不改启用状态。"""
    if action not in RUN_ACTIONS:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "action"})
    if action in ("start", "resume"):
        reject_challenge(save, "auto_trade")  # 挑战存档自动交易禁用（03 §3.2）
        reject_replay(save, "auto_trade")
    if action == "start":
        save.auto_enabled, save.auto_paused = True, False
    elif action == "pause":
        save.auto_paused = True
    elif action == "resume":
        save.auto_paused = False
    elif action == "stop":
        save.auto_enabled, save.auto_paused = False, False
    else:  # reset：与 legacy resetAutoTradeConfig 一致，清配置、事件与统计，并停止
        save.auto_enabled, save.auto_paused = False, False
        db.query(AutoTradeConfig).filter(AutoTradeConfig.save_id == save.id).delete()
        db.query(AutoTradeEvent).filter(AutoTradeEvent.save_id == save.id).delete()
        stats = _stats(db, save)
        stats.auto_total_trades = 0
        stats.auto_success_trades = 0
        stats.auto_failed_trades = 0
        stats.auto_total_pnl_cents = 0
    db.commit()
    return status(db, save)


def _encode_cursor(created_at: datetime, event_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(event_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, {"field": "cursor"}) from exc


def list_events(
    db: Session, save: Save, cursor: str | None, limit: int
) -> tuple[list[tuple[AutoTradeEvent, str]], str | None]:
    """按时间倒序分页（keyset）。返回 (事件与股票名列表, next_cursor)。"""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    stmt = select(AutoTradeEvent).where(AutoTradeEvent.save_id == save.id)
    if cursor:
        before_ts, before_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (AutoTradeEvent.created_at < before_ts)
            | ((AutoTradeEvent.created_at == before_ts) & (AutoTradeEvent.id < before_id))
        )
    rows = list(
        db.scalars(
            stmt.order_by(AutoTradeEvent.created_at.desc(), AutoTradeEvent.id.desc()).limit(
                limit + 1
            )
        )
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    names = _stock_names(db, {r.stock_code for r in rows})
    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return [(r, names.get(r.stock_code, "")) for r in rows], next_cursor


# ---------------------------------------------------------------- 评估与执行


def _runtime(db: Session, save: Save) -> tuple[dict[str, int], dict[str, int], int]:
    """从事件推导：每个 key(code-direction) 的最近尝试 tick、成功次数，以及全局成功次数。"""
    rows = db.execute(
        select(
            AutoTradeEvent.stock_code,
            AutoTradeEvent.direction,
            func.max(AutoTradeEvent.tick),
            func.sum(case((AutoTradeEvent.success.is_(True), 1), else_=0)),
        )
        .where(AutoTradeEvent.save_id == save.id)
        .group_by(AutoTradeEvent.stock_code, AutoTradeEvent.direction)
    ).all()
    last_tick: dict[str, int] = {}
    success: dict[str, int] = {}
    total = 0
    for code, direction, max_tick, ok in rows:
        key = f"{code}-{direction}"
        last_tick[key] = int(max_tick)
        success[key] = int(ok or 0)
        total += int(ok or 0)
    return last_tick, success, total


def _holdings(db: Session, save: Save) -> dict[str, Holding]:
    rows = db.scalars(select(Holding).where(Holding.save_id == save.id, Holding.quantity > 0))
    return {h.stock_code: h for h in rows}


def _quote(payload: Mapping[str, Any], code: str, stock: Stock) -> Quote | None:
    raw = payload.get(code)
    if not isinstance(raw, list) or len(raw) < 9:
        return None
    price, prev_close = int(raw[0]), int(raw[1])
    return Quote(
        code=code,
        name=stock.name,
        industry=stock.industry,
        price_cents=price,
        prev_close_cents=prev_close,
        circuit_breaker_active=int(raw[8]) > 0,
    )


def _domain_config(row: AutoTradeConfig, name: str, holding: Holding | None) -> DomainConfig:
    # 止损/止盈为“占持仓成本的百分比”（model 列为 pct100）；转换为金额阈值（分）供 domain 判断
    stop_cents = take_cents = 0
    if holding is not None and holding.total_cost_cents > 0:
        cost = holding.total_cost_cents
        if row.stop_loss_pct100:
            stop_cents = round_half_up_div(cost * row.stop_loss_pct100, 10_000)
        if row.take_profit_pct100:
            take_cents = round_half_up_div(cost * row.take_profit_pct100, 10_000)
    return DomainConfig(
        id=str(row.id),
        code=row.stock_code,
        name=name,
        direction=row.direction,  # type: ignore[arg-type]
        condition_type=row.condition_type,  # type: ignore[arg-type]
        condition_operator=row.condition_operator,  # type: ignore[arg-type]
        condition_value_cents=row.condition_value_cents or 0,
        condition_value_bp=row.condition_pct100 or 0,
        price_type=row.price_type,  # type: ignore[arg-type]
        limit_price_cents=row.limit_price_cents,
        quantity=row.quantity,
        max_trades=row.max_trades,
        max_amount_cents=row.max_amount_cents or 0,
        stop_loss_cents=stop_cents,
        take_profit_cents=take_cents,
    )


def _event(
    save: Save,
    row: AutoTradeConfig,
    *,
    success: bool,
    reason: str | None = None,
    amount_cents: int = 0,
    pnl_cents: int = 0,
    pnl_pct100: int | None = None,
    buy_price_cents: int | None = None,
    sell_price_cents: int | None = None,
) -> AutoTradeEvent:
    return AutoTradeEvent(
        id=uuid.uuid4(),
        save_id=save.id,
        config_id=row.id,
        stock_code=row.stock_code,
        direction=row.direction,
        condition_type=row.condition_type,
        success=success,
        message="" if success else (reason or ""),
        amount_cents=amount_cents,
        pnl_cents=pnl_cents,
        pnl_pct100=pnl_pct100,
        buy_price_cents=buy_price_cents,
        sell_price_cents=sell_price_cents,
        tick=save.tick,
        trading_day=save.trading_day,
        created_at=utcnow(),
    )


def run_auto_trade(db: Session, save: Save) -> list[Trade]:
    """对当前 tick 评估所有启用的条件单，满足则经 place_order(source='auto') 下单。

    返回本次新增的成交（Trade ORM 对象）。非交易时段、暂停、无行情或无启用配置时返回 []。
    每次进入执行即记录冷却（失败也计入）；每个尝试写一条 auto_trade_events。
    """
    if not save.auto_enabled or save.auto_paused or save.paused:
        return []
    if not is_order_time(save.clock_minute, save.clock_rules):
        return []
    configs = list(
        db.scalars(
            select(AutoTradeConfig)
            .where(AutoTradeConfig.save_id == save.id, AutoTradeConfig.enabled.is_(True))
            .order_by(AutoTradeConfig.created_at, AutoTradeConfig.id)
        )
    )
    market = db.get(MarketState, market_key(save))
    if not configs or market is None:
        return []

    holdings = _holdings(db, save)
    stock_rows = db.scalars(
        select(Stock).where(Stock.code.in_({c.stock_code for c in configs} | set(holdings)))
    )
    stocks = {s.code: s for s in stock_rows}
    last_tick, success_counts, total_success = _runtime(db, save)
    tick = save.tick
    produced: list[Trade] = []
    last_event_is_global_limit = _last_event_is_global_limit(db, save)
    stats = _stats(db, save)

    for row in configs:
        stock = stocks.get(row.stock_code)
        quote = _quote(market.payload or {}, row.stock_code, stock) if stock else None
        if stock is None or quote is None:
            continue  # 无行情的股票直接跳过，不产生事件（与 legacy 一致）
        key = f"{row.stock_code}-{row.direction}"
        holding = holdings.get(row.stock_code)
        domain_holding = (
            DomainHolding(
                code=row.stock_code,
                name=stock.name,
                quantity=holding.quantity,
                total_cost_cents=holding.total_cost_cents,
            )
            if holding
            else None
        )
        dcfg = _domain_config(row, stock.name, holding)

        last = last_tick.get(key)
        if last is not None and last <= tick and tick - last < cooldown_ticks(dcfg):
            continue
        if not should_trigger(dcfg, quote, domain_holding):
            continue

        last_tick[key] = tick  # 进入执行即计入冷却
        if row.max_trades and success_counts.get(key, 0) >= row.max_trades:
            db.add(_event(save, row, success=False, reason=AUTO_LIMIT_REACHED))
            _bump(stats, success=False)
            continue

        price = quote.price_cents if row.price_type == "market" else (row.limit_price_cents or 0)
        if row.max_amount_cents and price * row.quantity > row.max_amount_cents:
            db.add(_event(save, row, success=False, reason=AUTO_MAX_AMOUNT_EXCEEDED))
            _bump(stats, success=False)
            continue
        if total_success >= save.auto_max_total_trades:
            if not last_event_is_global_limit:
                db.add(_event(save, row, success=False, reason=AUTO_LIMIT_REACHED))
                _bump(stats, success=False)
                last_event_is_global_limit = True
            continue

        try:
            trade = trading_service.place_order(
                db,
                save,
                save.user_id,
                code=row.stock_code,
                side=row.direction,
                quantity=row.quantity,
                price_type=row.price_type,
                limit_price_cents=row.limit_price_cents,
                source="auto",
                confirm_deviation=True,
                auto_config_id=row.id,
            )
        except (AppError, DomainError) as exc:
            code = exc.code.value if isinstance(exc, AppError) else exc.code
            db.add(_event(save, row, success=False, reason=str(code)))
            _bump(stats, success=False)
            continue

        db.refresh(save)
        produced.append(trade)
        success_counts[key] = success_counts.get(key, 0) + 1
        total_success += 1
        last_event_is_global_limit = False
        avg_cost = (
            round_half_up_div(holding.total_cost_cents, holding.quantity) if holding else None
        )
        pnl_pct = None
        if row.direction == "sell" and avg_cost:
            cost_basis = avg_cost * trade.quantity
            pnl_pct = round_half_up_div(trade.realized_pnl_cents * 10_000, cost_basis)
        db.add(
            _event(
                save,
                row,
                success=True,
                amount_cents=trade.cash_delta_cents,
                pnl_cents=trade.realized_pnl_cents,
                pnl_pct100=pnl_pct,
                buy_price_cents=avg_cost if row.direction == "sell" else None,
                sell_price_cents=trade.price_cents if row.direction == "sell" else None,
            )
        )
        _bump(stats, success=True, pnl=trade.realized_pnl_cents)
        holdings = _holdings(db, save)

    db.commit()
    return produced


def _bump(stats: SaveStats, *, success: bool, pnl: int = 0) -> None:
    stats.auto_total_trades += 1
    if success:
        stats.auto_success_trades += 1
        stats.auto_total_pnl_cents += pnl
    else:
        stats.auto_failed_trades += 1


def _last_event_is_global_limit(db: Session, save: Save) -> bool:
    last = db.scalar(
        select(AutoTradeEvent)
        .where(AutoTradeEvent.save_id == save.id)
        .order_by(AutoTradeEvent.created_at.desc(), AutoTradeEvent.id.desc())
        .limit(1)
    )
    return last is not None and not last.success and last.message == AUTO_LIMIT_REACHED
