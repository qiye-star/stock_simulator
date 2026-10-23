"""WebSocket 路由：/api/v1/ws/saves/{save_id}。循环实现见 api/ws.py。"""

import uuid

from fastapi import APIRouter, WebSocket

from stocksim.api.ws import stream_save
from stocksim.services.auth import SESSION_COOKIE_NAME

router = APIRouter(tags=["ws"])


@router.websocket("/ws/saves/{save_id}")
async def save_stream(websocket: WebSocket, save_id: uuid.UUID) -> None:
    await websocket.accept()
    await stream_save(
        websocket,
        websocket.app.state.session_factory,
        websocket.app.state.settings,
        save_id,
        websocket.cookies.get(SESSION_COOKIE_NAME),
    )
