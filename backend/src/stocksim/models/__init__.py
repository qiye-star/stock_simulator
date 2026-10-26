"""ORM 模型（33 张表：原 16 张 + 预测卡 B 的 8 张（02 §9）+ 每日挑战 C 的 4 张（03 §6.2）
+ 预测市场 D 的 5 张（04 §6））。

导入本包即注册全部表到 `Base.metadata`，供 Alembic 使用。

字段权威定义见同目录 CLAUDE.md。
"""

from stocksim.models.account import AuthSession, LegacyImport, User
from stocksim.models.auto_trade import AutoTradeConfig, AutoTradeEvent
from stocksim.models.challenge import Challenge, ChallengeAnswer, ChallengeEntry, ChallengeRound
from stocksim.models.equity import EquitySnapshot
from stocksim.models.intel import IntelEdgeReveal, IntelRumorHint
from stocksim.models.market import Candle, MarketState, Stock
from stocksim.models.points import LedgerEntry, PointAccount, UserTitle
from stocksim.models.prediction_market import (
    PredictionMarket,
    PredictionMarketOutcome,
    PredictionPosition,
    PredictionSettlement,
    PredictionTrade,
)
from stocksim.models.predictions import PredictionAnswer, PredictionCard, PredictionSetting
from stocksim.models.replay import (
    ReplayLevel,
    ReplayLevelVersion,
    ReplayPrediction,
    ReplaySession,
)
from stocksim.models.save import Save, SaveAchievement, SaveSector, SaveStats
from stocksim.models.trading import Holding, Trade, WatchlistItem

__all__ = [
    "AuthSession",
    "AutoTradeConfig",
    "AutoTradeEvent",
    "Candle",
    "Challenge",
    "ChallengeAnswer",
    "ChallengeEntry",
    "ChallengeRound",
    "EquitySnapshot",
    "Holding",
    "IntelEdgeReveal",
    "IntelRumorHint",
    "LedgerEntry",
    "LegacyImport",
    "MarketState",
    "PointAccount",
    "PredictionAnswer",
    "PredictionCard",
    "PredictionMarket",
    "PredictionMarketOutcome",
    "PredictionPosition",
    "PredictionSetting",
    "PredictionSettlement",
    "PredictionTrade",
    "ReplayLevel",
    "ReplayLevelVersion",
    "ReplayPrediction",
    "ReplaySession",
    "Save",
    "SaveAchievement",
    "SaveSector",
    "SaveStats",
    "Stock",
    "Trade",
    "User",
    "UserTitle",
    "WatchlistItem",
]
