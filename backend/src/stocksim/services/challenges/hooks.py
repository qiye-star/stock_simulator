"""挑战钩子（03 §1.3）：D 等模块的扩展点。

约定（与 A §1.5 同规则）：钩子运行在调用方事务内，**不得 commit**，必须幂等。
默认无任何注册；由 main.create_app 调用 `register_defaults()`（当前为空，D 实施时补充）。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from stocksim.models import Challenge, ChallengeRound
from stocksim.services.challenges.registry import ChallengeInfo

CreatedHook = Callable[[Session, ChallengeInfo], None]
RevokedHook = Callable[[Session, ChallengeInfo, str], None]
RoundOpenHook = Callable[[Session, Challenge, ChallengeRound], None]
RoundClosedHook = Callable[[Session, Challenge, ChallengeRound], None]
QuestionResolvedHook = Callable[[Session, Challenge, ChallengeRound, str], None]
SettledHook = Callable[[Session, Challenge], None]

_created: list[CreatedHook] = []
_revoked: list[RevokedHook] = []
_round_open: list[RoundOpenHook] = []
_round_closed: list[RoundClosedHook] = []
_question_resolved: list[QuestionResolvedHook] = []
_settled: list[SettledHook] = []


def register_challenge_hooks(on_created: CreatedHook, on_revoked: RevokedHook) -> None:
    """04 §1.2 的名字：注册生成与作废钩子。"""
    if on_created not in _created:
        _created.append(on_created)
    if on_revoked not in _revoked:
        _revoked.append(on_revoked)


def register_round_open_hook(fn: RoundOpenHook) -> None:
    if fn not in _round_open:
        _round_open.append(fn)


def register_round_closed_hook(fn: RoundClosedHook) -> None:
    if fn not in _round_closed:
        _round_closed.append(fn)


def register_question_resolved_hook(fn: QuestionResolvedHook) -> None:
    if fn not in _question_resolved:
        _question_resolved.append(fn)


def register_settled_hook(fn: SettledHook) -> None:
    if fn not in _settled:
        _settled.append(fn)


def clear_hooks() -> None:
    """仅测试用。"""
    for lst in (_created, _revoked, _round_open, _round_closed, _question_resolved, _settled):
        lst.clear()


def register_defaults() -> None:
    """main.create_app 调用。当前无默认钩子（D 实施时在此注册）。"""


def run_created(db: Session, info: ChallengeInfo) -> None:
    for fn in tuple(_created):
        fn(db, info)


def run_revoked(db: Session, info: ChallengeInfo, reason: str) -> None:
    for fn in tuple(_revoked):
        fn(db, info, reason)


def run_round_open(db: Session, ch: Challenge, rnd: ChallengeRound) -> None:
    for fn in tuple(_round_open):
        fn(db, ch, rnd)


def run_round_closed(db: Session, ch: Challenge, rnd: ChallengeRound) -> None:
    for fn in tuple(_round_closed):
        fn(db, ch, rnd)


def run_question_resolved(db: Session, ch: Challenge, rnd: ChallengeRound, qid: str) -> None:
    for fn in tuple(_question_resolved):
        fn(db, ch, rnd, qid)


def run_settled(db: Session, ch: Challenge) -> None:
    for fn in tuple(_settled):
        fn(db, ch)
