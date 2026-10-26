"""预测市场 WebSocket：/api/v1/ws/prediction-markets（04 §8）。循环实现见 api/pm_ws.py。"""

from fastapi import APIRouter, WebSocket

from stocksim.api.pm_ws import stream_prediction_markets
from stocksim.services.auth import SESSION_COOKIE_NAME

router = APIRouter(tags=["ws"])


@router.websocket("/ws/prediction-markets")
async def prediction_market_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    await stream_prediction_markets(
        websocket,
        websocket.app.state.pm_hub,
        websocket.app.state.session_factory,
        websocket.app.state.settings,
        websocket.cookies.get(SESSION_COOKIE_NAME),
    )
