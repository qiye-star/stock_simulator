"""权益快照与资产曲线。

写入：行情推进跨交易日时（`market._run_ticks`）调用 `record_close_snapshot`，
按 (save_id, trading_day) 幂等覆盖；一次批量推进跨多日时，持仓与现金不变，各日按各自收盘价估值。
读取：`equity_curve` = 初始点 + 已收盘各日快照 + 当前交易日实时点（不落库）。
本模块不依赖 services.market / portfolio（避免循环导入）。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.models import EquitySnapshot, Holding, Save

RANGE_POINTS = {"7d": 7, "30d": 30}
INITIAL_DAY = -1  # 初始资金起点的 trading_day（真实交易日从 0 开始）


def holding_quantities(db: Session, save_id: Any) -> dict[str, int]:
    return {
        code: qty
        for code, qty in db.execute(
            select(Holding.stock_code, Holding.quantity).where(
                Holding.save_id == save_id, Holding.quantity > 0
            )
        )
    }


def upsert_snapshot(
    db: Session, save: Save, trading_day: int, cash: int, market_value: int, tick: int
) -> None:
    """幂等写入：同一 (存档, 交易日) 已存在则覆盖。"""
    row = db.scalar(
        select(EquitySnapshot).where(
            EquitySnapshot.save_id == save.id, EquitySnapshot.trading_day == trading_day
        )
    )
    if row is None:
        row = EquitySnapshot(save_id=save.id, trading_day=trading_day)
        db.add(row)
    row.cash_cents = cash
    row.market_value_cents = market_value
    row.equity_cents = cash + market_value
    row.tick = tick


def record_close_snapshot(
    db: Session,
    save: Save,
    closing_day: int,
    state: Mapping[str, Any],
    quantities: Mapping[str, int],
    tick: int,
) -> None:
    """交易日 closing_day 收盘：state 为 advance 之后的状态，倒数第二根 history 即已收盘的一日。"""
    closes = {s["code"]: int(s["history"][-2]["close"]) for s in state["stocks"]}
    market_value = sum(qty * closes.get(code, 0) for code, qty in quantities.items())
    upsert_snapshot(db, save, closing_day, save.cash_cents, market_value, tick)


def record_entries_close(
    db: Session,
    master: Save,
    closing_day: int,
    state: Mapping[str, Any],
    tick: int,
) -> None:
    """挑战 master 跨交易日时，为全部玩家挑战存档写入 closing_day 的收盘快照（03 §7.2）。

    一条查询取 market_source_id == master.id 的玩家 (id, cash)，一条查询取持仓，批量 insert。
    各玩家持仓在批次内不变（玩家只在 master 停在当前 tt 时交易），按 master 的收盘价估值。
    唯一键 (save_id, trading_day) 冲突抛 IntegrityError，由调用方 market._retrying 整体回滚重算。
    """
    players = db.execute(
        select(Save.id, Save.cash_cents).where(Save.market_source_id == master.id)
    ).all()
    if not players:
        return
    closes = {s["code"]: int(s["history"][-2]["close"]) for s in state["stocks"]}
    market_values: dict[Any, int] = {}
    holdings = db.execute(
        select(Holding.save_id, Holding.stock_code, Holding.quantity).where(
            Holding.save_id.in_([pid for pid, _ in players]), Holding.quantity > 0
        )
    )
    for save_id, code, qty in holdings:
        market_values[save_id] = market_values.get(save_id, 0) + qty * closes.get(code, 0)
    rows = []
    for pid, cash in players:
        market_value = market_values.get(pid, 0)
        rows.append(
            {
                "id": uuid.uuid4(),
                "save_id": pid,
                "trading_day": closing_day,
                "cash_cents": cash,
                "market_value_cents": market_value,
                "equity_cents": cash + market_value,
                "tick": tick,
            }
        )
    db.execute(EquitySnapshot.__table__.insert(), rows)


def equity_curve(
    db: Session, save: Save, live_equity: tuple[int, int, int], trading_day: int, range_: str
) -> list[dict[str, Any]]:
    """资产曲线。live_equity=(equity, cash, market_value)，为当前交易日的实时点。

    只取 trading_day 小于当前交易日的快照（行情被调试重置后遗留的“未来”快照自动忽略）。
    range_ 为 7d/30d 时取完整序列的最后 N 个点，all 返回全部。
    """
    snaps = db.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.save_id == save.id, EquitySnapshot.trading_day < trading_day)
        .order_by(EquitySnapshot.trading_day)
    ).all()
    initial = save.initial_fund_cents
    points: list[dict[str, Any]] = [
        _point(INITIAL_DAY, initial, initial, 0, "initial"),
        *(
            _point(s.trading_day, s.equity_cents, s.cash_cents, s.market_value_cents, "close")
            for s in snaps
        ),
        _point(trading_day, live_equity[0], live_equity[1], live_equity[2], "live"),
    ]
    n = RANGE_POINTS.get(range_)
    return points[-n:] if n else points


def _point(day: int, equity: int, cash: int, mv: int, kind: str) -> dict[str, Any]:
    return {
        "trading_day": day,
        "equity_cents": equity,
        "cash_cents": cash,
        "market_value_cents": mv,
        "kind": kind,
    }
