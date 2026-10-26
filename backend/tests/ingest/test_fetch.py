"""抓取层：FakeClient + 临时目录，不联网、不 sleep。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stocksim.replay_ingest import cli, rawstore
from stocksim.replay_ingest.client import CircuitOpen, Gateway
from stocksim.replay_ingest.fetch import (
    Fetcher,
    normalize_index,
    normalize_kline,
    quarter_range,
)
from stocksim.replay_ingest.rawstore import RawStore
from stocksim.replay_ingest.spec import Spec

if TYPE_CHECKING:
    from conftest import FakeClient

FIXED_NOW = "2024-01-01T00:00:00Z"  # 与 conftest 的 FIXED_NOW 一致（测试模块之间不互相 import）
FIXED_TODAY = "2024-01-01"

# 抓取层负责的目录；cls/ 由 E5 抓存产生，不在这里比较
FETCH_OWNED = ("calendar", "kline", "index", "cninfo", "gsrl", "cctv")


def _tree(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sub in FETCH_OWNED:
        for p in sorted((root / sub).rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            text = p.read_text(encoding="utf-8")
            out[rel] = (
                [json.loads(line) for line in text.splitlines() if line]
                if p.suffix == ".jsonl"
                else json.loads(text)
            )
    return out


def _fetcher(gw: Gateway, store: RawStore, **kw: Any) -> Fetcher:
    return Fetcher(store, gw, today=lambda: FIXED_TODAY, utc_now=lambda: FIXED_NOW, **kw)


def test_fetch_spec_reproduces_fixture_raw(
    spec_min: Spec,
    fake_client: FakeClient,
    make_gateway: Callable[..., Gateway],
    empty_store: RawStore,
    fixture_dir: Path,
) -> None:
    """FakeClient（原生列名）经 fetch 落盘后，必须与夹具 raw/ 逐文件内容一致。"""
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    summary = f.fetch_spec(spec_min)
    assert summary.ok
    assert _tree(empty_store.root) == _tree(fixture_dir / "raw")
    # 日历缺失时由 fetch 自己抓；K 线从窗口首日的前一交易日抓起
    assert len(fake_client.calls_of("trade_calendar")) == 1
    cal = empty_store.read_json(rawstore.calendar_path())["rows"]
    assert fake_client.calls_of("kline_daily")[0]["start"] == cal[4].replace("-", "")
    assert fake_client.calls_of("kline_daily")[0]["end"] == cal[29].replace("-", "")


def test_second_run_makes_no_requests(
    spec_min: Spec,
    fake_client: FakeClient,
    make_gateway: Callable[..., Gateway],
    empty_store: RawStore,
) -> None:
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    f.fetch_spec(spec_min)
    fake_client.calls.clear()
    f2 = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    s = f2.fetch_spec(spec_min)
    assert fake_client.calls == []
    assert s.fetched == 0
    assert s.skipped > 0


def test_force_refetches_everything(
    spec_min: Spec,
    fake_client: FakeClient,
    make_gateway: Callable[..., Gateway],
    empty_store: RawStore,
) -> None:
    _fetcher(make_gateway(fake_client, empty_store), empty_store).fetch_spec(spec_min)
    n = len(fake_client.calls)
    fake_client.calls.clear()
    _fetcher(make_gateway(fake_client, empty_store), empty_store, force=True).fetch_spec(spec_min)
    assert len(fake_client.calls) == n - 1  # 日历已在本地，不再抓


def test_kline_incremental_only_requests_after_last_date(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    f.kline("300001", "none", "2023-06-08", "2023-06-30")
    rows = empty_store.read_jsonl(rawstore.kline_path("none", "300001"))
    assert rows[-1]["d"] == "2023-06-30"
    fake_client.calls.clear()
    f.kline("300001", "none", "2023-06-08", "2023-07-14")
    (call,) = fake_client.calls_of("kline_daily")
    assert call["start"] == "20230701"  # 最后一行的下一天
    assert call["end"] == "20230714"
    rows = empty_store.read_jsonl(rawstore.kline_path("none", "300001"))
    dates = [r["d"] for r in rows]
    assert dates == sorted(set(dates))
    assert dates[0] == "2023-06-08"
    assert dates[-1] == "2023-07-14"


def test_kline_earlier_start_refetches_and_merges(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    f.kline("300001", "none", "2023-06-20", "2023-06-30")
    fake_client.calls.clear()
    f.kline("300001", "none", "2023-06-08", "2023-06-30")
    (call,) = fake_client.calls_of("kline_daily")
    assert call["start"] == "20230608"
    dates = [r["d"] for r in empty_store.read_jsonl(rawstore.kline_path("none", "300001"))]
    assert dates == sorted(set(dates))
    assert dates[0] == "2023-06-08"


def test_kline_end_is_clamped_to_today(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    f = Fetcher(
        empty_store,
        make_gateway(fake_client, empty_store),
        today=lambda: "2023-06-15",
        utc_now=lambda: FIXED_NOW,
    )
    f.kline("300001", "none", "2023-06-08", "2023-07-30")
    assert fake_client.calls_of("kline_daily")[0]["end"] == "20230615"


def test_current_quarter_is_refetched_finished_quarter_is_not(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    gw = make_gateway(fake_client, empty_store)
    f = Fetcher(empty_store, gw, today=lambda: "2023-07-20", utc_now=lambda: FIXED_NOW)
    f.cninfo("600001", 2023, 2)
    f.cninfo("600001", 2023, 3)
    fake_client.calls.clear()
    f.cninfo("600001", 2023, 2)  # 已结束且文件存在：跳过
    f.cninfo("600001", 2023, 3)  # 当前季度：重抓，end 截到今天
    (call,) = fake_client.calls_of("cninfo_disclosure")
    assert call == {"code": "600001", "start": "20230701", "end": "20230720"}
    f.cninfo("600001", 2023, 4)  # 未来季度：不请求
    assert len(fake_client.calls_of("cninfo_disclosure")) == 1


def test_quarter_range() -> None:
    assert quarter_range(2023, 1) == ("2023-01-01", "2023-03-31")
    assert quarter_range(2023, 4) == ("2023-10-01", "2023-12-31")
    assert quarter_range(2024, 1) == ("2024-01-01", "2024-03-31")


def test_gsrl_empty_day_is_stored_as_empty_rows(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    f.gsrl("2023-07-10")  # FakeClient 无此日文件 = 当日无数据（result=None 的形状）
    payload = empty_store.read_json(rawstore.gsrl_path("2023-07-10"))
    assert payload["rows"] == []
    assert payload["fn"] == "stock_gsrl_gsdt_em"
    assert payload["args"] == {"date": "20230710"}
    assert payload["akshare_version"] == "9.9.9-fixture"
    assert f.summary.failed == []


def test_gsrl_truncation_warning(
    make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    class Big:
        version = "t"

        def gsrl_dynamics(self, date: str) -> list[dict[str, Any]]:
            return [{"代码": str(i)} for i in range(5000)]

    f = _fetcher(make_gateway(Big(), empty_store), empty_store)
    f.gsrl("2023-07-10")
    assert any("截断" in w for w in f.summary.warnings)


def test_cctv_zero_rows_warns_but_2016_02_03_does_not(
    fake_client: FakeClient, make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    f.cctv("2016-02-03")  # 接口对该日返回 None，按空结果处理且不告警
    assert f.summary.warnings == []
    f.cctv("2023-07-10")
    assert len(f.summary.warnings) == 1


def test_single_item_failure_is_isolated(
    spec_min: Spec,
    fake_client: FakeClient,
    make_gateway: Callable[..., Gateway],
    empty_store: RawStore,
    fixture_dir: Path,
) -> None:
    fake_client.errors["cninfo_disclosure"] = lambda kw: (
        KeyError(kw["code"]) if kw["code"] == "000001" else None
    )  # 复现退市股触发的 KeyError
    f = _fetcher(make_gateway(fake_client, empty_store), empty_store)
    summary = f.fetch_spec(spec_min)
    assert not summary.ok
    assert len(summary.failed) == 2  # 000001 的两个季度
    assert all("cninfo 000001" in x for x in summary.failed)
    tree = _tree(empty_store.root)
    assert "cninfo/600001/2023Q3.json" in tree  # 其它股票照常抓取
    assert "cninfo/000001/2023Q3.json" not in tree


def test_circuit_open_propagates(
    spec_min: Spec,
    fake_client: FakeClient,
    make_gateway: Callable[..., Gateway],
    empty_store: RawStore,
) -> None:
    fake_client.errors["kline_daily"] = lambda kw: ValueError("bad")
    f = _fetcher(make_gateway(fake_client, empty_store, breaker_threshold=2), empty_store)
    with pytest.raises(CircuitOpen):
        f.fetch_spec(spec_min)


def test_normalize_kline_formats_and_skips_incomplete_rows() -> None:
    rows = normalize_kline(
        [
            {
                "日期": "2023-08-25",
                "开盘": 23.5,
                "收盘": 23.67,
                "最高": 24.0,
                "最低": 23.1,
                "成交量": 2116638,
                "成交额": 4904903314.0,
            },
            {
                "日期": "2023-08-24",
                "开盘": 1,
                "收盘": 2,
                "最高": 3,
                "最低": 1,
                "成交量": 5,
                "成交额": None,
            },
            {"日期": "2023-08-23", "开盘": None, "收盘": 2, "最高": 3, "最低": 1},  # 缺价格：跳过
        ]
    )
    assert [r["d"] for r in rows] == ["2023-08-24", "2023-08-25"]  # 升序
    assert rows[1] == {
        "d": "2023-08-25",
        "o": "23.5",
        "h": "24.0",
        "l": "23.1",
        "c": "23.67",
        "v_lot": 2116638,
        "amt": "4904903314.0",
    }
    assert rows[0]["amt"] is None


def test_normalize_index_accepts_both_column_sets() -> None:
    em = {
        "date": "2023-08-25",
        "open": 3.0,
        "close": 4.0,
        "high": 5.0,
        "low": 2.0,
        "volume": 10,
        "amount": 1e3,
    }
    cn = {
        "日期": "2023-08-25",
        "开盘": 3.0,
        "收盘": 4.0,
        "最高": 5.0,
        "最低": 2.0,
        "成交量": 10,
        "成交额": 1e3,
    }
    assert normalize_index([em]) == normalize_index([cn])
    assert normalize_index([em])[0]["c"] == "4.0"


# ---------- CLI ----------
@pytest.fixture
def fast_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    for host in ("EASTMONEY", "CNINFO", "CCTV", "SINA"):
        monkeypatch.setenv(f"REPLAY_RATE_{host}_MS", "0")


def test_cli_fetch_then_build_roundtrip(
    fixture_dir: Path,
    fake_client: FakeClient,
    tmp_path: Path,
    fast_rates: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    spec = fixture_dir / "spec_min.json"
    assert (
        cli.run(
            ["--data-dir", str(data), "fetch", "--spec", str(spec)],
            client_factory=lambda: fake_client,
        )
        == 0
    )
    assert "失败 0" in capsys.readouterr().out
    # 抓取得到的原始数据足以构建（cls 目录由 E5 产生，这里没有，所以关掉 cls 来源）
    spec_data = json.loads(spec.read_text(encoding="utf-8"))
    spec_data["sources"]["cls"] = False
    spec2 = tmp_path / "spec.json"
    spec2.write_text(json.dumps(spec_data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "packs" / "p.json"
    assert (
        cli.run(
            [
                "--data-dir",
                str(data),
                "build",
                "--spec",
                str(spec2),
                "--out",
                str(out),
                "--version",
                "1",
            ]
        )
        == 0
    )
    assert out.exists()
    assert cli.run(["verify", "--pack", str(out)]) == 0


def test_cli_fetch_kline(fake_client: FakeClient, tmp_path: Path, fast_rates: None) -> None:
    code = cli.run(
        [
            "--data-dir",
            str(tmp_path),
            "fetch-kline",
            "--codes",
            "600001,300001",
            "--start",
            "20230608",
            "--end",
            "2023-06-30",
        ],
        client_factory=lambda: fake_client,
    )
    assert code == 0
    assert (tmp_path / "kline" / "hfq" / "300001.jsonl").exists()
    assert len(fake_client.calls_of("kline_daily")) == 4  # 2 只 x (none, hfq)


def test_cli_exit_codes(
    fixture_dir: Path, fake_client: FakeClient, tmp_path: Path, fast_rates: None
) -> None:
    spec = fixture_dir / "spec_min.json"
    # 单项失败 -> 1
    fake_client.errors["cninfo_disclosure"] = lambda kw: KeyError(kw["code"])
    assert (
        cli.run(
            ["--data-dir", str(tmp_path / "a"), "fetch", "--spec", str(spec)],
            client_factory=lambda: fake_client,
        )
        == 1
    )
    # 熔断 -> 2（不可重试的错误连续出现 10 次）
    fake_client.errors.clear()
    for method in ("kline_daily", "index_daily", "cninfo_disclosure"):
        fake_client.errors[method] = lambda kw: ValueError("bad")
    assert (
        cli.run(
            ["--data-dir", str(tmp_path / "b"), "fetch", "--spec", str(spec)],
            client_factory=lambda: fake_client,
        )
        == 2
    )
    # 规格错误 -> 1
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert (
        cli.run(
            ["--data-dir", str(tmp_path / "c"), "fetch", "--spec", str(bad)],
            client_factory=lambda: fake_client,
        )
        == 1
    )
