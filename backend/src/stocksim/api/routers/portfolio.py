"""持仓与资产：GET /saves/{id}/portfolio、GET /saves/{id}/equity-curve。"""

import uuid
from typing import Literal

from fastapi import APIRouter

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.portfolio import EquityCurveOut, PortfolioOut
from stocksim.services.portfolio import equity_curve_view, portfolio_view
from stocksim.services.saves import open_save

router = APIRouter(prefix="/saves/{save_id}", tags=["portfolio"])


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(save_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    save = open_save(db, user, save_id)
    return portfolio_view(db, save)


@router.get("/equity-curve", response_model=EquityCurveOut)
def get_equity_curve(
    save_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    range: Literal["7d", "30d", "all"] = "30d",
) -> dict:
    save = open_save(db, user, save_id)
    return equity_curve_view(db, save, range)
