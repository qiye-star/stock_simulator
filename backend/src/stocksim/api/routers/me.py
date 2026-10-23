"""当前用户接口：读取/修改偏好、注销账号。"""

from fastapi import APIRouter, Response, status

from stocksim.api.deps import CurrentUser, DbSession
from stocksim.schemas.user import MePatch, UserOut
from stocksim.services import auth as auth_service
from stocksim.services.auth import SESSION_COOKIE_NAME

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("", response_model=UserOut)
def patch_me(body: MePatch, user: CurrentUser, db: DbSession) -> UserOut:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    user = auth_service.update_preferences(db, user, changes)
    return UserOut.model_validate(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(response: Response, user: CurrentUser, db: DbSession) -> None:
    auth_service.delete_account(db, user)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
