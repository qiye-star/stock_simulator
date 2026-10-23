"""ORM 模型（16 张表）。导入本包即注册全部表到 `Base.metadata`，供 Alembic 使用。

字段权威定义见同目录 CLAUDE.md。
"""

from stocksim.models.account import AuthSession, LegacyImport, User
from stocksim.models.auto_trade import AutoTradeConfig, AutoTradeEvent
from stocksim.models.equity import EquitySnapshot
from stocksim.models.market import Candle, MarketState, Stock
from stocksim.models.save import Save, SaveAchievement, SaveSector, SaveStats
from stocksim.models.trading import Holding, Trade, WatchlistItem

__all__ = [
    "AuthSession",
    "AutoTradeConfig",
    "AutoTradeEvent",
    "Candle",
    "EquitySnapshot",
    "Holding",
    "LegacyImport",
    "MarketState",
    "Save",
    "SaveAchievement",
    "SaveSector",
    "SaveStats",
    "Stock",
    "Trade",
    "User",
    "WatchlistItem",
]
