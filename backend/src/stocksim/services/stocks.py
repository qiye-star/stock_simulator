"""股票池目录：读取静态数据 `data/stock_pool.json` / `data/industries.json`，并查询 stocks 表。

列表顺序即 stock_idx（行情 RNG 维度），不得重排。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocksim.models import Save, Stock
from stocksim.models.save import SAVE_MODE_REPLAY

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str
    industry: str
    profile: str
    idx: int  # stock_idx：RNG 维度，等于在股票池中的位置


@lru_cache(maxsize=1)
def stock_pool() -> tuple[StockInfo, ...]:
    raw = json.loads((DATA_DIR / "stock_pool.json").read_text(encoding="utf-8"))
    return tuple(
        StockInfo(
            code=str(row["code"]),
            name=str(row["name"]),
            industry=str(row["industry"]),
            profile=str(row.get("profile", "normal")),
            idx=idx,
        )
        for idx, row in enumerate(raw)
    )


@lru_cache(maxsize=1)
def _pool_by_code() -> dict[str, StockInfo]:
    return {info.code: info for info in stock_pool()}


def get_stock_info(code: str) -> StockInfo | None:
    return _pool_by_code().get(code)


def stock_info_for(db: Session, save: Save, code: str) -> StockInfo | None:
    """存档视角的股票信息：复盘存档按关卡（别名或真名），其余等同 get_stock_info（05 §5.3）。"""
    if save.mode == SAVE_MODE_REPLAY:
        from stocksim.services.replay import state as replay_state

        return replay_state.stock_info(db, save, code)
    return get_stock_info(code)


def info_lookup(db: Session, save: Save) -> Callable[[str], StockInfo | None]:
    """与 stock_info_for 同口径的查找函数（一次请求内复用会话上下文）。"""
    return lambda code: stock_info_for(db, save, code)


@lru_cache(maxsize=1)
def industry_ranges() -> dict[str, tuple[int, int]]:
    """行业 -> 基准价区间（元，[lo, hi]），供 domain.init_market 使用。"""
    raw = json.loads((DATA_DIR / "industries.json").read_text(encoding="utf-8"))
    return {
        str(row["name"]): (
            int(row["base_price_range_yuan"][0]),
            int(row["base_price_range_yuan"][1]),
        )
        for row in raw
    }


def list_stock_rows(db: Session) -> list[Stock]:
    return list(db.scalars(select(Stock).order_by(Stock.code)))
