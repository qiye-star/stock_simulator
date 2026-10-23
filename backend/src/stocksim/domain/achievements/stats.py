"""成就统计：全部由成交记录（TradeRecord，含 trade-time 快照）+ 当前持仓推导。纯函数。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..clock import is_early_bird_window, is_night_owl_window
from ..money import BP_DENOMINATOR, is_palindrome
from ..rules import is_limit_down, is_limit_up
from ..types import Holding

LARGE_TRADE_CENTS = 10_000_000  # 单笔金额 >10 万元（legacy 1 行 amount >= 100000）
MAOTAI_CODE = "600519"
ALL_IN_BP = 9000  # 使用 >=90% 资金
ROUND_NUMBER_UNIT = 100  # 价格为整数元
PALINDROME_MIN_CENTS = 100  # 盈利至少 1 元才参与回文判断（避免 0.x 元被判为 "0"）


@dataclass(frozen=True)
class AchievementStats:
    trade_count: int = 0
    total_profit_cents: int = 0  # 净值相对初始资金的正向部分（legacy 语义，但显式计算）
    total_loss_cents: int = 0
    net_pnl_cents: int = 0
    max_return_bp: int = 0  # 当前收益率（基点）
    max_holdings: int = 0  # 回放成交得到的最大同时持仓只数
    sector_count: int = 0
    day_trades: int = 0  # 同日先买后卖的卖出笔数
    watchlist_count: int = 0
    profit_streak: int = 0
    large_trades: int = 0
    maotai_bought: int = 0
    double_bagger_count: int = 0  # 当前持仓中收益 ≥100% 的只数
    value_investor: int = 0  # 当前持仓中存在收益 ≥100%
    stock_god: int = 0  # 当前持仓中存在收益 ≥500%
    fomo_trades: int = 0  # 涨停价买入
    panic_sells: int = 0  # 跌停价卖出
    yo_yo_trades: int = 0  # 同日同股 ≥3 笔的组合数
    all_in_trades: int = 0
    round_number_trades: int = 0
    palindrome_profit: int = 0
    total_fees_cents: int = 0
    early_trades: int = 0
    late_trades: int = 0
    perfect_game: int = 0  # 至少 1 笔卖出且全部盈利


def compute_stats(
    *,
    trades: Sequence[Mapping[str, Any]],
    holdings: Mapping[str, Holding],
    prices: Mapping[str, int],
    fund_cents: int,
    initial_fund_cents: int,
    watchlist_count: int = 0,
) -> AchievementStats:
    """prices: {code: 当前价（分）}，用于估算持仓市值与收益率；缺失则按成本计。"""
    market_value = sum(
        h.quantity * prices.get(code, h.avg_cost_cents) for code, h in holdings.items()
    )
    equity = fund_cents + market_value
    net = equity - initial_fund_cents
    max_return_bp = net * BP_DENOMINATOR // initial_fund_cents if initial_fund_cents > 0 else 0

    sectors = {str(t["industry"]) for t in trades if t.get("industry")}

    # 回放持仓数量得到最大同时持仓只数
    qty: dict[str, int] = {}
    max_holdings = 0
    for t in trades:
        code = str(t["code"])
        delta = int(t["quantity"]) if t["side"] == "buy" else -int(t["quantity"])
        qty[code] = qty.get(code, 0) + delta
        max_holdings = max(max_holdings, sum(1 for v in qty.values() if v > 0))

    day_trades = 0
    bought_by_day_code: dict[tuple[int, str], int] = {}
    counts_by_day_code: dict[tuple[int, str], int] = {}
    large = 0
    round_num = 0
    all_in = 0
    fomo = 0
    panic = 0
    early = 0
    late = 0
    fees = 0
    maotai = 0
    palindrome = 0
    streak = 0
    best_streak = 0
    sells = 0
    profitable_sells = 0

    for t in trades:
        code = str(t["code"])
        day = int(t["trading_day"])
        key = (day, code)
        side = str(t["side"])
        qty_t = int(t["quantity"])
        price = int(t["price_cents"])
        amount = int(t["amount_cents"])
        fee = int(t["fee_cents"])
        prev_close = int(t["prev_close_cents"])
        minute = int(t["minute_of_day"])
        pnl = int(t["pnl_cents"])

        counts_by_day_code[key] = counts_by_day_code.get(key, 0) + 1
        fees += fee
        if amount >= LARGE_TRADE_CENTS:
            large += 1
        if price % ROUND_NUMBER_UNIT == 0:
            round_num += 1
        if is_early_bird_window(minute):
            early += 1
        if is_night_owl_window(minute):
            late += 1
        if side == "buy":
            bought_by_day_code[key] = bought_by_day_code.get(key, 0) + qty_t
            if code == MAOTAI_CODE:
                maotai += 1
            if (amount + fee) * 10_000 >= int(t["fund_before_cents"]) * ALL_IN_BP:
                all_in += 1
            if is_limit_up(price, prev_close):
                fomo += 1
        else:
            sells += 1
            if bought_by_day_code.get(key, 0) > 0:
                day_trades += 1
            if is_limit_down(price, prev_close):
                panic += 1
            if pnl > 0:
                profitable_sells += 1
                streak += 1
                best_streak = max(best_streak, streak)
                if pnl >= PALINDROME_MIN_CENTS and is_palindrome(pnl // 100):
                    palindrome += 1
            elif pnl < 0:
                streak = 0

    yo_yo = sum(1 for c in counts_by_day_code.values() if c >= 3)

    double_bagger = 0
    value_investor = 0
    stock_god = 0
    for code, h in holdings.items():
        avg = h.avg_cost_cents
        price = prices.get(code)
        if avg <= 0 or price is None:
            continue
        # 收益率 = (price - avg) / avg：≥100% ⇔ price ≥ 2*avg；≥500% ⇔ price ≥ 6*avg
        if price >= 2 * avg:
            double_bagger += 1
            value_investor = 1
        if price >= 6 * avg:
            stock_god = 1

    return AchievementStats(
        trade_count=len(trades),
        total_profit_cents=max(0, net),
        total_loss_cents=max(0, -net),
        net_pnl_cents=net,
        max_return_bp=max_return_bp,
        max_holdings=max_holdings,
        sector_count=len(sectors),
        day_trades=day_trades,
        watchlist_count=watchlist_count,
        profit_streak=best_streak,
        large_trades=large,
        maotai_bought=1 if maotai else 0,
        double_bagger_count=double_bagger,
        value_investor=value_investor,
        stock_god=stock_god,
        fomo_trades=fomo,
        panic_sells=panic,
        yo_yo_trades=yo_yo,
        all_in_trades=all_in,
        round_number_trades=round_num,
        palindrome_profit=1 if palindrome else 0,
        total_fees_cents=fees,
        early_trades=early,
        late_trades=late,
        perfect_game=1 if sells > 0 and profitable_sells == sells else 0,
    )


__all__ = ["AchievementStats", "compute_stats"]
