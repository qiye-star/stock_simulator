"""自动交易执行（纯函数）。买卖逻辑全部复用 matching.execute_order。

legacy：executeAutoTrade（game.js 5785-6000）。与 legacy 的差异：
- 全局上限 AUTO_LIMIT_REACHED 只计成功成交（legacy 计所有尝试）。
- 冷却按 tick 计（见 conditions.cooldown_ticks）。
- 限价单按 execute_order 的限价规则（不成交则失败事件 ORDER_LIMIT_NOT_REACHED）。
- 自动单不做偏离确认（confirm_deviation=True），与 legacy 一致。
- 自动单同样校验交易单位（legacy 未校验）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..clock import is_trading_time
from ..errors import AUTO_LIMIT_REACHED, AUTO_MAX_AMOUNT_EXCEEDED, VALIDATION_ERROR, DomainError
from ..matching import execute_order
from ..types import Account, OrderRequest, Quote, TradeRecord, TradeSettings
from .conditions import AutoTradeConfig, cooldown_ticks, should_trigger

DEFAULT_MAX_TOTAL_TRADES = 100  # legacy game.js 6010


@dataclass(frozen=True)
class AutoRuntime:
    """自动交易运行时状态（不可变；每次 run 返回新实例）。

    key 统一为 f"{code}-{direction}"，与 legacy lastTradeTimes / stockTradeCounts 一致。
    """

    last_attempt_tick: Mapping[str, int] = field(default_factory=dict)
    trade_counts: Mapping[str, int] = field(default_factory=dict)
    total_success: int = 0
    limit_notified: bool = False


@dataclass(frozen=True)
class AutoEvent:
    config_id: str
    stock_code: str
    stock_name: str
    direction: str
    tick: int
    success: bool
    reason: str | None  # 成功为 None，失败为错误码
    params: Mapping[str, Any]
    amount_cents: int = 0  # 买：-(金额+手续费)；卖：金额-手续费（与 cash 一致）
    pnl_cents: int = 0
    fill_price_cents: int = 0


@dataclass(frozen=True)
class AutoTickResult:
    runtime: AutoRuntime
    account: Account
    new_trades: tuple[TradeRecord, ...]
    events: tuple[AutoEvent, ...]


def _key(config: AutoTradeConfig) -> str:
    return f"{config.code}-{config.direction}"


def _failure(
    config: AutoTradeConfig, tick: int, reason: str, params: Mapping[str, Any] | None = None
) -> AutoEvent:
    return AutoEvent(
        config_id=config.id,
        stock_code=config.code,
        stock_name=config.name,
        direction=config.direction,
        tick=tick,
        success=False,
        reason=reason,
        params=dict(params or {}),
    )


def run_auto_trades(
    configs: Sequence[AutoTradeConfig],
    runtime: AutoRuntime,
    *,
    tick: int,
    trading_day: int,
    minute_of_day: int,
    quotes: Mapping[str, Quote],
    account: Account,
    settings: TradeSettings,
    trades: Sequence[Mapping[str, Any]],
    max_total_trades: int = DEFAULT_MAX_TOTAL_TRADES,
) -> AutoTickResult:
    """对所有配置执行一次条件检查。非交易时段原样返回。

    trades: 该存档已有成交（用于 T+1）；本次新增成交会在循环内追加参与后续判断。
    """
    if not is_trading_time(minute_of_day):
        return AutoTickResult(runtime, account, (), ())

    last_attempt = dict(runtime.last_attempt_tick)
    trade_counts = dict(runtime.trade_counts)
    total_success = runtime.total_success
    limit_notified = runtime.limit_notified
    working_trades: list[Mapping[str, Any]] = list(trades)
    new_trades: list[TradeRecord] = []
    events: list[AutoEvent] = []

    for config in configs:
        quote = quotes.get(config.code)
        if quote is None:
            continue  # legacy：无行情数据直接跳过，不产生记录
        key = _key(config)
        last = last_attempt.get(key)
        if last is not None and tick - last < cooldown_ticks(config):
            continue
        holding = account.holdings.get(config.code)
        if not should_trigger(config, quote, holding):
            continue

        last_attempt[key] = tick  # legacy：进入执行即更新冷却，失败也计入
        if config.max_trades and trade_counts.get(key, 0) >= config.max_trades:
            events.append(
                _failure(
                    config, tick, AUTO_LIMIT_REACHED, {"scope": "config", "max": config.max_trades}
                )
            )
            continue

        price = quote.price_cents if config.price_type == "market" else config.limit_price_cents
        if price is None or price <= 0:
            events.append(_failure(config, tick, VALIDATION_ERROR, {"field": "limit_price_cents"}))
            continue
        amount = price * config.quantity
        if config.max_amount_cents and amount > config.max_amount_cents:
            events.append(
                _failure(
                    config, tick, AUTO_MAX_AMOUNT_EXCEEDED, {"max_cents": config.max_amount_cents}
                )
            )
            continue
        if total_success >= max_total_trades:
            notify = not limit_notified
            limit_notified = True
            events.append(
                _failure(
                    config,
                    tick,
                    AUTO_LIMIT_REACHED,
                    {"scope": "global", "max": max_total_trades, "notify": notify},
                )
            )
            continue

        request = OrderRequest(
            code=config.code,
            side=config.direction,
            quantity=config.quantity,
            price_type=config.price_type,
            limit_price_cents=config.limit_price_cents,
            confirm_deviation=True,
        )
        try:
            result = execute_order(
                request,
                account=account,
                quote=quote,
                settings=settings,
                trades=working_trades,
                trading_day=trading_day,
                minute_of_day=minute_of_day,
                source="auto",
            )
        except DomainError as exc:
            events.append(_failure(config, tick, exc.code, exc.params))
            continue

        account = result.account
        working_trades.append(result.trade)
        new_trades.append(result.trade)
        trade_counts[key] = trade_counts.get(key, 0) + 1
        total_success += 1
        events.append(
            AutoEvent(
                config_id=config.id,
                stock_code=config.code,
                stock_name=config.name,
                direction=config.direction,
                tick=tick,
                success=True,
                reason=None,
                params={},
                amount_cents=result.trade["cash_cents"],
                pnl_cents=result.pnl_cents,
                fill_price_cents=result.fill_price_cents,
            )
        )

    new_runtime = AutoRuntime(
        last_attempt_tick=last_attempt,
        trade_counts=trade_counts,
        total_success=total_success,
        limit_notified=limit_notified,
    )
    return AutoTickResult(new_runtime, account, tuple(new_trades), tuple(events))
