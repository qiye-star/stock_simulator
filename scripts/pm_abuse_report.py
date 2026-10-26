#!/usr/bin/env python3
"""预测市场风控报表（04 §5.5 第 4 条，§12 第 12 步）：读库，输出可疑账户 CSV。

只报告，不处罚；人工复核后再决定。规则（阈值见下方常量，均为起始值，待用真实数据校准）：
- 往返：同一账户、同一市场、同一档位，卖出紧跟（seq 距离 ≤ RT_WINDOW）着自己的买入，
  累计 ≥ RT_MIN 次。
- 对倒配对：两个不同账户在同一市场同一档位上，seq 距离 ≤ PAIR_WINDOW 的一买一卖相向成交，
  ≥ PAIR_MIN 次。
- 小号集中：同一市场、同一档位、同方向成交的账户中，注册时间落在 CLUSTER_HOURS 小时内的
  ≥ CLUSTER_MIN 个。
- 胜率异常：已结算市场的买入 ≥ WIN_MIN 笔，其中买在获胜档位的占比 ≥ WIN_RATIO。
附带列 early_confirm（只报告，不据此标记）：买入后 WIN_TICKS 个 seq 之内，同档价格继续上涨的占比。

用法（读库需要 SQLAlchemy，用 backend 环境运行）：
  cd backend && uv run python ../scripts/pm_abuse_report.py --database-url sqlite:///x.db \
    [--challenge <uuid>] [--out risk.csv]
  DATABASE_URL 环境变量可代替 --database-url。
  cd backend && uv run python ../scripts/pm_abuse_report.py --sample
    构造作弊样本并校验每条规则都能检出、正常账户不被标记；漏检则退出码 1。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

RT_WINDOW = 10  # 往返：卖出与买入的 seq 距离上限
RT_MIN = 3  # 往返：账户累计次数下限
PAIR_WINDOW = 3  # 对倒配对：相向成交的 seq 距离上限
PAIR_MIN = 3  # 对倒配对：两账户相向成交次数下限
CLUSTER_HOURS = 24  # 小号集中：注册时间窗口（小时）
CLUSTER_MIN = 3  # 小号集中：同窗口内同向成交的账户数下限
WIN_TICKS = 5  # 早期确认：买入后观察的 seq 距离
WIN_MIN = 8  # 胜率异常：已结算买入笔数下限
WIN_RATIO = 0.85  # 胜率异常：获胜占比下限

FLAG_ORDER = ("往返", "对倒配对", "小号集中", "胜率异常")
CSV_FIELDS = (
    "username",
    "user_id",
    "flags",
    "round_trips",
    "pair_partners",
    "cluster_hits",
    "settled_buys",
    "win_ratio",
    "early_confirm",
    "created_at",
)


@dataclass(frozen=True)
class Trade:
    user_id: str
    market_id: str
    seq: int
    side: str  # buy | sell
    outcome: int
    prices_after: tuple[int, ...]  # 成交后各档价格（ppm）
    winning: int | None  # 市场获胜档位；未结算为 None


@dataclass(frozen=True)
class User:
    username: str
    created_at: datetime


def _new_detail() -> dict[str, Any]:
    return {
        "round_trips": 0,
        "pair_partners": set(),
        "cluster_hits": 0,
        "settled_buys": 0,
        "wins": 0,
        "confirm": 0,
        "confirm_n": 0,
    }


def detect(trades: list[Trade], users: dict[str, User]) -> list[dict[str, Any]]:
    """纯函数：按上述规则给出可疑账户行（只含至少命中一条规则的账户），按命中数降序。"""
    flags: dict[str, set[str]] = defaultdict(set)
    detail: dict[str, dict[str, Any]] = defaultdict(_new_detail)

    by_market: dict[str, list[Trade]] = defaultdict(list)
    per_user_market: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for t in trades:
        by_market[t.market_id].append(t)
        per_user_market[(t.user_id, t.market_id)].append(t)
    for ts in by_market.values():
        ts.sort(key=lambda t: t.seq)

    # 往返
    for (uid, _), ts in per_user_market.items():
        open_buys: dict[int, list[int]] = defaultdict(list)
        for t in sorted(ts, key=lambda t: t.seq):
            q = open_buys[t.outcome]
            if t.side == "buy":
                q.append(t.seq)
                continue
            while q and t.seq - q[0] > RT_WINDOW:
                q.pop(0)
            if q:
                q.pop(0)
                detail[uid]["round_trips"] += 1
    for uid, d in detail.items():
        if d["round_trips"] >= RT_MIN:
            flags[uid].add("往返")

    # 对倒配对：同市场同档位，seq 相近的相向成交
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for ts in by_market.values():
        for k in {t.outcome for t in ts}:
            group = [t for t in ts if t.outcome == k]
            for j, b in enumerate(group):
                for i in range(j - 1, -1, -1):
                    a = group[i]
                    if b.seq - a.seq > PAIR_WINDOW:
                        break
                    if a.user_id != b.user_id and a.side != b.side:
                        pair_counts[tuple(sorted((a.user_id, b.user_id)))] += 1
    for (u, v), n in pair_counts.items():
        if n >= PAIR_MIN:
            for x, y in ((u, v), (v, u)):
                flags[x].add("对倒配对")
                detail[x]["pair_partners"].add(y)

    # 小号集中：同市场同档位同方向，注册时间相近的账户扎堆
    for ts in by_market.values():
        for k in {t.outcome for t in ts}:
            for side in ("buy", "sell"):
                uids = sorted(
                    {
                        t.user_id
                        for t in ts
                        if t.outcome == k and t.side == side and t.user_id in users
                    },
                    key=lambda uid: users[uid].created_at,
                )
                window = timedelta(hours=CLUSTER_HOURS)
                for i, anchor in enumerate(uids):
                    members = [
                        uid
                        for uid in uids[i:]
                        if users[uid].created_at - users[anchor].created_at <= window
                    ]
                    if len(members) >= CLUSTER_MIN:
                        for uid in members:
                            flags[uid].add("小号集中")
                            detail[uid]["cluster_hits"] += 1

    # 胜率异常与早期确认
    for t in trades:
        if t.side != "buy":
            continue
        d = detail[t.user_id]
        if t.winning is not None:
            d["settled_buys"] += 1
            if t.outcome == t.winning:
                d["wins"] += 1
        later = next((u for u in by_market[t.market_id] if u.seq >= t.seq + WIN_TICKS), None)
        if later is not None:
            d["confirm_n"] += 1
            if later.prices_after[t.outcome] > t.prices_after[t.outcome]:
                d["confirm"] += 1
    for uid, d in detail.items():
        if d["settled_buys"] >= WIN_MIN and d["wins"] / d["settled_buys"] >= WIN_RATIO:
            flags[uid].add("胜率异常")

    names = {uid: u.username for uid, u in users.items()}
    rows = []
    for uid, fs in flags.items():
        if not fs:
            continue
        d = detail[uid]
        user = users.get(uid)
        rows.append(
            {
                "username": names.get(uid, ""),
                "user_id": uid,
                "flags": "|".join(f for f in FLAG_ORDER if f in fs),
                "round_trips": d["round_trips"],
                "pair_partners": ";".join(sorted(names.get(p, p) for p in d["pair_partners"])),
                "cluster_hits": d["cluster_hits"],
                "settled_buys": d["settled_buys"],
                "win_ratio": round(d["wins"] / d["settled_buys"], 3) if d["settled_buys"] else "",
                "early_confirm": round(d["confirm"] / d["confirm_n"], 3) if d["confirm_n"] else "",
                "created_at": user.created_at.isoformat() if user else "",
            }
        )
    rows.sort(key=lambda r: (-len(r["flags"].split("|")), r["username"]))
    return rows


def _aware(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def load(database_url: str, challenge_id: str | None = None) -> tuple[list[Trade], dict[str, User]]:
    """从库读取成交与用户（原生 SQL，sqlite 与 PostgreSQL 通用）。"""
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    where = "WHERE m.challenge_id = :cid" if challenge_id else ""
    params = {"cid": challenge_id} if challenge_id else {}
    with engine.connect() as conn:
        users = {
            str(r[0]): User(username=r[1], created_at=_aware(r[2]))
            for r in conn.execute(text("SELECT id, username, created_at FROM users"))
        }
        trades = []
        for r in conn.execute(
            text(
                "SELECT t.user_id, t.market_id, t.seq, t.side, t.outcome_idx, "
                "t.prices_after_ppm, m.winning_outcome "
                "FROM prediction_trades t JOIN prediction_markets m ON m.id = t.market_id "
                f"{where}"
            ),
            params,
        ):
            prices = json.loads(r[5]) if isinstance(r[5], str) else r[5]
            trades.append(
                Trade(
                    user_id=str(r[0]),
                    market_id=str(r[1]),
                    seq=int(r[2]),
                    side=r[3],
                    outcome=int(r[4]),
                    prices_after=tuple(int(p) for p in prices),
                    winning=None if r[6] is None else int(r[6]),
                )
            )
    engine.dispose()
    return trades, users


def sample() -> tuple[list[Trade], dict[str, User], dict[str, set[str]]]:
    """构造作弊样本。返回 (成交, 用户, 期望命中的规则：{username: {flag,...}})。"""
    base = datetime(2026, 10, 1, tzinfo=UTC)
    old = datetime(2026, 8, 1, tzinfo=UTC)
    users: dict[str, User] = {}
    # 正常账户：注册时间彼此相隔数天，互不扎堆
    for i in range(4):
        users[f"clean{i}"] = User(f"clean{i}", old + timedelta(days=10 * i))
    users["insider"] = User("insider", base - timedelta(days=20))
    users["cheat"] = User("cheat", base - timedelta(days=40))
    for i in range(3):  # 小号：一小时间隔批量注册
        users[f"sybil{i}"] = User(f"sybil{i}", base + timedelta(hours=i))

    # 市场：档位与获胜档位
    markets = {"m0": 0, "m1": 1, "m2": 2, "m3": 1, "m4": 0}
    prices = (333_333, 333_333, 333_334)
    trades: list[Trade] = []

    def add(user: str, market: str, seq: int, side: str, outcome: int) -> None:
        trades.append(Trade(user, market, seq, side, outcome, prices, markets[market]))

    # 往返：同一市场同一档位买卖 3 轮
    for k in range(3):
        add("cheat", "m0", 1 + 2 * k, "buy", 2)
        add("cheat", "m0", 2 + 2 * k, "sell", 2)

    # 对倒配对 + 小号集中：三个小号在三个市场同档位同向买入，并与相邻成交相向
    for mk in ("m1", "m2", "m3"):
        add("sybil0", mk, 10, "buy", 1)
        add("sybil1", mk, 11, "buy", 1)
        add("sybil2", mk, 12, "buy", 1)
        add("sybil1", mk, 13, "sell", 1)

    # 胜率异常：9 笔买入全部押中已结算市场的获胜档位
    for i in range(9):
        mk = list(markets)[i % len(markets)]
        add("insider", mk, 100 + i, "buy", markets[mk])

    # 正常账户：少量买入，胜负随机分布，不触发任何规则
    for i in range(4):
        for j, mk in enumerate(("m0", "m1")):
            add(f"clean{i}", mk, 200 + 10 * i + j, "buy", (i + j) % 3)

    expected = {
        "cheat": {"往返"},
        "sybil0": {"小号集中", "对倒配对"},
        "sybil1": {"小号集中", "对倒配对"},
        "sybil2": {"小号集中", "对倒配对"},
        "insider": {"胜率异常"},
    }
    return trades, users, expected


def _write(rows: list[dict[str, Any]], out) -> None:
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r[k] for k in CSV_FIELDS})


def run_sample() -> int:
    trades, users, expected = sample()
    rows = detect(trades, users)
    _write(rows, sys.stdout)
    hit = {r["username"]: set(r["flags"].split("|")) for r in rows}
    missed = {u: fs - hit.get(u, set()) for u, fs in expected.items() if fs - hit.get(u, set())}
    extra = sorted(set(hit) - set(expected))
    if missed or extra:
        print(f"SAMPLE FAIL missed={missed} unexpected={extra}", file=sys.stderr)
        return 1
    print("SAMPLE OK: 所有作弊样本被检出，正常账户未被标记", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--challenge", help="只看某个挑战（challenges.id）的市场；缺省为全库")
    parser.add_argument("--out", help="CSV 输出路径；缺省输出到标准输出")
    parser.add_argument("--sample", action="store_true", help="构造作弊样本并自检")
    args = parser.parse_args()

    if args.sample:
        return run_sample()
    if not args.database_url:
        parser.error("需要 --database-url 或 DATABASE_URL")
    trades, users = load(args.database_url, args.challenge)
    rows = detect(trades, users)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            _write(rows, fh)
        print(f"可疑账户 {len(rows)} 个 -> {args.out}", file=sys.stderr)
    else:
        _write(rows, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
