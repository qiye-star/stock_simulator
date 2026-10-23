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
