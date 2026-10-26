"""账号与会话服务：注册、登录、登出、改密、偏好、注销账号。"""

import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocksim.core.config import Settings
from stocksim.core.errors import AppError, ErrorCode
from stocksim.core.security import (
    burn_password_time,
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from stocksim.db.base import utcnow
from stocksim.models import AuthSession, User

SESSION_COOKIE_NAME = "session"

# 与 legacy/game.js 的 USERNAME_PATTERN、RESERVED_USERNAMES、密码长度规则保持一致
USERNAME_PATTERN = re.compile(r"^[一-龥a-zA-Z0-9_\-]+$")
RESERVED_USERNAMES = frozenset(
    {
        "__proto__",
        "constructor",
        "prototype",
        "hasOwnProperty",
        "toString",
        "valueOf",
        "__defineGetter__",
        "__defineSetter__",
    }
)
USERNAME_MIN_LEN = 2
USERNAME_MAX_LEN = 20
PASSWORD_MIN_LEN = 6
PASSWORD_MAX_LEN = 20

PREFERENCE_FIELDS = ("theme", "lang", "refresh_rate_ms", "tutorial_completed", "clock_speed")


def validate_username(username: str) -> None:
    if not (USERNAME_MIN_LEN <= len(username) <= USERNAME_MAX_LEN):
        raise AppError(ErrorCode.AUTH_USERNAME_INVALID, {"reason": "length"})
    if not USERNAME_PATTERN.fullmatch(username) or username in RESERVED_USERNAMES:
        raise AppError(ErrorCode.AUTH_USERNAME_INVALID, {"reason": "charset"})


def validate_password(password: str) -> None:
    if not (PASSWORD_MIN_LEN <= len(password) <= PASSWORD_MAX_LEN):
        raise AppError(
            ErrorCode.AUTH_PASSWORD_WEAK,
            {"min": PASSWORD_MIN_LEN, "max": PASSWORD_MAX_LEN},
        )


def register(db: Session, username: str, password: str) -> User:
    validate_username(username)
    validate_password(password)
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(ErrorCode.AUTH_USERNAME_TAKEN, {"username": username}) from None
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        burn_password_time(password)
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)
    valid, upgraded = verify_password(password, user.password_hash)
    if not valid:
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)
    if upgraded is not None:
        user.password_hash = upgraded
        db.commit()
    return user


def create_session(db: Session, settings: Settings, user: User) -> str:
    """创建会话，返回明文 token（只给客户端，库内仅存 HMAC）。"""
    token = new_session_token()
    now = utcnow()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_session_token(token, settings.SECRET_KEY),
            created_at=now,
            expires_at=now + timedelta(hours=settings.SESSION_TTL_HOURS),
            last_seen_at=now,
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, settings: Settings, token: str | None) -> User | None:
    if not token:
        return None
    token_hash = hash_session_token(token, settings.SECRET_KEY)
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if row is None:
        return None
    if row.expires_at <= utcnow():
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    return user


def revoke_session(db: Session, settings: Settings, token: str | None) -> None:
    if not token:
        return
    token_hash = hash_session_token(token, settings.SECRET_KEY)
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
    db.commit()


def change_password(
    db: Session,
    settings: Settings,
    user: User,
    current_password: str,
    new_password: str,
    keep_token: str | None,
) -> None:
    valid, _ = verify_password(current_password, user.password_hash)
    if not valid:
        raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)
    validate_password(new_password)
    if new_password == current_password:
        raise AppError(ErrorCode.AUTH_PASSWORD_WEAK, {"reason": "same_as_current"})
    user.password_hash = hash_password(new_password)
    # 改密后吊销该用户其他所有会话，保留当前会话
    keep_hash = hash_session_token(keep_token, settings.SECRET_KEY) if keep_token else ""
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.token_hash != keep_hash,
        )
    )
    db.commit()


def update_preferences(db: Session, user: User, changes: dict[str, Any]) -> User:
    for field in PREFERENCE_FIELDS:
        if field in changes:
            setattr(user, field, changes[field])
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, user: User) -> None:
    """删除账号。外键 ON DELETE CASCADE 会级联清除会话与全部存档数据。"""
    db.delete(user)
    db.commit()
