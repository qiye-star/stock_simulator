"""合约生成与结算判定（04 §3.2–§3.4）。纯函数：只读 GameEvent 的公开字段与 tick 边界。

- 只对挑战的回合事件开市（调用方经 `contracts_for_challenge(round_event_ids=...)` 过滤）。
- 窗口锚定在首次出现日 d0 = day_of(first_seen)，不锚定发布日
  （priced_in 的发布时点在发布前是隐藏的，锚定它会泄密）。
- 档位边界与窗口直接用 predictions 的公开函数，与预测卡、挑战回合题逐位一致。
- spec 不得依赖 magnitude/knots/expectation/impacts/rumor.truth；真值只在 resolve_* 中读取。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from ..clock import timebase
from ..events.types import GameEvent
from ..predictions import DIRECTION_WINDOW_DAYS, Structure, bucket_edges_bp
from ..scoring import bucket_of
from .constants import (
    BUCKET_PRIOR_PPM,
    MAX_MARKETS_PER_CHALLENGE,
    MIN_OPEN_TICKS,
    RUMOR_CLOSE_LEAD_TICKS,
    RUMOR_PRIOR_PPM,
)
from .types import ContractSpec


@dataclass(frozen=True)
class ContractContext:
    """挑战边界与公开结构。first_tt/last_tt 为挑战公共时间线上的 trading tick（last_tt 含端点）。"""

    clock_rules: int
    first_tt: int
    last_tt: int
    structure: Structure


def _check_context(ctx: ContractContext) -> None:
    if ctx.first_tt < 0 or ctx.last_tt < ctx.first_tt:
        raise ValueError("invalid challenge tick bounds")


def bucket_prior(scope: str, sentiment: int) -> tuple[int, ...]:
    """分档开盘先验（ppm，和为 1e6）。(scope, sentiment) 无统计时由 constants 给出均匀占位。"""
    return BUCKET_PRIOR_PPM[(scope, sentiment)]


def _bucket_spec(ev: GameEvent, ctx: ContractContext, f: int) -> ContractSpec | None:
    tb = timebase(ctx.clock_rules)
    d0 = tb.day_of(f)
    from_day = d0
    to_day = d0 + DIRECTION_WINDOW_DAYS - 1
    open_tt = f
    close_tt = tb.first_tt(to_day)  # 最后一个交易日开盘即停止交易（盲盘）
    resolve_tt = tb.first_tt(to_day + 1)  # to_day 收盘数据可得（次日 9:30 换日 tick）
    if resolve_tt > ctx.last_tt:
        return None
    if close_tt - open_tt < MIN_OPEN_TICKS[ctx.clock_rules]:
        return None
    if ev.scope == "industry":
        if ev.source_industry is None:
            raise ValueError("industry event without source_industry")
        industry, code = ev.source_industry, None
        n = ctx.structure.stock_count[ev.source_industry]
    elif ev.scope == "stock":
        if ev.source_code is None:
            raise ValueError("stock event without source_code")
        industry, code = None, ev.source_code
        n = 1
    elif ev.scope == "market":
        industry, code = None, None
        n = ctx.structure.stock_total
    else:
        raise ValueError(f"unknown scope: {ev.scope}")
    edges = bucket_edges_bp(ev.scope, n, DIRECTION_WINDOW_DAYS, ctx.clock_rules)
    return ContractSpec(
        kind="bucket",
        event_id=ev.event_id,
        scope=ev.scope,
        industry=industry,
        code=code,
        from_day=from_day,
        to_day=to_day,
        edges_bp=tuple(edges),
        n_outcomes=len(edges) + 1,
        prior_ppm=tuple(bucket_prior(ev.scope, ev.sentiment)),
        open_tt=open_tt,
        close_tt=close_tt,
        resolve_tt=resolve_tt,
        close_public=True,
    )


def _rumor_spec(ev: GameEvent, ctx: ContractContext, f: int) -> ContractSpec | None:
    if ev.rumor is None:
        raise ValueError("rumor event without rumor info")
    cap = min(ev.rumor.resolve_trading_tick, ctx.last_tt + 1)  # 揭晓晚于挑战末则在挑战末结算
    open_tt = f
    close_tt = cap - RUMOR_CLOSE_LEAD_TICKS[ctx.clock_rules]
    resolve_tt = cap
    if close_tt - open_tt < MIN_OPEN_TICKS[ctx.clock_rules]:
        return None
    return ContractSpec(
        kind="rumor",
        event_id=ev.event_id,
        scope=ev.scope,  # type: ignore[arg-type]
        industry=ev.source_industry,
        code=ev.source_code,
        from_day=None,
        to_day=None,
        edges_bp=(),
        n_outcomes=2,
        prior_ppm=RUMOR_PRIOR_PPM,
        open_tt=open_tt,
        close_tt=close_tt,
        resolve_tt=resolve_tt,
        close_public=False,
    )


def contracts_for_event(ev: GameEvent, ctx: ContractContext) -> tuple[ContractSpec, ...]:
    """单个事件的合约（未按挑战截断）。非重大事件返回空元组。

    重大事件：1 个 bucket（5 档）；kind=="rumor" 再加 1 个 rumor（deny, confirm）。
    过滤（任一不满足即不生成）：首次出现 ≥ first_tt；bucket 的 resolve_tt ≤ last_tt；
    close_tt − open_tt ≥ MIN_OPEN_TICKS。rumor 不因揭晓晚于挑战而被过滤（在 last_tt 结算）。
    """
    _check_context(ctx)
    if not ev.major or not ev.news:
        return ()
    f = ev.first_seen_trading_tick
    if f < ctx.first_tt:
        return ()
    out: list[ContractSpec] = []
    bucket = _bucket_spec(ev, ctx, f)
    if bucket is not None:
        out.append(bucket)
    if ev.kind == "rumor":
        rumor = _rumor_spec(ev, ctx, f)
        if rumor is not None:
            out.append(rumor)
    return tuple(out)


def contracts_for_challenge(
    events: Iterable[GameEvent],
    ctx: ContractContext,
    *,
    round_event_ids: Collection[str],
) -> tuple[ContractSpec, ...]:
    """挑战的全部市场：只取回合事件，按 (首次出现 tick, event_id, kind) 升序，截断到上限。"""
    rounds = set(round_event_ids)
    specs = [
        spec for ev in events if ev.event_id in rounds for spec in contracts_for_event(ev, ctx)
    ]
    specs.sort(key=lambda s: (s.open_tt, s.event_id, s.kind))
    return tuple(specs[:MAX_MARKETS_PER_CHALLENGE])


def resolve_rumor(ev: GameEvent) -> int:
    """传闻结算：0 = deny（辟谣），1 = confirm（证实）。与 RUMOR 选项序一致。"""
    if ev.rumor is None:
        raise ValueError("rumor event without rumor info")
    return 1 if ev.rumor.truth else 0


def resolve_bucket(spec: ContractSpec, change_bp: int) -> int:
    """分档结算：左闭右开，等于边界值进上一档（bucket_of）。"""
    if spec.kind != "bucket":
        raise ValueError("not a bucket contract")
    return bucket_of(change_bp, spec.edges_bp)
