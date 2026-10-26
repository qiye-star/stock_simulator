"""每日挑战服务层（03 §7）。

子模块：timeutil（时间）、config（配置入口）、clock（公共时间线缓存）、
registry（查询与 D 的 §1.7 契约）、generate（生成）、sync（推进与镜像）、entries（报名）、
rounds（回合与判定）、settle（结算）、boards（排行）、hooks（D 的扩展点）、
policy（B 的 CardPolicy）、views（对外 dict 的唯一出口）。

子模块不在此重导出，以免 market ↔ challenges 形成导入循环。§1.7 的函数与 ChallengeInfo
经模块级 __getattr__ 惰性解析：challenges.get_challenge(...) 可用。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# §1.7 契约名 → 所在子模块（惰性导入，避免导入期循环）
_LAZY: dict[str, str] = {
    "ChallengeInfo": "registry",
    "challenge_events": "registry",
    "expected_participants": "registry",
    "get_challenge": "registry",
    "knowledge_trading_tick": "registry",
    "live_challenges": "registry",
    "public_event": "registry",
    "public_trading_tick": "registry",
    "real_time_of": "registry",
    "reference_change_bp": "registry",
    "round_event_ids": "registry",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)
