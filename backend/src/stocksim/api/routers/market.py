"""行情：全市场快照（分页/搜索/排序）、单只股票详情（日 K + 五档 + 涨跌停价）、个股分时。"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.core.errors import AppError, ErrorCode
from stocksim.schemas.market import IntradayOut, MarketOut, StockMarketOut
from stocksim.services import market as market_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/market", tags=["market"])


@router.get("", response_model=MarketOut)
def get_market(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=32)] = None,
    sort: Literal["code", "price", "change", "volume"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    watchlisted: bool | None = None,
) -> dict:
    """不带参数返回全部；limit/cursor 分页，q 搜代码/名称，sort/order 排序，watchlisted 筛自选。"""
    save = open_save(db, user, save_id)
    return market_service.market_overview(
        db,
        save,
        limit=limit,
        cursor=cursor,
        q=q,
        sort=sort,
        order=order,
        watchlisted=watchlisted,
    )


@router.get("/{code}", response_model=StockMarketOut)
def get_stock_market(save_id: uuid.UUID, code: str, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    detail = market_service.stock_market(db, save, code)
    if detail is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    return detail


@router.get("/{code}/intraday", response_model=IntradayOut)
def get_intraday(save_id: uuid.UUID, code: str, user: CurrentUser, db: DbSession) -> dict:
    """个股当日分时（交易日开盘至当前 clock_minute，确定性重放）。"""
    save = open_save(db, user, save_id)
    data = market_service.intraday(db, save, code)
    if data is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    return data
