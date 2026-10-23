"""领域错误。code 必须是 docs/CONTRACT.md 中 ErrorCode 的字符串值。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    """领域规则拒绝。services/api 层负责映射为 HTTP 错误体 {"code","params"}。"""

    def __init__(self, code: str, params: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params: dict[str, Any] = dict(params or {})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DomainError({self.code!r}, {self.params!r})"


# 契约内已有的码（core/errors.py 同步）
STOCK_NOT_FOUND = "STOCK_NOT_FOUND"
TRADE_INSUFFICIENT_FUNDS = "TRADE_INSUFFICIENT_FUNDS"
TRADE_INSUFFICIENT_HOLDINGS = "TRADE_INSUFFICIENT_HOLDINGS"
TRADE_T1_SELL_BLOCKED = "TRADE_T1_SELL_BLOCKED"
TRADE_INVALID_QUANTITY = "TRADE_INVALID_QUANTITY"
TRADE_PRICE_OUT_OF_LIMIT = "TRADE_PRICE_OUT_OF_LIMIT"
ORDER_LIMIT_NOT_REACHED = "ORDER_LIMIT_NOT_REACHED"
MARKET_CLOSED = "MARKET_CLOSED"
AUTO_LIMIT_REACHED = "AUTO_LIMIT_REACHED"
VALIDATION_ERROR = "VALIDATION_ERROR"

# 领域新增码（需追加到 core/errors.py 的 ErrorCode，并补 frontend/src/i18n/errors.js 文案）
TRADE_T1_BUY_BLOCKED = "TRADE_T1_BUY_BLOCKED"  # legacy game.js 3357-3363：当日已卖出则禁止买入
TRADE_PRICE_DEVIATION_EXCEEDED = "TRADE_PRICE_DEVIATION_EXCEEDED"  # 委托价偏离市价 >20%，硬阻断
TRADE_PRICE_DEVIATION_CONFIRM = (
    "TRADE_PRICE_DEVIATION_CONFIRM"  # 偏离 10%-20%，需 confirm_deviation
)
TRADE_CIRCUIT_BREAKER_ACTIVE = "TRADE_CIRCUIT_BREAKER_ACTIVE"
AUTO_MAX_AMOUNT_EXCEEDED = "AUTO_MAX_AMOUNT_EXCEEDED"  # 自动交易单次金额上限（事件码，不抛 HTTP）
