"""事件模式的扩展点（01 §1.5、§1.6）：发布暂停钩子、reset 钩子、揭示状态提供者。

- 暂停钩子在 `market._run_ticks` 的推进事务内运行：返回 True 表示在本 tick 后停住（存档置为暂停）。
  钩子**不得 commit**，可以 `db.add` 自己的行；乐观锁冲突重试时会被再次调用，因此必须幂等。
- reset 钩子在 `debug.reset_market` 换 seed 之前运行，用于清理 B/C/D 的派生数据。
- 揭示 provider 返回 `{edge_id: level}`（0/1/2）；默认返回空，即产业链关系全部隐藏。
- A 自己不注册任何钩子：默认永不暂停。注册函数按函数对象去重；`clear_hooks` 仅供测试。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session

from stocksim.domain.events import GameEvent, NewsItem
from stocksim.models import Save


@dataclass(frozen=True)
class PublishContext:
    save: Save
    trading_tick: int  # 本 tick（已推进完成）
    tick: int  # 全局 tick
    clock_minute: int
    news: tuple[NewsItem, ...]  # 本 tick 发布的全部快讯
    events: tuple[GameEvent, ...]  # 这些快讯所属的完整事件（含隐藏字段，服务端专用）


PublishHook = Callable[[Session, PublishContext], bool]
ResetHook = Callable[[Session, Save], None]
RevealProvider = Callable[[Session, Save], Mapping[str, int]]


def _no_reveal(_db: Session, _save: Save) -> Mapping[str, int]:
    return {}


_publish_hooks: list[PublishHook] = []
_reset_hooks: list[ResetHook] = []
_reveal: RevealProvider = _no_reveal


def register_publish_hook(hook: PublishHook) -> None:
    if hook not in _publish_hooks:
        _publish_hooks.append(hook)


def register_reset_hook(hook: ResetHook) -> None:
    if hook not in _reset_hooks:
        _reset_hooks.append(hook)


def register_reveal_provider(fn: RevealProvider) -> None:
    global _reveal
    _reveal = fn


def clear_hooks() -> None:
    """仅测试用：清空全部钩子并恢复默认的揭示 provider。"""
    global _reveal
    _publish_hooks.clear()
    _reset_hooks.clear()
    _reveal = _no_reveal


def run_publish_hooks(db: Session, ctx: PublishContext) -> bool:
    """任一钩子返回 True 即为 True。全部钩子都运行，不因前一个返回 True 而短路。"""
    results = [bool(hook(db, ctx)) for hook in tuple(_publish_hooks)]
    return any(results)


def run_reset_hooks(db: Session, save: Save) -> None:
    for hook in tuple(_reset_hooks):
        hook(db, save)


def reveal_levels(db: Session, save: Save) -> Mapping[str, int]:
    """{edge_id: level}，level ∈ {0,1,2}；缺省的边视为 0（隐藏）。"""
    return _reveal(db, save)


__all__ = [
    "PublishContext",
    "PublishHook",
    "ResetHook",
    "RevealProvider",
    "clear_hooks",
    "register_publish_hook",
    "register_reset_hook",
    "register_reveal_provider",
    "reveal_levels",
    "run_publish_hooks",
    "run_reset_hooks",
]
