"""FastAPI 依赖：数据库会话、配置、当前用户。"""

from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.db.session import get_db
from stocksim.models import User
from stocksim.services.auth import SESSION_COOKIE_NAME, resolve_session

DbSession = Annotated[Session, Depends(get_db)]


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_session_token(
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> str | None:
    return session


SessionTokenDep = Annotated[str | None, Depends(get_session_token)]


def get_current_user(db: DbSession, settings: SettingsDep, token: SessionTokenDep) -> User:
    user = resolve_session(db, settings, token)
    if user is None:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

__all__ = [
    "CurrentUser",
    "DbSession",
    "SessionTokenDep",
    "SettingsDep",
    "get_current_user",
    "get_db",
    "get_settings",
]
