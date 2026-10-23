"""自动交易条件判断（纯函数）。legacy：checkAutoTradeCondition（game.js 5643-5780）。

单位约定：
- price 类条件的 condition_value_cents：分；
- profit 类条件（盈亏金额）：分；
- percentage 类条件 condition_value_bp：基点（500 = 5%）。
- 冷却以 tick 计：默认 2 tick（legacy 5 秒 / 3 秒刷新），time 类 10 tick（legacy 30 秒）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..types import Holding, Quote, Side

ConditionType = Literal["price", "percentage", "profit", "time"]
Operator = Literal["above", "below", "equal"]
PriceType = Literal["market", "limit"]

DEFAULT_COOLDOWN_TICKS = 2  # legacy 5000ms（刷新 3000ms 下约 2 tick）
TIME_COOLDOWN_TICKS = 10  # legacy 30000ms


@dataclass(frozen=True)
class AutoTradeConfig:
    id: str
    code: str
    name: str
    direction: Side
    condition_type: ConditionType
    condition_operator: Operator | None = None
    condition_value_cents: int = 0
    condition_value_bp: int = 0
    price_type: PriceType = "market"
    limit_price_cents: int | None = None
    quantity: int = 0
    max_trades: int = 0  # 0 = 不限
    max_amount_cents: int = 0  # 0 = 不限；单次 价*量 上限
    stop_loss_cents: int = 0  # 0 = 不设；取绝对值作为亏损阈值
    take_profit_cents: int = 0  # 0 = 不设


def cooldown_ticks(config: AutoTradeConfig) -> int:
    return TIME_COOLDOWN_TICKS if config.condition_type == "time" else DEFAULT_COOLDOWN_TICKS


def _price_matches(config: AutoTradeConfig, price: int) -> bool:
    value = config.condition_value_cents
    if config.condition_operator == "above":
        return price > value
    if config.condition_operator == "below":
        return price < value
    if config.condition_operator == "equal":
        return abs(price - value) < 1  # legacy: |diff| < 0.01 元
    return False


def _percent_matches(config: AutoTradeConfig, quote: Quote) -> bool:
    # 涨跌幅 = (price - prev) / prev；与阈值做精确比较（避免浮点）。
    # 单位：diff_bp 为 (price-prev)*10000，与 value_bp*prev 比较。
    diff = (quote.price_cents - quote.prev_close_cents) * 10_000
    scaled = config.condition_value_bp * quote.prev_close_cents
    if config.condition_operator == "above":
        return diff > scaled
    if config.condition_operator == "below":
        return diff < scaled
    if config.condition_operator == "equal":
        return abs(diff - scaled) < quote.prev_close_cents  # 小于 1 bp
    return False


def position_pnl_cents(quote: Quote, holding: Holding) -> int:
    """持仓浮动盈亏（分）= (现价 - 均价) * 持仓量。"""
    return (quote.price_cents - holding.avg_cost_cents) * holding.quantity


def base_triggered(config: AutoTradeConfig, quote: Quote, holding: Holding | None) -> bool:
    """基础触发条件（legacy 5688-5731）。"""
    if config.condition_type == "price":
        return _price_matches(config, quote.price_cents)
    if config.condition_type == "percentage":
        return _percent_matches(config, quote)
    if config.condition_type == "profit":
        if config.direction != "sell" or holding is None:
            return False
        pnl = position_pnl_cents(quote, holding)
        if config.condition_operator == "above":
            return pnl >= config.condition_value_cents
        if config.condition_operator == "below":
            return pnl <= -config.condition_value_cents
        return False
    # time：冷却已过即触发（冷却由调用方按 tick 判断）
    return config.condition_type == "time"


def stop_or_take_triggered(config: AutoTradeConfig, quote: Quote, holding: Holding | None) -> bool:
    """止损/止盈（仅卖出，且需有持仓；legacy 5733-5763）。"""
    if config.direction != "sell" or holding is None:
        return False
    pnl = position_pnl_cents(quote, holding)
    stop_hit = config.stop_loss_cents != 0 and pnl <= -abs(config.stop_loss_cents)
    take_hit = config.take_profit_cents > 0 and pnl >= config.take_profit_cents
    return stop_hit or take_hit


def should_trigger(config: AutoTradeConfig, quote: Quote, holding: Holding | None) -> bool:
    return base_triggered(config, quote, holding) or stop_or_take_triggered(config, quote, holding)
