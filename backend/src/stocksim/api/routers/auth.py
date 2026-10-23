"""认证接口：注册、登录、登出、修改密码。会话通过 httpOnly Cookie `session` 维持。"""

from fastapi import APIRouter, Response, status

from stocksim.api.deps import CurrentUser, DbSession, SessionTokenDep, SettingsDep
from stocksim.core.config import Settings
from stocksim.schemas.auth import LoginIn, PasswordChangeIn, RegisterIn
from stocksim.schemas.user import UserOut
from stocksim.services import auth as auth_service
from stocksim.services.auth import SESSION_COOKIE_NAME

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: RegisterIn, response: Response, db: DbSession, settings: SettingsDep) -> UserOut:
    user = auth_service.register(db, body.username, body.password)
    token = auth_service.create_session(db, settings, user)
    _set_session_cookie(response, settings, token)
    return UserOut.model_validate(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: DbSession, settings: SettingsDep) -> UserOut:
    user = auth_service.authenticate(db, body.username, body.password)
    token = auth_service.create_session(db, settings, user)
    _set_session_cookie(response, settings, token)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response, db: DbSession, settings: SettingsDep, token: SessionTokenDep
) -> None:
    auth_service.revoke_session(db, settings, token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeIn,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    token: SessionTokenDep,
) -> None:
    auth_service.change_password(
        db, settings, user, body.current_password, body.new_password, keep_token=token
    )
