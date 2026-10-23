"""股票目录：GET /stocks。"""

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.stocks import StockOut
from stocksim.services.stocks import list_stock_rows

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
def list_stocks(user: CurrentUser, db: DbSession) -> list[StockOut]:
    return [StockOut.model_validate(row) for row in list_stock_rows(db)]
