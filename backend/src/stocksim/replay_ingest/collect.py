"""定时抓存（05 §2.5）：财联社电报、东财个股新闻，以及每日盘后补抓。

只用标准库；网络访问全部经 ``Gateway``（限速、重试、熔断、fetch_log），不导入 akshare。

调度（单进程，``Collector.run_loop``，不需要 cron）：
- 每 ``interval`` 秒（默认 120）抓一次 cls：``全部`` 与 ``重点`` 各一次，去重后追加到
  ``cls/<yyyy-mm>/<发布日期>.jsonl``。相邻两次 ``全部`` 没有任何重叠时写 ``gap_suspected``。
- 每 10 秒轮转一只股票抓个股新闻，去重后追加到 ``em_news/<code>/<yyyy-mm>.jsonl``。
- 北京时间 20:30 起排一批补抓（公司动态、新闻联播、股票池当季公告）。补抓按条执行，与上面两路
  交错进行，不阻塞快讯节奏；全部完成后在 cursor 记下 ``daily_done``，同一天重启不会重跑。

落盘行保留 AKShare 原列名（标题/内容/发布日期/发布时间），与构建器读取 cls 的方式一致，
另加 ``key``（去重键）、``imp``（是否在 ``重点`` 列表中）、``ts_utc``。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any

from . import rawstore
from .client import CircuitOpen, Gateway
from .errors import CollectError
from .fetch import Fetcher
from .rawstore import RawStore

CN_TZ = timezone(timedelta(hours=8))  # 中国大陆无夏令时，固定 +08:00
CLS_INTERVAL_S = 120
EM_STEP_S = 10
IDLE_TICK_S = 1.0
DAILY_AT = dtime(20, 30)
DEDUPE_CAP = 2000
CONTENT_LIMIT = 500
EASTER_EGG_CODE = "999999"  # 股票池里的彩蛋条目，不是真实 A 股，抓存时排除
UNIVERSE_ENV = "REPLAY_COLLECT_UNIVERSE"
POOL_FILE_ENV = "REPLAY_POOL_FILE"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}")

Row = dict[str, Any]


# ---------- 股票池 ----------


def default_pool_file() -> Path:
    env = os.environ.get(POOL_FILE_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data" / "stock_pool.json"


def is_stock_code(code: str) -> bool:
    return len(code) == 6 and code.isdigit()


def load_universe(spec: str | None, *, pool_file: Path | None = None) -> list[str]:
    """``pool``（默认）读股票池，否则为逗号分隔的 6 位代码；排除彩蛋 999999，去重保序。"""
    text = (spec or "").strip() or "pool"
    if text == "pool":
        try:
            items = json.loads((pool_file or default_pool_file()).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CollectError(f"读取股票池失败：{exc}") from exc
        if not isinstance(items, list):
            raise CollectError("股票池文件须为 JSON 数组")
        raw = [str(item.get("code", "")).strip() for item in items if isinstance(item, dict)]
    else:
        raw = [c.strip() for c in text.split(",") if c.strip()]
    codes = list(dict.fromkeys(c for c in raw if c != EASTER_EGG_CODE))
    if not codes:
        raise CollectError("抓存股票池为空")
    bad = [c for c in codes if not is_stock_code(c)]
    if bad:
        raise CollectError(f"不是 6 位数字代码：{bad[:5]}")
    return codes


# ---------- 归一化与去重 ----------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def em_key(url: str, pub_time: str, title: str) -> str:
    """个股新闻去重键 ``sha1(新闻链接)``；没有链接时退回 ``发布时间 + 标题``。"""
    return hashlib.sha1((url or f"{pub_time}{title}").encode()).hexdigest()


def normalize_cls(
    rows: Iterable[Mapping[str, Any]], *, important: set[str] | None, ts_utc: str
) -> list[Row]:
    """电报行 -> 落盘行。``important`` 为 None 表示没有取到 ``重点`` 列表，``imp`` 记 False。

    丢弃发布日期不合法、或标题与内容都为空的行（标题可能为空串，05 §2.1）。
    """
    out: list[Row] = []
    for r in rows:
        title = _text(r.get("标题"))
        content = _text(r.get("内容"))
        pub_date = _text(r.get("发布日期"))
        pub_time = _text(r.get("发布时间"))
        if not _DATE_RE.match(pub_date) or not (title or content):
            continue
        key = rawstore.cls_key(pub_date, pub_time, title, content)
        out.append(
            {
                "标题": title,
                "内容": content[:CONTENT_LIMIT],
                "发布日期": pub_date,
                "发布时间": pub_time,
                "key": key,
                "imp": important is not None and key in important,
                "ts_utc": ts_utc,
            }
        )
    return out


def normalize_em(code: str, rows: Iterable[Mapping[str, Any]], *, ts_utc: str) -> list[Row]:
    out: list[Row] = []
    for r in rows:
        title = _text(r.get("新闻标题"))
        url = _text(r.get("新闻链接"))
        pub = _text(r.get("发布时间"))
        content = _text(r.get("新闻内容"))
        if not (title or url):
            continue
        out.append(
            {
                "关键词": _text(r.get("关键词")) or code,
                "新闻标题": title,
                "新闻内容": content[:CONTENT_LIMIT],
                "发布时间": pub,
                "文章来源": _text(r.get("文章来源")),
                "新闻链接": url,
                "key": em_key(url, pub, title),
                "ts_utc": ts_utc,
            }
        )
    return out


class _Seen:
    """有上限的去重集合：只保留最近插入的 ``cap`` 个键。"""

    def __init__(self, cap: int = DEDUPE_CAP) -> None:
        self._cap = cap
        self._keys: OrderedDict[str, None] = OrderedDict()

    def __contains__(self, key: object) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        self._keys[key] = None
        self._keys.move_to_end(key)
        while len(self._keys) > self._cap:
            self._keys.popitem(last=False)


# ---------- 调度 ----------


class Collector:
    """抓存编排。所有时间与睡眠都可注入，便于不联网、不等待地测试。"""

    def __init__(
        self,
        store: RawStore,
        gateway: Gateway,
        universe: Iterable[str],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.gw = gateway
        self.universe = list(universe)
        self._now = now
        self._clock = clock
        self._sleep = sleep
        self._say = progress or (lambda _msg: None)
        self.failed_count = 0

        cursor = store.read_json(rawstore.COLLECT_CURSOR)
        cursor = cursor if isinstance(cursor, dict) else {}
        try:
            em_index = int(cursor.get("em_index") or 0)
        except (TypeError, ValueError):
            em_index = 0
        self._em_index = em_index % max(len(self.universe), 1)
        prev_keys = cursor.get("cls_prev_keys")
        self._cls_prev: list[str] = (
            [k for k in prev_keys if isinstance(k, str)] if isinstance(prev_keys, list) else []
        )
        done = cursor.get("daily_done")
        self._daily_done: str | None = done if isinstance(done, str) else None

        self._pending: deque[tuple[str, Callable[[], None]]] = deque()
        self._pending_date: str | None = None
        self._cls_seen = _Seen()
        self._em_seen: dict[str, tuple[str, _Seen]] = {}
        self._backfill_cls()

    # ----- 小工具 -----

    def _ts(self) -> str:
        return self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _months(self) -> tuple[str, str]:
        """(上个月, 本月)，按北京时间。"""
        cur = self._now().astimezone(CN_TZ).date()
        prev = cur.replace(day=1) - timedelta(days=1)
        return prev.strftime("%Y-%m"), cur.strftime("%Y-%m")

    def _fail(self, label: str, exc: Exception) -> None:
        self.failed_count += 1
        self._say(f"FAIL {label}: {type(exc).__name__}: {exc}")

    def _save_cursor(self) -> None:
        self.store.write_json(
            rawstore.COLLECT_CURSOR,
            {
                "em_index": self._em_index,
                "cls_prev_keys": self._cls_prev,
                "daily_done": self._daily_done,
            },
        )

    def _log_event(self, event: str, **fields: Any) -> None:
        entry = {"ts_utc": self._ts(), "event": event, **fields}
        self.store.append_jsonl(rawstore.COLLECT_LOG, [entry])

    def _backfill_cls(self) -> None:
        """启动时从本月与上月的电报文件回填去重键（最多 DEDUPE_CAP 个）。"""
        for ym in self._months():
            d = self.store.root / "cls" / ym
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.jsonl")):
                for row in self.store.read_jsonl(f"cls/{ym}/{p.name}"):
                    key = row.get("key")
                    if not isinstance(key, str):
                        key = rawstore.cls_key(
                            _text(row.get("发布日期")),
                            _text(row.get("发布时间")),
                            _text(row.get("标题")),
                            _text(row.get("内容")),
                        )
                    self._cls_seen.add(key)

    def _em_seen_for(self, code: str) -> _Seen:
        prev, cur = self._months()
        cached = self._em_seen.get(code)
        if cached is not None and cached[0] == cur:
            return cached[1]
        seen = _Seen()
        for ym in (prev, cur):
            for row in self.store.read_jsonl(rawstore.em_news_path(code, ym)):
                key = row.get("key")
                if not isinstance(key, str):
                    key = em_key(
                        _text(row.get("新闻链接")),
                        _text(row.get("发布时间")),
                        _text(row.get("新闻标题")),
                    )
                seen.add(key)
        self._em_seen[code] = (cur, seen)
        return seen

    # ----- 快讯（财联社电报） -----

    def cls_cycle(self) -> int:
        """抓一轮电报（全部 + 重点），追加新行；返回新增条数。单项失败只记录。"""
        ts = self._ts()
        try:
            all_raw = self.gw.call("cls_flash", symbol="全部")
        except CircuitOpen:
            raise
        except Exception as exc:
            self._fail("cls 全部", exc)
            return 0

        imp_rows: list[Row] | None
        try:
            imp_rows = normalize_cls(
                self.gw.call("cls_flash", symbol="重点"), important=None, ts_utc=ts
            )
        except CircuitOpen:
            raise
        except Exception as exc:
            self._fail("cls 重点", exc)
            imp_rows = None
        important = {r["key"] for r in imp_rows} if imp_rows is not None else None

        rows = normalize_cls(all_raw, important=important, ts_utc=ts)
        keys = [r["key"] for r in rows]
        if keys and self._cls_prev and not set(keys) & set(self._cls_prev):
            self._log_event("gap_suspected", stream="cls", prev=len(self._cls_prev), cur=len(keys))
            self._say("WARN cls: 相邻两次抓取没有重叠，可能漏抓")
        if keys:
            self._cls_prev = keys
            self._save_cursor()
        # 重点里有、全部里没有的（两次调用之间刚进来的）也要存，并标为重点
        all_keys = set(keys)
        rows += [dict(r, imp=True) for r in imp_rows or [] if r["key"] not in all_keys]

        groups: dict[str, list[Row]] = {}
        for r in rows:
            if r["key"] in self._cls_seen:
                continue
            self._cls_seen.add(r["key"])
            groups.setdefault(r["发布日期"], []).append(r)
        added = sum(
            self.store.append_jsonl(rawstore.cls_path(day), group)
            for day, group in sorted(groups.items())
        )
        self._say(f"cls: 全部 {len(all_raw)}，重点 {len(imp_rows or [])}，新增 {added}")
        return added

    # ----- 个股新闻（东财） -----

    def em_step(self) -> int:
        """轮转一只股票抓个股新闻；游标写入 cursor，重启后接着轮转。返回新增条数。"""
        if not self.universe:
            return 0
        code = self.universe[self._em_index]
        self._em_index = (self._em_index + 1) % len(self.universe)
        self._save_cursor()
        ts = self._ts()
        try:
            raw = self.gw.call("em_news", symbol=code)
        except CircuitOpen:
            raise
        except Exception as exc:
            self._fail(f"em_news {code}", exc)
            return 0

        seen = self._em_seen_for(code)
        cur = self._months()[1]
        groups: dict[str, list[Row]] = {}
        for r in normalize_em(code, raw, ts_utc=ts):
            if r["key"] in seen:
                continue
            seen.add(r["key"])
            ym = r["发布时间"][:7] if _MONTH_RE.match(r["发布时间"]) else cur
            groups.setdefault(ym, []).append(r)
        added = sum(
            self.store.append_jsonl(rawstore.em_news_path(code, ym), group)
            for ym, group in sorted(groups.items())
        )
        self._say(f"个股新闻 {code}: 返回 {len(raw)}，新增 {added}")
        return added

    # ----- 每日补抓 -----

    def enqueue_daily(self, day: date) -> None:
        """排入当日补抓：新闻联播、公司动态、股票池当季公告（强制重抓，覆盖当日已有文件）。"""
        if self._pending:
            return
        iso = day.isoformat()
        fetcher = Fetcher(
            self.store,
            self.gw,
            today=lambda: iso,
            utc_now=self._ts,
            force=True,
            progress=self._say,
        )
        year, quarter = day.year, (day.month - 1) // 3 + 1
        jobs: list[tuple[str, Callable[[], None]]] = [
            (f"gsrl {iso}", lambda: fetcher.gsrl(iso)),
            (f"cctv {iso}", lambda: fetcher.cctv(iso)),
        ]
        for code in self.universe:
            jobs.append(
                (
                    f"cninfo {code} {year}Q{quarter}",
                    lambda c=code: fetcher.cninfo(c, year, quarter),
                )
            )
        self._pending = deque(jobs)
        self._pending_date = iso
        self._say(f"daily {iso}: 排入 {len(jobs)} 项补抓")

    def daily_due(self, now_local: datetime) -> date | None:
        """北京时间 20:30 之后、且当日尚未完成时返回当日（重启后也会补跑）。"""
        if self._pending or now_local.time() < DAILY_AT:
            return None
        day = now_local.date()
        return None if self._daily_done == day.isoformat() else day

    def step_daily(self) -> bool:
        """执行一项待办补抓；没有待办返回 False。全部完成时记下 ``daily_done``。"""
        if not self._pending:
            return False
        label, job = self._pending.popleft()
        try:
            job()
        except CircuitOpen:
            raise
        except Exception as exc:
            self._fail(label, exc)
        if not self._pending and self._pending_date is not None:
            self._daily_done = self._pending_date
            self._pending_date = None
            self._save_cursor()
            self._say(f"daily {self._daily_done} 完成")
        return True

    def run_daily(self, day: date) -> None:
        """单次运行当日补抓（``daily`` 子命令）。"""
        self.enqueue_daily(day)
        while self.step_daily():
            pass

    # ----- 入口 -----

    def tick_once(self) -> None:
        """``collect --once``：一轮电报 + 轮转一只个股新闻。"""
        self.cls_cycle()
        self.em_step()

    def run_loop(
        self, *, interval_s: float = CLS_INTERVAL_S, stop: Callable[[], bool] = lambda: False
    ) -> None:
        """``collect --loop``：常驻。``CircuitOpen`` 原样抛出（CLI 以退出码 2 结束）。"""
        next_cls = self._clock()
        next_em = self._clock()
        while not stop():
            if self._clock() >= next_cls:
                self.cls_cycle()
                next_cls = self._clock() + interval_s
            if self._clock() >= next_em:
                self.em_step()
                next_em = self._clock() + EM_STEP_S
            day = self.daily_due(self._now().astimezone(CN_TZ))
            if day is not None:
                self.enqueue_daily(day)
            if self.step_daily():
                continue  # 补抓本身由 Gateway 限速，不再额外睡眠
            wait = min(next_cls, next_em) - self._clock()
            self._sleep(min(max(wait, 0.0), IDLE_TICK_S))
