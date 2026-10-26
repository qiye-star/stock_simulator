"""挑战服务使用的配置入口（03 §11.1）。

create_app 把本应用的 Settings 登记到这里（use_settings），挑战服务经 current_settings() 读取，
使 `create_app(settings)` 注入的 CHALLENGE_* 对挑战逻辑生效（不依赖全局 get_settings 缓存）。
未登记时回退到 get_settings()。
"""

from __future__ import annotations

from stocksim.core.config import Settings, get_settings

_active: Settings | None = None


def use_settings(settings: Settings | None) -> None:
    global _active
    _active = settings


def current_settings() -> Settings:
    return _active if _active is not None else get_settings()
