"""持仓与资产：GET /saves/{id}/portfolio。"""

import uuid

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.portfolio import PortfolioOut
from stocksim.services.portfolio import portfolio_view
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}", tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return portfolio_view(db, save)
