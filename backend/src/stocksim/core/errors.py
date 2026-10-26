"""错误契约：HTTP 错误体统一为 `{"code": ..., "params": {...}}`。"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_USERNAME_TAKEN = "AUTH_USERNAME_TAKEN"
    AUTH_USERNAME_INVALID = "AUTH_USERNAME_INVALID"
    AUTH_PASSWORD_WEAK = "AUTH_PASSWORD_WEAK"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SAVE_NOT_FOUND = "SAVE_NOT_FOUND"
    SAVE_LIMIT_REACHED = "SAVE_LIMIT_REACHED"
    STOCK_NOT_FOUND = "STOCK_NOT_FOUND"
    TRADE_INSUFFICIENT_FUNDS = "TRADE_INSUFFICIENT_FUNDS"
    TRADE_INSUFFICIENT_HOLDINGS = "TRADE_INSUFFICIENT_HOLDINGS"
    TRADE_T1_SELL_BLOCKED = "TRADE_T1_SELL_BLOCKED"
    TRADE_INVALID_QUANTITY = "TRADE_INVALID_QUANTITY"
    TRADE_PRICE_OUT_OF_LIMIT = "TRADE_PRICE_OUT_OF_LIMIT"
    ORDER_LIMIT_NOT_REACHED = "ORDER_LIMIT_NOT_REACHED"
    MARKET_CLOSED = "MARKET_CLOSED"
    AUTO_CONFIG_DUPLICATE = "AUTO_CONFIG_DUPLICATE"
    AUTO_LIMIT_REACHED = "AUTO_LIMIT_REACHED"
    DEBUG_DISABLED = "DEBUG_DISABLED"
    LEGACY_IMPORT_INVALID = "LEGACY_IMPORT_INVALID"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TRADE_T1_BUY_BLOCKED = "TRADE_T1_BUY_BLOCKED"
    TRADE_PRICE_DEVIATION_EXCEEDED = "TRADE_PRICE_DEVIATION_EXCEEDED"
    TRADE_PRICE_DEVIATION_CONFIRM = "TRADE_PRICE_DEVIATION_CONFIRM"
    TRADE_CIRCUIT_BREAKER_ACTIVE = "TRADE_CIRCUIT_BREAKER_ACTIVE"
    AUTO_MAX_AMOUNT_EXCEEDED = "AUTO_MAX_AMOUNT_EXCEEDED"
    AUTO_CONFIG_NOT_FOUND = "AUTO_CONFIG_NOT_FOUND"
    # 事件行情（01 §9.2）
    EVENTS_DISABLED = "EVENTS_DISABLED"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    SUPPLY_EDGE_NOT_FOUND = "SUPPLY_EDGE_NOT_FOUND"
    # 预测卡 / 积分 / 情报卡 / 称号（02 §1.4）
    PREDICTION_NOT_FOUND = "PREDICTION_NOT_FOUND"
    PREDICTION_CLOSED = "PREDICTION_CLOSED"
    POINTS_INSUFFICIENT = "POINTS_INSUFFICIENT"
    INTEL_LIMIT_REACHED = "INTEL_LIMIT_REACHED"
    INTEL_UNAVAILABLE = "INTEL_UNAVAILABLE"
    TITLE_NOT_UNLOCKED = "TITLE_NOT_UNLOCKED"
    # 每日挑战（03 §10.3）
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"
    CHALLENGE_NOT_STARTED = "CHALLENGE_NOT_STARTED"
    CHALLENGE_ENTRY_CLOSED = "CHALLENGE_ENTRY_CLOSED"
    CHALLENGE_ENDED = "CHALLENGE_ENDED"
    CHALLENGE_NOT_ENTERED = "CHALLENGE_NOT_ENTERED"
    CHALLENGE_ROUND_NOT_FOUND = "CHALLENGE_ROUND_NOT_FOUND"
    CHALLENGE_ROUND_CLOSED = "CHALLENGE_ROUND_CLOSED"
    CHALLENGE_ANSWER_LIMIT = "CHALLENGE_ANSWER_LIMIT"
    CHALLENGE_NOT_SETTLED = "CHALLENGE_NOT_SETTLED"
    CHALLENGE_UNSUPPORTED = "CHALLENGE_UNSUPPORTED"
    # 真实复盘（05 §5.9）
    REPLAY_LEVEL_NOT_FOUND = "REPLAY_LEVEL_NOT_FOUND"
    REPLAY_UNSUPPORTED = "REPLAY_UNSUPPORTED"
    REPLAY_STOCK_SUSPENDED = "REPLAY_STOCK_SUSPENDED"
    REPLAY_LIMIT_LOCKED = "REPLAY_LIMIT_LOCKED"
    REPLAY_PREDICTION_PENDING = "REPLAY_PREDICTION_PENDING"
    REPLAY_QUESTION_CLOSED = "REPLAY_QUESTION_CLOSED"
    REPLAY_SESSION_SETTLED = "REPLAY_SESSION_SETTLED"
    REPLAY_REVEAL_LOCKED = "REPLAY_REVEAL_LOCKED"
    # 预测市场（04 §9.3）
    PM_NOT_FOUND = "PM_NOT_FOUND"
    PM_NOT_OPEN = "PM_NOT_OPEN"
    PM_LOCKED_AHEAD = "PM_LOCKED_AHEAD"
    PM_NOT_ELIGIBLE = "PM_NOT_ELIGIBLE"
    PM_SLIPPAGE_EXCEEDED = "PM_SLIPPAGE_EXCEEDED"
    PM_INSUFFICIENT_SHARES = "PM_INSUFFICIENT_SHARES"
    PM_TRADE_TOO_SMALL = "PM_TRADE_TOO_SMALL"
    PM_POSITION_LIMIT = "PM_POSITION_LIMIT"
    PM_DAILY_LIMIT = "PM_DAILY_LIMIT"
    PM_RATE_LIMITED = "PM_RATE_LIMITED"
    PM_BUSY = "PM_BUSY"


# 每个业务错误码的默认 HTTP 状态码
ERROR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.AUTH_USERNAME_TAKEN: 409,
    ErrorCode.AUTH_USERNAME_INVALID: 422,
    ErrorCode.AUTH_PASSWORD_WEAK: 422,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.SAVE_NOT_FOUND: 404,
    ErrorCode.SAVE_LIMIT_REACHED: 409,
    ErrorCode.STOCK_NOT_FOUND: 404,
    ErrorCode.TRADE_INSUFFICIENT_FUNDS: 422,
    ErrorCode.TRADE_INSUFFICIENT_HOLDINGS: 422,
    ErrorCode.TRADE_T1_SELL_BLOCKED: 422,
    ErrorCode.TRADE_INVALID_QUANTITY: 422,
    ErrorCode.TRADE_PRICE_OUT_OF_LIMIT: 422,
    ErrorCode.ORDER_LIMIT_NOT_REACHED: 422,
    ErrorCode.MARKET_CLOSED: 409,
    ErrorCode.AUTO_CONFIG_DUPLICATE: 409,
    ErrorCode.AUTO_LIMIT_REACHED: 409,
    ErrorCode.DEBUG_DISABLED: 403,
    ErrorCode.LEGACY_IMPORT_INVALID: 422,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.TRADE_T1_BUY_BLOCKED: 422,
    ErrorCode.TRADE_PRICE_DEVIATION_EXCEEDED: 422,
    ErrorCode.TRADE_PRICE_DEVIATION_CONFIRM: 422,
    ErrorCode.TRADE_CIRCUIT_BREAKER_ACTIVE: 409,
    ErrorCode.AUTO_MAX_AMOUNT_EXCEEDED: 409,
    ErrorCode.AUTO_CONFIG_NOT_FOUND: 404,
    ErrorCode.EVENTS_DISABLED: 409,
    ErrorCode.EVENT_NOT_FOUND: 404,
    ErrorCode.SUPPLY_EDGE_NOT_FOUND: 404,
    ErrorCode.PREDICTION_NOT_FOUND: 404,
    ErrorCode.PREDICTION_CLOSED: 409,
    ErrorCode.POINTS_INSUFFICIENT: 422,
    ErrorCode.INTEL_LIMIT_REACHED: 409,
    ErrorCode.INTEL_UNAVAILABLE: 409,
    ErrorCode.TITLE_NOT_UNLOCKED: 409,
    # 每日挑战（03 §10.3）
    ErrorCode.CHALLENGE_NOT_FOUND: 404,
    ErrorCode.CHALLENGE_NOT_STARTED: 409,
    ErrorCode.CHALLENGE_ENTRY_CLOSED: 409,
    ErrorCode.CHALLENGE_ENDED: 409,
    ErrorCode.CHALLENGE_NOT_ENTERED: 409,
    ErrorCode.CHALLENGE_ROUND_NOT_FOUND: 404,
    ErrorCode.CHALLENGE_ROUND_CLOSED: 409,
    ErrorCode.CHALLENGE_ANSWER_LIMIT: 409,
    ErrorCode.CHALLENGE_NOT_SETTLED: 409,
    ErrorCode.CHALLENGE_UNSUPPORTED: 409,
    # 真实复盘（05 §5.9）
    ErrorCode.REPLAY_LEVEL_NOT_FOUND: 404,
    ErrorCode.REPLAY_UNSUPPORTED: 409,
    ErrorCode.REPLAY_STOCK_SUSPENDED: 409,
    ErrorCode.REPLAY_LIMIT_LOCKED: 409,
    ErrorCode.REPLAY_PREDICTION_PENDING: 409,
    ErrorCode.REPLAY_QUESTION_CLOSED: 409,
    ErrorCode.REPLAY_SESSION_SETTLED: 409,
    ErrorCode.REPLAY_REVEAL_LOCKED: 409,
    # 预测市场（04 §9.3）
    ErrorCode.PM_NOT_FOUND: 404,
    ErrorCode.PM_NOT_OPEN: 409,
    ErrorCode.PM_LOCKED_AHEAD: 403,
    ErrorCode.PM_NOT_ELIGIBLE: 403,
    ErrorCode.PM_SLIPPAGE_EXCEEDED: 409,
    ErrorCode.PM_INSUFFICIENT_SHARES: 422,
    ErrorCode.PM_TRADE_TOO_SMALL: 422,
    ErrorCode.PM_POSITION_LIMIT: 409,
    ErrorCode.PM_DAILY_LIMIT: 409,
    ErrorCode.PM_RATE_LIMITED: 429,
    ErrorCode.PM_BUSY: 409,
}


class AppError(Exception):
    """业务异常。services/domain 抛出，由 `register_error_handlers` 转为 HTTP 响应。"""

    def __init__(
        self,
        code: ErrorCode,
        params: Mapping[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.params: dict[str, Any] = dict(params or {})
        self.status_code = status_code or ERROR_STATUS[code]
        super().__init__(code.value)


def error_body(code: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "params": dict(params or {})}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        body = error_body(exc.code.value, exc.params)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(ErrorCode.VALIDATION_ERROR.value, {"errors": fields}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 非业务的传输层错误（如未知路由 404）：code 为 HTTP_<status>，不属于 ErrorCode 枚举
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(f"HTTP_{exc.status_code}", {"detail": str(exc.detail)}),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", {}))
