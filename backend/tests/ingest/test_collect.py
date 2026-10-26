"""定时抓存（collect/daily）：去重、分文件、缺口告警、轮转与游标、调度、补抓、CLI。

全部不联网、不 sleep：时钟、睡眠与 Gateway 的限速/重试全部注入；数据为合成行。
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from stocksim.replay_ingest import cli, rawstore
from stocksim.replay_ingest.client import AkshareClient, CircuitOpen, Gateway
from stocksim.replay_ingest.collect import (
    CN_TZ,
    Collector,
    load_universe,
    normalize_cls,
)
from stocksim.replay_ingest.errors import CollectError
from stocksim.replay_ingest.rawstore import RawStore

POOL_FILE = Path(__file__).resolve().parents[2] / "src" / "stocksim" / "data" / "stock_pool.json"
MORNING = datetime(2026, 10, 26, 10, 0, tzinfo=CN_TZ)  # 20:30 之前，不触发补抓
EVENING = datetime(2026, 10, 26, 20, 20, tzinfo=CN_TZ)  # 20:30 前 10 分钟


class FakeTime:
    """假时钟：``sleep`` 直接推进时间，``now`` 与 ``clock`` 保持一致。"""

    def __init__(self, start: datetime) -> None:
        self.start = start
        self.t = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.t)


class LiveFake:
    """电报 / 个股新闻 / 补抓接口的假客户端。``script[键]`` 是按调用顺序消费的响应队列
    （元素为 list 或 Exception），耗尽后重复最后一项；没有脚本则返回空结果。
    电报的键为 ``cls_flash:全部`` / ``cls_flash:重点``，其余为方法名。"""

    version = "9.9.9-live-fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.script: dict[str, list[Any]] = {}

    def _respond(self, key: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append((key, kw))
        queue = self.script.get(key)
        if not queue:
            return []
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def cls_flash(self, symbol: str) -> list[dict[str, Any]]:
        return self._respond(f"cls_flash:{symbol}", symbol=symbol)

    def em_news(self, symbol: str) -> list[dict[str, Any]]:
        return self._respond("em_news", symbol=symbol)

    def gsrl_dynamics(self, date: str) -> list[dict[str, Any]]:
        return self._respond("gsrl_dynamics", date=date)

    def cctv_news(self, date: str) -> list[dict[str, Any]]:
        return self._respond("cctv_news", date=date)

    def cninfo_disclosure(self, code: str, start: str, end: str) -> list[dict[str, Any]]:
        return self._respond("cninfo_disclosure", code=code, start=start, end=end)

    def trade_calendar(self) -> list[dict[str, Any]]:
        return []

    def kline_daily(self, **kw: Any) -> list[dict[str, Any]]:
        return []

    def index_daily(self, **kw: Any) -> list[dict[str, Any]]:
        return []

    def keys_of(self, prefix: str) -> list[dict[str, Any]]:
        return [kw for key, kw in self.calls if key.startswith(prefix)]


def cls_row(day: str, hhmm: str, title: str, content: str = "合成正文") -> dict[str, Any]:
    return {"标题": title, "内容": content, "发布日期": day, "发布时间": hhmm}


def em_row(pub: str, title: str, url: str) -> dict[str, Any]:
    return {
        "关键词": "600036",
        "新闻标题": title,
        "新闻内容": "合成新闻正文",
        "发布时间": pub,
        "文章来源": "合成来源",
        "新闻链接": url,
    }


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "replay")


@pytest.fixture
def live() -> LiveFake:
    return LiveFake()


def _collector(
    store: RawStore,
    live: LiveFake,
    make_gateway: Callable[..., Gateway],
    ft: FakeTime,
    universe: list[str] | None = None,
    gateway: Gateway | None = None,
) -> Collector:
    gw = gateway or make_gateway(live, store)
    return Collector(
        store,
        gw,
        universe if universe is not None else ["600036", "601398", "601288"],
        now=ft.now,
        clock=ft.clock,
        sleep=ft.sleep,
    )


# ---------- 股票池 ----------


def test_pool_universe_excludes_easter_egg_and_matches_file() -> None:
    items = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    expected = [x["code"] for x in items if x["code"] != "999999"]
    assert load_universe("pool") == expected
    assert load_universe(None) == expected
    assert "999999" not in expected


def test_explicit_universe_dedupes_and_validates(tmp_path: Path) -> None:
    assert load_universe(" 600036, 601398,600036,999999 ") == ["600036", "601398"]
    with pytest.raises(CollectError, match="6 位"):
        load_universe("60036")
    with pytest.raises(CollectError, match="6 位"):
        load_universe("abc,600036")
    with pytest.raises(CollectError, match="读取股票池失败"):
        load_universe("pool", pool_file=tmp_path / "missing.json")


# ---------- 电报 ----------


def test_cls_appends_only_new_rows_partitioned_by_publish_date(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    a = cls_row("2026-10-25", "09:00:00", "甲")
    b = cls_row("2026-10-26", "10:00:00", "乙")
    c = cls_row("2026-10-26", "10:05:00", "丙")
    live.script["cls_flash:全部"] = [[a, b], [b, c]]
    ft = FakeTime(MORNING)
    col = _collector(store, live, make_gateway, ft)

    assert col.cls_cycle() == 2
    assert col.cls_cycle() == 1  # b 已存在，只新增 c
    assert [r["标题"] for r in store.read_jsonl("cls/2026-10/2026-10-25.jsonl")] == ["甲"]
    assert [r["标题"] for r in store.read_jsonl("cls/2026-10/2026-10-26.jsonl")] == ["乙", "丙"]
    assert col.failed_count == 0


def test_cls_dedupe_survives_restart(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    b = cls_row("2026-10-26", "10:00:00", "乙")
    live.script["cls_flash:全部"] = [[b]]
    ft = FakeTime(MORNING)
    _collector(store, live, make_gateway, ft).cls_cycle()
    again = _collector(store, live, make_gateway, ft)  # 新进程：从当月文件回填去重键
    assert again.cls_cycle() == 0
    assert len(store.read_jsonl("cls/2026-10/2026-10-26.jsonl")) == 1


def test_cls_importance_tags_and_keeps_important_only_items(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    a = cls_row("2026-10-26", "10:00:00", "甲")
    b = cls_row("2026-10-26", "10:01:00", "乙")
    c = cls_row("2026-10-26", "10:02:00", "丙")  # 只在 重点 里出现
    live.script["cls_flash:全部"] = [[a, b]]
    live.script["cls_flash:重点"] = [[a, c]]
    col = _collector(store, live, make_gateway, FakeTime(MORNING))
    assert col.cls_cycle() == 3
    rows = {r["标题"]: r for r in store.read_jsonl("cls/2026-10/2026-10-26.jsonl")}
    assert rows["甲"]["imp"] is True
    assert rows["乙"]["imp"] is False
    assert rows["丙"]["imp"] is True
    # 落盘行保留 AKShare 原列名，构建器据此读取
    assert {"标题", "内容", "发布日期", "发布时间"} <= set(rows["甲"])


def test_cls_gap_is_logged_only_when_consecutive_pulls_do_not_overlap(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    rows = [cls_row("2026-10-26", f"10:0{i}:00", f"标题{i}") for i in range(6)]
    live.script["cls_flash:全部"] = [rows[0:2], rows[2:4], rows[3:5]]
    col = _collector(store, live, make_gateway, FakeTime(MORNING))
    col.cls_cycle()
    col.cls_cycle()  # 与上一次没有重叠 -> 缺口
    log = store.read_jsonl(rawstore.COLLECT_LOG)
    assert [e["event"] for e in log] == ["gap_suspected"]
    assert log[0]["prev"] == 2 and log[0]["cur"] == 2
    col.cls_cycle()  # 与上一次有重叠 -> 不再记录
    assert len(store.read_jsonl(rawstore.COLLECT_LOG)) == 1


def test_cls_failures_are_isolated(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    b = cls_row("2026-10-26", "10:00:00", "乙")
    live.script["cls_flash:全部"] = [ValueError("结构变化"), [b]]
    live.script["cls_flash:重点"] = [ValueError("重点失败")]
    col = _collector(store, live, make_gateway, FakeTime(MORNING))
    assert col.cls_cycle() == 0  # 全部失败：本轮不写
    assert col.failed_count == 1
    assert col.cls_cycle() == 1  # 重点失败不影响全部：标为非重点
    assert col.failed_count == 2
    (row,) = store.read_jsonl("cls/2026-10/2026-10-26.jsonl")
    assert row["imp"] is False


def test_normalize_cls_keeps_empty_title_and_drops_unplaceable_rows() -> None:
    rows = normalize_cls(
        [
            cls_row("2026-10-26", "10:00:00", "", "只有内容"),
            cls_row("2026-10-26", "10:01:00", "", ""),
            cls_row("", "10:02:00", "没有日期"),
            cls_row("2026-10-26", "10:03:00", "超长", "字" * 900),
        ],
        important=None,
        ts_utc="2026-10-26T02:00:00Z",
    )
    assert [r["标题"] for r in rows] == ["", "超长"]
    assert len(rows[1]["内容"]) == 500


# ---------- 个股新闻 ----------


def test_em_rotation_persists_cursor_across_restart(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    ft = FakeTime(MORNING)
    col = _collector(store, live, make_gateway, ft)
    for _ in range(4):
        col.em_step()
    assert [kw["symbol"] for kw in live.keys_of("em_news")] == [
        "600036",
        "601398",
        "601288",
        "600036",
    ]
    again = _collector(store, live, make_gateway, ft)
    again.em_step()
    assert live.keys_of("em_news")[-1]["symbol"] == "601398"


def test_em_dedupes_by_url_across_restart_and_partitions_by_month(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    n1 = em_row("2026-10-25 10:00:00", "新闻一", "https://example.invalid/a/1.html")
    n2 = em_row("2026-10-26 09:00:00", "新闻二", "https://example.invalid/a/2.html")
    n3 = em_row("2026-09-30 23:00:00", "新闻三", "https://example.invalid/a/3.html")
    live.script["em_news"] = [[n1, n2], [n2, n3]]
    ft = FakeTime(MORNING)
    col = _collector(store, live, make_gateway, ft, universe=["600036"])
    assert col.em_step() == 2
    assert col.em_step() == 1
    restarted = _collector(store, live, make_gateway, ft, universe=["600036"])
    assert restarted.em_step() == 0  # 重启后回填去重键
    assert len(store.read_jsonl("em_news/600036/2026-10.jsonl")) == 2
    assert [r["新闻标题"] for r in store.read_jsonl("em_news/600036/2026-09.jsonl")] == ["新闻三"]


def test_em_failure_is_recorded_and_rotation_continues(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    live.script["em_news"] = [ValueError("格式变化"), [em_row("2026-10-26 09:00:00", "甲", "u1")]]
    col = _collector(store, live, make_gateway, FakeTime(MORNING), universe=["600036", "601398"])
    assert col.em_step() == 0
    assert col.em_step() == 1
    assert col.failed_count == 1
    assert [kw["symbol"] for kw in live.keys_of("em_news")] == ["600036", "601398"]


# ---------- 调度 ----------


def test_loop_cadence_is_120s_for_cls_and_10s_for_em(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    ft = FakeTime(MORNING)
    col = _collector(store, live, make_gateway, ft, universe=["600036", "601398"])
    col.run_loop(stop=lambda: ft.t >= 300)
    assert len(live.keys_of("cls_flash:全部")) == 3  # t = 0, 120, 240
    assert len(live.keys_of("em_news")) == 30  # t = 0, 10, ..., 290


def test_daily_runs_after_2030_and_is_not_repeated_after_restart(
    store: RawStore, live: LiveFake, make_gateway: Callable[..., Gateway]
) -> None:
    ft = FakeTime(EVENING)
    universe = ["600036", "601398"]
    col = _collector(store, live, make_gateway, ft, universe=universe)
    assert col.daily_due(EVENING) is None  # 20:20 尚未到
    col.run_loop(stop=lambda: ft.t >= 900)  # 20:30 之后约 5 分钟

    day = "2026-10-26"
    assert live.keys_of("gsrl_dynamics") == [{"date": "20261026"}]
    assert live.keys_of("cctv_news") == [{"date": "20261026"}]
    assert sorted(kw["code"] for kw in live.keys_of("cninfo_disclosure")) == universe
    assert all(kw["start"] == "20261001" for kw in live.keys_of("cninfo_disclosure"))
    assert store.exists(rawstore.gsrl_path(day))
    assert store.exists(rawstore.cctv_path(day))
    assert store.exists(rawstore.cninfo_path("600036", 2026, 4))
    assert store.read_json(rawstore.COLLECT_CURSOR)["daily_done"] == day

    restarted = _collector(store, live, make_gateway, FakeTime(EVENING + timedelta(hours=1)))
    assert restarted.daily_due(EVENING + timedelta(hours=1)) is None
    assert len(live.keys_of("gsrl_dynamics")) == 1


def test_daily_failure_is_isolated_and_circuit_open_propagates(
    store: RawStore,
    live: LiveFake,
    make_gateway: Callable[..., Gateway],
) -> None:
    live.script["cninfo_disclosure"] = [ValueError("退市股"), []]  # 第一只失败，其余照常
    col = _collector(store, live, make_gateway, FakeTime(EVENING), universe=["600036", "601398"])
    col.run_daily(EVENING.date())
    assert col.failed_count == 1
    assert store.exists(rawstore.cninfo_path("601398", 2026, 4))

    breaker = make_gateway(live, store, breaker_threshold=1)
    strict = _collector(store, live, make_gateway, FakeTime(EVENING), gateway=breaker)
    live.script["cninfo_disclosure"] = [ValueError("仍然失败")]
    with pytest.raises(CircuitOpen):
        strict.run_daily(EVENING.date())


# ---------- 客户端映射 ----------


class _FakeDF:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def to_dict(self, orient: str) -> list[dict[str, Any]]:
        return self._rows


def test_akshare_client_maps_cls_and_em_news(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    mod = types.ModuleType("akshare")
    mod.__version__ = "1.2.3"  # type: ignore[attr-defined]

    def cls(**kw: Any) -> _FakeDF:
        calls.append(("cls", kw))
        return _FakeDF([cls_row("2026-10-26", "10:00:00", "甲")])

    def em(**kw: Any) -> _FakeDF:
        calls.append(("em", kw))
        return _FakeDF([])

    mod.stock_info_global_cls = cls  # type: ignore[attr-defined]
    mod.stock_news_em = em  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", mod)

    client = AkshareClient()
    assert client.cls_flash("重点") == [cls_row("2026-10-26", "10:00:00", "甲")]
    assert client.em_news("600036") == []
    assert calls == [("cls", {"symbol": "重点"}), ("em", {"symbol": "600036"})]


# ---------- CLI ----------


def test_cli_collect_once_writes_files(
    tmp_path: Path, live: LiveFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REPLAY_COLLECT_UNIVERSE", raising=False)
    live.script["cls_flash:全部"] = [[cls_row("2026-10-26", "10:00:00", "甲")]]
    live.script["em_news"] = [[em_row("2026-10-26 09:00:00", "新闻", "u1")]]
    data = tmp_path / "data"
    rc = cli.run(
        ["--data-dir", str(data), "collect", "--once", "--universe", "600036,601398"],
        client_factory=lambda: live,
    )
    assert rc == 0
    store = RawStore(data)
    assert store.exists("cls/2026-10/2026-10-26.jsonl")
    assert store.exists("em_news/600036/2026-10.jsonl")
    assert not store.exists("em_news/601398/2026-10.jsonl")  # 一次只轮转一只


def test_cli_collect_rejects_bad_universe_and_requires_mode(tmp_path: Path, live: LiveFake) -> None:
    rc = cli.run(
        ["--data-dir", str(tmp_path), "collect", "--once", "--universe", "abc"],
        client_factory=lambda: live,
    )
    assert rc == 1
    assert live.calls == []
    with pytest.raises(SystemExit):
        cli.run(["--data-dir", str(tmp_path), "collect"], client_factory=lambda: live)
    with pytest.raises(SystemExit):
        cli.run(
            ["--data-dir", str(tmp_path), "collect", "--loop", "--interval", "5"],
            client_factory=lambda: live,
        )
