"""路由汇总（自动发现）。

`api_router` 不带前缀，由 main.create_app 挂载到 `/api/v1`。
routers 包下任何模块只要暴露 `router: APIRouter` 就会被自动登记，无需修改本文件。
"""

import importlib
import pkgutil

from fastapi import APIRouter

api_router = APIRouter()

for _mod in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    _m = importlib.import_module(f"{__name__}.{_mod.name}")
    _r = getattr(_m, "router", None)
    if isinstance(_r, APIRouter):
        api_router.include_router(_r)

__all__ = ["api_router"]
