"""预测市场 REST（04 §9.1）。全部需登录。CHALLENGE_ENABLED=false 时一律 404 CHALLENGE_NOT_FOUND。

公开市场：/prediction-markets*；个人：/me/prediction-*；调试：/debug/prediction-markets*（ENABLE_DEBUG_API）。
下单必须带 Idempotency-Key（≤64）；同键同市场重放返回 200 与 replayed=true，首次为 201。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from stocksim.api.deps import CurrentUser, DbSession, SettingsDep
from stocksim.core.errors import AppError, ErrorCode
from stocksim.schemas.prediction_markets import (
    PmDebugSyncOut,
    PmDebugVoidIn,
    PmHistoryOut,
    PmMarketDetailOut,
    PmMarketPageOut,
    PmPositionPageOut,
    PmQuoteOut,
    PmSettlementPageOut,
    PmTapePageOut,
    PmTradeIn,
    PmTradeResultOut,
)
from stocksim.services import pm_lifecycle
from stocksim.services import prediction_markets as pm_service
from stocksim.services.challenges import timeutil

router = APIRouter(tags=["prediction-markets"])
debug_router = APIRouter(tags=["prediction-markets"], prefix="/debug/prediction-markets")

MarketPath = Annotated[uuid.UUID, Path()]


def require_pm_enabled(settings: SettingsDep) -> None:
    if not settings.CHALLENGE_ENABLED:
        raise AppError(ErrorCode.CHALLENGE_NOT_FOUND, {})


def require_debug_enabled(settings: SettingsDep) -> None:
    if not settings.ENABLE_DEBUG_API:
        raise AppError(ErrorCode.DEBUG_DISABLED)


def _now():  # 时间统一经挑战的 timeutil（测试可 monkeypatch 模块属性）
    return timeutil.now()


@router.get(
    "/prediction-markets",
    response_model=PmMarketPageOut,
    dependencies=[Depends(require_pm_enabled)],
)
def list_markets(
    user: CurrentUser,
    db: DbSession,
    challenge_id: uuid.UUID | None = None,
    status_: Annotated[
        Literal["all", "open", "closed", "resolved", "voided"] | None,
        Query(alias="status"),
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> PmMarketPageOut:
    page = pm_service.list_markets(
        db,
        user,
        challenge_id=challenge_id,
        status=status_,
        limit=limit,
        cursor=cursor,
        now=_now(),
    )
    return PmMarketPageOut.model_validate(page)


@router.get(
    "/prediction-markets/{market_id}",
    response_model=PmMarketDetailOut,
    dependencies=[Depends(require_pm_enabled)],
)
def get_market(market_id: MarketPath, user: CurrentUser, db: DbSession) -> PmMarketDetailOut:
    return PmMarketDetailOut.model_validate(
        pm_service.market_detail(db, user, market_id, now=_now())
    )


@router.get(
    "/prediction-markets/{market_id}/quote",
    response_model=PmQuoteOut,
    dependencies=[Depends(require_pm_enabled)],
)
def quote(
    market_id: MarketPath,
    user: CurrentUser,
    db: DbSession,
    side: Literal["buy", "sell"],
    outcome: Annotated[int, Query(ge=0, le=7)],
    shares: Annotated[int | None, Query(ge=1, le=200)] = None,
    budget_points: Annotated[int | None, Query(ge=1)] = None,
) -> PmQuoteOut:
    return PmQuoteOut.model_validate(
        pm_service.quote_market(
            db,
            user,
            market_id,
            side=side,
            outcome=outcome,
            shares=shares,
            budget_points=budget_points,
            now=_now(),
        )
    )


@router.post(
    "/prediction-markets/{market_id}/trades",
    response_model=PmTradeResultOut,
    dependencies=[Depends(require_pm_enabled)],
)
def place_trade(
    market_id: MarketPath,
    body: PmTradeIn,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=64)],
) -> PmTradeResultOut:
    order = pm_service.TradeOrder(
        side=body.side,
        outcome=body.outcome,
        shares=body.shares,
        budget_points=body.budget_points,
        max_cost_points=body.max_cost_points,
        min_proceeds_points=body.min_proceeds_points,
    )
    result = pm_service.trade(
        db, user, market_id, order, idempotency_key=idempotency_key, now=_now()
    )
    if result["replayed"]:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_201_CREATED
    return PmTradeResultOut.model_validate(result)


@router.get(
    "/prediction-markets/{market_id}/history",
    response_model=PmHistoryOut,
    dependencies=[Depends(require_pm_enabled)],
)
def history(
    market_id: MarketPath,
    user: CurrentUser,
    db: DbSession,
    max_points: Annotated[int, Query(ge=10, le=500)] = 200,
) -> PmHistoryOut:
    del user  # 价格曲线对已登录用户公开
    return PmHistoryOut.model_validate(
        pm_service.price_history(db, market_id, max_points, now=_now())
    )


@router.get(
    "/prediction-markets/{market_id}/trades",
    response_model=PmTapePageOut,
    dependencies=[Depends(require_pm_enabled)],
)
def tape(
    market_id: MarketPath,
    user: CurrentUser,
    db: DbSession,
    cursor: str | None = None,
) -> PmTapePageOut:
    del user  # 成交带匿名
    return PmTapePageOut.model_validate(pm_service.tape_page(db, market_id, cursor, now=_now()))


@router.get(
    "/me/prediction-positions",
    response_model=PmPositionPageOut,
    dependencies=[Depends(require_pm_enabled)],
)
def my_positions(
    user: CurrentUser,
    db: DbSession,
    status_: Annotated[Literal["active", "settled"], Query(alias="status")] = "active",
    cursor: str | None = None,
) -> PmPositionPageOut:
    return PmPositionPageOut.model_validate(
        pm_service.my_positions(db, user, status=status_, cursor=cursor, now=_now())
    )


@router.get(
    "/me/prediction-settlements",
    response_model=PmSettlementPageOut,
    dependencies=[Depends(require_pm_enabled)],
)
def my_settlements(
    user: CurrentUser,
    db: DbSession,
    cursor: str | None = None,
) -> PmSettlementPageOut:
    return PmSettlementPageOut.model_validate(pm_service.my_settlements(db, user, cursor=cursor))


# ---------------------------------------------------------------- 调试（ENABLE_DEBUG_API）


@debug_router.post(
    "/{market_id}/void",
    response_model=PmMarketDetailOut,
    dependencies=[Depends(require_debug_enabled), Depends(require_pm_enabled)],
)
def debug_void(
    market_id: MarketPath,
    body: PmDebugVoidIn,
    user: CurrentUser,
    db: DbSession,
) -> PmMarketDetailOut:
    pm_lifecycle.void_market(db, market_id, body.reason or "manual")
    return PmMarketDetailOut.model_validate(
        pm_service.market_detail(db, user, market_id, now=_now())
    )


@debug_router.post(
    "/sync",
    response_model=PmDebugSyncOut,
    dependencies=[Depends(require_debug_enabled), Depends(require_pm_enabled)],
)
def debug_sync(request: Request, user: CurrentUser) -> PmDebugSyncOut:
    """立即执行一轮 sweeper（物化 + 迁移所有到点市场）。"""
    del user
    changed = pm_lifecycle.sync_due(request.app.state.session_factory, _now())
    return PmDebugSyncOut(changed=changed)


router.include_router(debug_router)
