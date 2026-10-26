"""事件状态与情报提示（01 §1.3、§1.7）。纯函数，不外发隐藏字段由服务层负责。"""

from __future__ import annotations

from ..rng import rand_below
from .constants import EVENT_DAY_TICK_BASE, K_RUMOR_HINT, RUMOR_HINT_ACCURACY_PCT
from .types import GameEvent


def rumor_hint(seed: int, event: GameEvent) -> str:
    """情报卡的传闻真假提示：RNG 预先决定，80% 与真值一致。返回 "likely_true" / "likely_false"。"""
    if event.rumor is None:
        raise ValueError("not a rumor")
    right = (
        rand_below(seed, EVENT_DAY_TICK_BASE - event.trading_day, event.slot, K_RUMOR_HINT, 100)
        < RUMOR_HINT_ACCURACY_PCT
    )
    says_true = event.rumor.truth if right else not event.rumor.truth
    return "likely_true" if says_true else "likely_false"


def rumor_status(event: GameEvent, trading_tick: int) -> str | None:
    """非传闻为 None；到了揭晓 tick 才会变成 confirmed / denied。"""
    if event.rumor is None:
        return None
    if trading_tick < event.rumor.resolve_trading_tick:
        return "unresolved"
    return "confirmed" if event.rumor.truth else "denied"


def event_phase(event: GameEvent, trading_tick: int) -> str:
    """expected = 只有铺垫；active = 源节点曲线还在变化；settled = 曲线已走完。"""
    if trading_tick < event.publish_trading_tick:
        return "expected"
    if trading_tick < event.lifetime_end_tick:
        return "active"
    return "settled"
