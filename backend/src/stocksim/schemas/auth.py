"""认证接口的请求体。用户名/密码的业务校验放在 services/auth.py，错误码由其抛出。"""

from pydantic import BaseModel, Field

_MAX_SECRET_LEN = 256  # 防止超长输入拖慢 argon2


class RegisterIn(BaseModel):
    username: str = Field(max_length=_MAX_SECRET_LEN)
    password: str = Field(max_length=_MAX_SECRET_LEN)


class LoginIn(BaseModel):
    username: str = Field(max_length=_MAX_SECRET_LEN)
    password: str = Field(max_length=_MAX_SECRET_LEN)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=_MAX_SECRET_LEN)
    new_password: str = Field(max_length=_MAX_SECRET_LEN)
