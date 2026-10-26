"""replay_ingest 测试夹具：合成数据、FakeClient、无等待的 Gateway。全部不联网。"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from stocksim.replay_ingest.client import Gateway, RateLimiter, RetryPolicy
from stocksim.replay_ingest.rawstore import RawStore
from stocksim.replay_ingest.spec import Spec, load_spec

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "replay"
FIXED_NOW = "2024-01-01T00:00:00Z"
FIXED_TODAY = "2024-01-01"


def _iso(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


class FakeClient:
    """从 ``fixtures/replay/client/*.json`` 读取 AKShare 原生列名的响应；没有文件即空结果。"""

    version = "9.9.9-fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, Callable[[dict[str, Any]], Exception | None]] = {}

    def _load(self, name: str) -> list[dict[str, Any]]:
        path = FIXTURE_DIR / "client" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _enter(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))
        hook = self.errors.get(method)
        exc = hook(kwargs) if hook else None
        if exc is not None:
            raise exc

    def calls_of(self, method: str) -> list[dict[str, Any]]:
        return [kw for m, kw in self.calls if m == method]

    def trade_calendar(self) -> list[dict[str, Any]]:
        self._enter("trade_calendar")
        return self._load("calendar")

    def kline_daily(self, code: str, start: str, end: str, adjust: str) -> list[dict[str, Any]]:
        self._enter("kline_daily", code=code, start=start, end=end, adjust=adjust)
        rows = self._load(f"kline_{adjust}_{code}")
        return [r for r in rows if _iso(start) <= r["日期"] <= _iso(end)]

    def index_daily(self, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        self._enter("index_daily", symbol=symbol, start=start, end=end)
        return [r for r in self._load(f"index_{symbol}") if _iso(start) <= r["date"] <= _iso(end)]

    def cninfo_disclosure(self, code: str, start: str, end: str) -> list[dict[str, Any]]:
        self._enter("cninfo_disclosure", code=code, start=start, end=end)
        rows = self._load(f"cninfo_{code}")
        return [r for r in rows if _iso(start) <= r["公告时间"][:10] <= _iso(end)]

    def gsrl_dynamics(self, date: str) -> list[dict[str, Any]]:
        self._enter("gsrl_dynamics", date=date)
        return self._load(f"gsrl_{date}")

    def cctv_news(self, date: str) -> list[dict[str, Any]]:
        self._enter("cctv_news", date=date)
        return self._load(f"cctv_{date}")


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_gateway(sleeps: list[float]) -> Callable[..., Gateway]:
    """无限速、重试 sleep 只记录不等待的 Gateway。"""

    def _make(client: Any, store: RawStore | None = None, **kw: Any) -> Gateway:
        return Gateway(
            client,
            limiter=RateLimiter({}, sleep=sleeps.append),
            retry=RetryPolicy(sleep=sleeps.append),
            log=store.log_fetch if store else None,
            utc_now=lambda: FIXED_NOW,
            **kw,
        )

    return _make


@pytest.fixture
def raw_store(tmp_path: Path) -> RawStore:
    """夹具 ``raw/`` 的临时副本（构建器测试的输入）。"""
    dst = tmp_path / "raw"
    shutil.copytree(FIXTURE_DIR / "raw", dst)
    return RawStore(dst)


@pytest.fixture
def empty_store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "fetched")


@pytest.fixture
def spec_min() -> Spec:
    return load_spec(FIXTURE_DIR / "spec_min.json", industries={"券商", "银行"})


@pytest.fixture(scope="session")
def pack_min() -> dict[str, Any]:
    """从夹具 raw/ 构建一次的关卡包（只读，勿修改；需要改的测试请 deepcopy）。"""
    from stocksim.replay_ingest.build import build_pack

    spec = load_spec(FIXTURE_DIR / "spec_min.json", industries={"券商", "银行"})
    return build_pack(spec, RawStore(FIXTURE_DIR / "raw"), version=1).pack
