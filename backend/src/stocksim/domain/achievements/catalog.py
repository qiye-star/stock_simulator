"""成就目录：来自 legacy/achievements.js 的 54 个 id。

名称与描述不在后端（由前端 i18n 提供 achievement.<id>.name/desc）。
condition 为声明式：stat（AchievementStats 字段名）>= threshold；
threshold 金额单位为分，收益率单位为基点（1000 = 10%）。
hidden=True 的成就：legacy 从未写入其统计输入，或无法从成交记录可靠推导，
接口仍返回但标记隐藏，永远不会解锁（见 HIDDEN_REASON_*）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LEVEL_BRONZE = "bronze"
LEVEL_SILVER = "silver"
LEVEL_GOLD = "gold"
LEVEL_LEGEND = "legend"
CATEGORY_STANDARD = "standard"
CATEGORY_EASTER = "easter_egg"  # 原 legacy “彩蛋成就 - 搞笑类”

HIDDEN_NO_MARKET_DATA = "需要历史行情/指数数据，成交记录不包含（legacy 从未写入）"
HIDDEN_NO_CALENDAR = "游戏内无日历日期，无法判断星期几"
HIDDEN_NO_POST_TRADE_PRICE = "需要卖出/买入后的即时行情，成交记录未保存"
HIDDEN_NO_STATE_HISTORY = "需要按日的净值/持仓历史，目前未保存"


@dataclass(frozen=True)
class AchievementDef:
    id: str
    level: str
    category: str
    stat: str
    threshold: int = 1
    hidden: bool = False
    hidden_reason: str = ""
    # "all_others"：除隐藏成就外，其它可见成就均已解锁（legacy all_achievements）
    op: str = "gte"


def _std(id_: str, level: str, stat: str, threshold: int = 1) -> AchievementDef:
    return AchievementDef(
        id=id_, level=level, category=CATEGORY_STANDARD, stat=stat, threshold=threshold
    )


def _easter(id_: str, level: str, stat: str, threshold: int = 1) -> AchievementDef:
    return AchievementDef(
        id=id_, level=level, category=CATEGORY_EASTER, stat=stat, threshold=threshold
    )


def _hidden(id_: str, level: str, reason: str, category: str = CATEGORY_STANDARD) -> AchievementDef:
    return AchievementDef(
        id=id_,
        level=level,
        category=category,
        stat="",
        threshold=0,
        hidden=True,
        hidden_reason=reason,
    )


_YUAN = 100  # 1 元 = 100 分
_BP_10 = 1000  # 10%
_BP_50 = 5000
_BP_100 = 10_000

CATALOG: tuple[AchievementDef, ...] = (
    # 青铜
    _std("first_trade", LEVEL_BRONZE, "trade_count", 1),
    _std("first_profit", LEVEL_BRONZE, "total_profit_cents", 1),
    _std("first_loss", LEVEL_BRONZE, "total_loss_cents", 1),
    _std("hold_5", LEVEL_BRONZE, "max_holdings", 5),
    _std("trade_10", LEVEL_BRONZE, "trade_count", 10),
    _std("profit_1k", LEVEL_BRONZE, "total_profit_cents", 1000 * _YUAN),
    _std("day_trader", LEVEL_BRONZE, "day_trades", 1),
    _std("watchlist_10", LEVEL_BRONZE, "watchlist_count", 10),
    # 白银
    _std("profit_10k", LEVEL_SILVER, "total_profit_cents", 10_000 * _YUAN),
    _std("trade_50", LEVEL_SILVER, "trade_count", 50),
    _std("hold_10", LEVEL_SILVER, "max_holdings", 10),
    _std("return_10", LEVEL_SILVER, "max_return_bp", _BP_10),
    _std("profit_streak_3", LEVEL_SILVER, "profit_streak", 3),
    _std("all_sectors", LEVEL_SILVER, "sector_count", 5),
    _std("large_trade", LEVEL_SILVER, "large_trades", 1),
    _std("maotai_holder", LEVEL_SILVER, "maotai_bought", 1),
    # 黄金
    _std("profit_100k", LEVEL_GOLD, "total_profit_cents", 100_000 * _YUAN),
    _std("return_50", LEVEL_GOLD, "max_return_bp", _BP_50),
    _std("trade_200", LEVEL_GOLD, "trade_count", 200),
    _std("profit_streak_10", LEVEL_GOLD, "profit_streak", 10),
    _std("double_bagger", LEVEL_GOLD, "double_bagger_count", 1),
    _hidden("market_beater", LEVEL_GOLD, HIDDEN_NO_MARKET_DATA),
    _std("diversified", LEVEL_GOLD, "sector_count", 10),
    _std("day_trader_pro", LEVEL_GOLD, "day_trades", 20),
    # 传说
    _std("profit_1m", LEVEL_LEGEND, "total_profit_cents", 1_000_000 * _YUAN),
    _std("return_100", LEVEL_LEGEND, "max_return_bp", _BP_100),
    _std("trade_1000", LEVEL_LEGEND, "trade_count", 1000),
    _std("perfect_game", LEVEL_LEGEND, "perfect_game", 1),
    _std("stock_god", LEVEL_LEGEND, "stock_god", 1),
    AchievementDef(
        id="all_achievements",
        level=LEVEL_LEGEND,
        category=CATEGORY_STANDARD,
        stat="",
        threshold=0,
        op="all_others",
    ),
    # 彩蛋
    _hidden("standing_guard", LEVEL_BRONZE, HIDDEN_NO_STATE_HISTORY, CATEGORY_EASTER),
    _hidden("buy_high_sell_low", LEVEL_BRONZE, HIDDEN_NO_STATE_HISTORY, CATEGORY_EASTER),
    _easter("fomo_master", LEVEL_BRONZE, "fomo_trades", 1),
    _easter("panic_seller", LEVEL_BRONZE, "panic_sells", 1),
    _hidden("bagholder", LEVEL_SILVER, HIDDEN_NO_STATE_HISTORY, CATEGORY_EASTER),
    _easter("yo_yo_trader", LEVEL_SILVER, "yo_yo_trades", 1),
    _easter("all_in_gambler", LEVEL_SILVER, "all_in_trades", 1),
    _hidden("comeback_kid", LEVEL_GOLD, HIDDEN_NO_STATE_HISTORY, CATEGORY_EASTER),
    _hidden("diamond_hands", LEVEL_GOLD, HIDDEN_NO_MARKET_DATA, CATEGORY_EASTER),
    _hidden("paper_hands", LEVEL_BRONZE, HIDDEN_NO_POST_TRADE_PRICE, CATEGORY_EASTER),
    _hidden("lucky_star", LEVEL_SILVER, HIDDEN_NO_POST_TRADE_PRICE, CATEGORY_EASTER),
    _hidden("unlucky_star", LEVEL_BRONZE, HIDDEN_NO_POST_TRADE_PRICE, CATEGORY_EASTER),
    _hidden("weekend_warrior", LEVEL_BRONZE, HIDDEN_NO_CALENDAR, CATEGORY_EASTER),
    _easter("round_number", LEVEL_BRONZE, "round_number_trades", 1),
    _easter("palindrome_profit", LEVEL_SILVER, "palindrome_profit", 1),
    _easter("tax_payer", LEVEL_SILVER, "total_fees_cents", 10_000 * _YUAN),
    _hidden("market_crash_survivor", LEVEL_GOLD, HIDDEN_NO_MARKET_DATA, CATEGORY_EASTER),
    _hidden("contrarian", LEVEL_SILVER, HIDDEN_NO_MARKET_DATA, CATEGORY_EASTER),
    _hidden("momentum_chaser", LEVEL_SILVER, HIDDEN_NO_POST_TRADE_PRICE, CATEGORY_EASTER),
    _easter("value_investor", LEVEL_GOLD, "value_investor", 1),
    _hidden("technical_trader", LEVEL_SILVER, HIDDEN_NO_MARKET_DATA, CATEGORY_EASTER),
    _hidden("news_trader", LEVEL_BRONZE, HIDDEN_NO_MARKET_DATA, CATEGORY_EASTER),
    _easter("early_bird", LEVEL_BRONZE, "early_trades", 1),
    _easter("night_owl", LEVEL_BRONZE, "late_trades", 1),
)

CATALOG_BY_ID: dict[str, AchievementDef] = {a.id: a for a in CATALOG}
assert len(CATALOG_BY_ID) == len(CATALOG) == 54, "catalog must contain 54 unique ids"


def visible_catalog() -> tuple[AchievementDef, ...]:
    return tuple(a for a in CATALOG if not a.hidden)


def catalog_as_dicts() -> list[dict[str, Any]]:
    """供 GET /achievements/catalog 使用（不含名称文案）。"""
    return [asdict(a) for a in CATALOG]
