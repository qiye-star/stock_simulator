from __future__ import annotations

import json
import random
import sys
import types
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest

from stocksim.replay_ingest.client import (
    AkshareClient,
    CircuitOpen,
    Gateway,
    RateLimiter,
    RetryPolicy,
    intervals_from_env,
    is_retryable,
    records,
)
from stocksim.replay_ingest.rawstore import RawStore


# ---------- RateLimiter ----------
class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_spaces_calls_per_host() -> None:
    clock = Clock()
    rl = RateLimiter(
        {"eastmoney": 1500, "cninfo": 3000}, clock=lambda: clock.now, sleep=clock.sleep
    )
    assert rl.acquire("eastmoney") == 0  # 首次不等
    assert rl.acquire("eastmoney") == pytest.approx(1.5)
    assert rl.acquire("cninfo") == 0  # 主机之间互不影响
    clock.now += 10  # 间隔已过，不再等待
    assert rl.acquire("eastmoney") == 0
    assert clock.sleeps == [pytest.approx(1.5)]
    assert rl.acquire("unknown-host") == 0  # 未配置的主机不限速
    assert rl.acquire("unknown-host") == 0


def test_intervals_from_env_overrides() -> None:
    base = intervals_from_env({})
    assert base["eastmoney"] == 1500
    assert base["cninfo"] == 3000
    assert base["cctv"] == 30000
    env = {"REPLAY_RATE_EASTMONEY_MS": "50", "REPLAY_RATE_CCTV_MS": "oops"}
    out = intervals_from_env(env)
    assert out["eastmoney"] == 50
    assert out["cctv"] == 30000  # 非法值忽略


# ---------- 重试分类 ----------
class RequestsLikeError(Exception):
    __module__ = "requests.exceptions"


def test_is_retryable_classification() -> None:
    assert is_retryable(ConnectionError("boom"))
    assert is_retryable(TimeoutError())
    assert is_retryable(json.JSONDecodeError("x", "doc", 0))
    assert is_retryable(KeyError("result"))
    assert is_retryable(RequestsLikeError("net"))  # 按包名识别，不导入 requests
    assert not is_retryable(KeyError("600030"))  # 退市股：不重试
    assert not is_retryable(ValueError("bad"))
    assert not is_retryable(TypeError("bad"))


class Flaky:
    version = "t"

    def __init__(self, fails: int, exc: Callable[[], Exception]) -> None:
        self.fails, self.exc, self.n = fails, exc, 0

    def gsrl_dynamics(self, date: str) -> list[dict[str, Any]]:
        self.n += 1
        if self.n <= self.fails:
            raise self.exc()
        return [{"代码": "x"}]


def test_retry_backoff_2_4_8_with_jitter(
    make_gateway: Callable[..., Gateway], sleeps: list[float]
) -> None:
    client = Flaky(3, lambda: ConnectionError("net"))
    gw = make_gateway(client)
    assert gw.call("gsrl_dynamics", date="20230101") == [{"代码": "x"}]
    assert client.n == 4  # 首次 + 3 次重试
    assert [int(s) for s in sleeps] == [2, 4, 8]
    assert all(b <= s <= b + 1 for s, b in zip(sleeps, (2, 4, 8), strict=True))


def test_retry_exhausted_raises_original(
    make_gateway: Callable[..., Gateway], sleeps: list[float]
) -> None:
    client = Flaky(99, lambda: ConnectionError("net"))
    with pytest.raises(ConnectionError):
        make_gateway(client).call("gsrl_dynamics", date="20230101")
    assert client.n == 4
    assert len(sleeps) == 3


def test_non_retryable_fails_immediately(
    make_gateway: Callable[..., Gateway], sleeps: list[float]
) -> None:
    client = Flaky(99, lambda: KeyError("600030"))
    with pytest.raises(KeyError):
        make_gateway(client).call("gsrl_dynamics", date="20230101")
    assert client.n == 1
    assert sleeps == []


def test_retry_jitter_is_injectable() -> None:
    p = RetryPolicy(rng=random.Random(1))
    assert 2 <= p.delay(0) <= 3
    assert 8 <= p.delay(2) <= 9


def test_circuit_breaker_after_consecutive_failed_calls(
    make_gateway: Callable[..., Gateway],
) -> None:
    client = Flaky(10**6, lambda: ValueError("bad"))
    gw = make_gateway(client, breaker_threshold=3)
    for _ in range(2):
        with pytest.raises(ValueError, match="bad"):
            gw.call("gsrl_dynamics", date="20230101")
    with pytest.raises(CircuitOpen):  # 第 3 次失败触发熔断
        gw.call("gsrl_dynamics", date="20230101")
    n = client.n
    with pytest.raises(CircuitOpen):  # 熔断后不再访问
        gw.call("gsrl_dynamics", date="20230101")
    assert client.n == n


def test_success_resets_breaker(make_gateway: Callable[..., Gateway]) -> None:
    client = Flaky(2, lambda: ValueError("bad"))
    gw = make_gateway(client, breaker_threshold=3)
    for _ in range(2):
        with pytest.raises(ValueError, match="bad"):
            gw.call("gsrl_dynamics", date="20230101")
    assert gw.call("gsrl_dynamics", date="20230101")
    client.fails = 10**6
    for _ in range(2):  # 计数已清零：再失败 2 次仍不熔断
        with pytest.raises(ValueError, match="bad"):
            gw.call("gsrl_dynamics", date="20230101")


def test_gateway_logs_every_call(
    make_gateway: Callable[..., Gateway], empty_store: RawStore
) -> None:
    client = Flaky(1, lambda: ValueError("bad"))
    gw = make_gateway(client, empty_store)
    with pytest.raises(ValueError, match="bad"):
        gw.call("gsrl_dynamics", date="20230101")
    gw.call("gsrl_dynamics", date="20230102")
    first, second = empty_store.read_jsonl("_state/fetch_log.jsonl")
    assert first["ok"] is False
    assert first["error"].startswith("ValueError")
    assert first["fn"] == "gsrl_dynamics"
    assert first["args"] == {"date": "20230101"}
    assert second["ok"] is True
    assert second["rows"] == 1
    assert set(second) == {"ts_utc", "fn", "args", "ok", "rows", "ms", "error"}


def test_gateway_rejects_unknown_method(make_gateway: Callable[..., Gateway]) -> None:
    with pytest.raises(ValueError, match="unknown"):
        make_gateway(Flaky(0, Exception)).call("nope")


def test_gateway_rate_limits_by_host(sleeps: list[float]) -> None:
    class C:
        version = "t"

        def kline_daily(self, **kw: Any) -> list[dict[str, Any]]:
            return []

    clock = Clock()
    gw = Gateway(
        C(),  # type: ignore[arg-type]
        limiter=RateLimiter({"eastmoney": 1500}, clock=lambda: clock.now, sleep=clock.sleep),
        retry=RetryPolicy(sleep=sleeps.append),
    )
    gw.call("kline_daily", code="1", start="a", end="b", adjust="none")
    gw.call("kline_daily", code="1", start="a", end="b", adjust="hfq")
    assert clock.sleeps == [pytest.approx(1.5)]


# ---------- records 与 AkshareClient（用假 akshare 模块，不联网）----------
class FakeDF:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def to_dict(self, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return self._rows


class NumpyLike:
    def __init__(self, v: Any) -> None:
        self.v = v

    def item(self) -> Any:
        return self.v


def test_records_converts_to_json_native() -> None:
    nan = float("nan")
    rows = records(
        FakeDF(
            [
                {
                    "日期": date(2023, 8, 25),
                    "时间": datetime(2023, 8, 25, 9, 30),
                    "量": NumpyLike(7),
                    "缺失": nan,
                    "名": "x",
                    "空": None,
                }
            ]
        )
    )
    assert rows == [
        {
            "日期": "2023-08-25",
            "时间": "2023-08-25T09:30:00",
            "量": 7,
            "缺失": None,
            "名": "x",
            "空": None,
        }
    ]
    json.dumps(rows)  # 必须可序列化
    assert records(None) == []
    assert records(FakeDF([])) == []


def _fake_akshare(
    monkeypatch: pytest.MonkeyPatch, **funcs: Callable[..., Any]
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    mod = types.ModuleType("akshare")
    mod.__version__ = "1.2.3"  # type: ignore[attr-defined]
    for name, fn in funcs.items():

        def wrapped(*a: Any, _n: str = name, _f: Callable[..., Any] = fn, **kw: Any) -> Any:
            calls.append((_n, kw))
            return _f(*a, **kw)

        setattr(mod, name, wrapped)
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return calls


def test_akshare_client_maps_parameters_and_adjust(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_akshare(
        monkeypatch,
        stock_zh_a_hist=lambda **kw: FakeDF([{"日期": date(2023, 8, 25), "收盘": 1.5}]),
        stock_zh_a_disclosure_report_cninfo=lambda **kw: FakeDF([]),
    )
    c = AkshareClient()
    assert c.version == "1.2.3"
    assert c.kline_daily("600030", "20230801", "20230831", "none") == [
        {"日期": "2023-08-25", "收盘": 1.5}
    ]
    c.kline_daily("600030", "20230801", "20230831", "hfq")
    assert [kw["adjust"] for _, kw in calls] == ["", "hfq"]  # 不使用 qfq
    assert calls[0][1]["period"] == "daily"
    assert calls[0][1]["symbol"] == "600030"
    with pytest.raises(ValueError, match="adjust"):
        c.kline_daily("600030", "20230801", "20230831", "qfq")
    c.cninfo_disclosure("600030", "20230701", "20230930")
    assert calls[-1][1]["market"] == "沪深京"


def test_akshare_client_gsrl_none_result_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kw: Any) -> Any:
        raise TypeError("'NoneType' object is not subscriptable")  # result=None 时的真实报错

    _fake_akshare(monkeypatch, stock_gsrl_gsdt_em=boom, news_cctv=lambda **kw: None)
    c = AkshareClient()
    assert c.gsrl_dynamics("20230101") == []
    assert c.cctv_news("20160203") == []  # news_cctv 在 20160203 返回 None


def test_akshare_client_index_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def em_fail(**kw: Any) -> Any:
        raise ConnectionError("down")

    calls = _fake_akshare(
        monkeypatch,
        stock_zh_index_daily_em=em_fail,
        index_zh_a_hist=lambda **kw: FakeDF([{"日期": date(2023, 8, 25), "收盘": 3700.5}]),
    )
    rows = AkshareClient().index_daily("000300", "20230801", "20230831")
    assert rows == [{"日期": "2023-08-25", "收盘": 3700.5}]
    assert [n for n, _ in calls] == ["stock_zh_index_daily_em", "index_zh_a_hist"]
    assert calls[0][1]["symbol"] == "sh000300"


def test_akshare_client_index_symbol_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_akshare(monkeypatch, stock_zh_index_daily_em=lambda **kw: FakeDF([]))
    AkshareClient().index_daily("399006", "20230801", "20230831")
    assert calls[0][1]["symbol"] == "sz399006"


def test_construct_without_akshare_raises_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """模块导入不需要 akshare（见 test_purity）；只有构造 AkshareClient 才导入。"""
    monkeypatch.setitem(sys.modules, "akshare", None)  # 让 import akshare 抛 ImportError
    with pytest.raises(ImportError):
        AkshareClient()
