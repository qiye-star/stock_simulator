"""行情：全市场快照与单只股票详情（日 K + 五档 + 涨跌停价）。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.core.errors import AppError, ErrorCode
from stocksim.schemas.market import MarketOut, StockMarketOut
from stocksim.services import market as market_service
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}/market", tags=["market"])


@router.get("", response_model=MarketOut)
def get_market(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return market_service.market_overview(db, save)


@router.get("/{code}", response_model=StockMarketOut)
def get_stock_market(save_id: uuid.UUID, code: str, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    detail = market_service.stock_market(db, save, code)
    if detail is None:
        raise AppError(ErrorCode.STOCK_NOT_FOUND, {"code": code})
    return detail
