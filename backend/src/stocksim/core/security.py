"""密码哈希（argon2id，经 pwdlib）与会话 token 工具。"""

import hashlib
import hmac
import secrets
from functools import lru_cache

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()  # argon2id


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> tuple[bool, str | None]:
    """校验密码；返回 (是否通过, 若参数过时则给出新哈希，否则 None)。"""
    return _hasher.verify_and_update(password, hashed)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def burn_password_time(password: str) -> None:
    """用户不存在时也执行一次哈希校验，避免通过响应时间枚举用户名。"""
    _hasher.verify(password, _dummy_hash())


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str, secret: str) -> str:
    """会话 token 以 HMAC-SHA256(SECRET_KEY, token) 存库，数据库泄漏不直接泄漏会话。"""
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
