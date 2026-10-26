"""AKShare 访问层：协议、真实客户端、限速、重试、熔断。

**只有本模块允许（延迟）导入 akshare**，且只在 ``AkshareClient.__init__`` 里导入，
因此没装 akshare 时其余模块（构建器、测试）照常可用。

可测性：每个用到的 AKShare 函数对应 ``AkClient`` 的一个方法，一律返回 ``list[dict]``
（日期时间已转 ISO 字符串、numpy 标量已转原生类型）。测试注入 FakeClient，
``RateLimiter`` 与 ``RetryPolicy`` 的时钟、sleep、随机数也可注入。
"""

from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .rawstore import utc_now_iso

Rows = list[dict[str, Any]]

# 方法 -> 主机（限速按主机分别计）
HOST_OF: dict[str, str] = {
    "trade_calendar": "sina",
    "kline_daily": "eastmoney",
    "index_daily": "eastmoney",
    "cninfo_disclosure": "cninfo",
    "gsrl_dynamics": "eastmoney",
    "cctv_news": "cctv",
    "cls_flash": "cls",
    "em_news": "eastmoney",
}

# 默认最小间隔（毫秒），可用环境变量 REPLAY_RATE_<HOST>_MS 覆盖（05 §2.4）
DEFAULT_INTERVALS_MS: dict[str, int] = {
    "eastmoney": 1500,
    "cninfo": 3000,
    "cctv": 30000,
    "sina": 1000,
    "cls": 0,
}


class AkClient(Protocol):
    """抓取层依赖的最小接口。日期参数统一为 ``YYYYMMDD`` 字符串。"""

    version: str

    def trade_calendar(self) -> Rows: ...

    def kline_daily(self, code: str, start: str, end: str, adjust: str) -> Rows:
        """``adjust`` 取 ``none`` 或 ``hfq``。"""
        ...

    def index_daily(self, symbol: str, start: str, end: str) -> Rows: ...

    def cninfo_disclosure(self, code: str, start: str, end: str) -> Rows: ...

    def gsrl_dynamics(self, date: str) -> Rows: ...

    def cctv_news(self, date: str) -> Rows: ...

    def cls_flash(self, symbol: str) -> Rows:
        """财联社电报，``symbol`` 取 ``全部`` 或 ``重点``；只返回最新 20 条。"""
        ...

    def em_news(self, symbol: str) -> Rows:
        """东财个股新闻（实际只返回最新 10 条）。"""
        ...


# ---------- 真实客户端 ----------


def _jsonable(value: Any) -> Any:
    """DataFrame 单元格 -> JSON 原生类型（不依赖 numpy/pandas 的导入）。"""
    if value is None or isinstance(value, bool | str):
        return value
    try:
        if value != value:  # NaN / NaT
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):  # date / datetime / time / Timestamp
        return value.isoformat()
    if hasattr(value, "item"):  # numpy 标量
        return _jsonable(value.item())
    return value


def records(df: Any) -> Rows:
    """``df.to_dict('records')`` 并转成 JSON 原生类型；None/空表返回 []。"""
    if df is None or len(df) == 0:
        return []
    return [{str(k): _jsonable(v) for k, v in row.items()} for row in df.to_dict("records")]


def _em_index_symbol(symbol: str) -> str:
    """指数代码 -> 东财前缀代码：399xxx 属深市，其余按沪市。"""
    return ("sz" if symbol.startswith("399") else "sh") + symbol


class AkshareClient:
    """真实 AKShare 客户端。构造时才导入 akshare。"""

    def __init__(self) -> None:
        import akshare  # 延迟导入：仅此一处

        self._ak = akshare
        self.version: str = str(getattr(akshare, "__version__", "unknown"))

    def trade_calendar(self) -> Rows:
        return records(self._ak.tool_trade_date_hist_sina())

    def kline_daily(self, code: str, start: str, end: str, adjust: str) -> Rows:
        if adjust not in ("none", "hfq"):
            raise ValueError(f"unsupported adjust: {adjust!r}")
        df = self._ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="" if adjust == "none" else "hfq",
            timeout=30,
        )
        return records(df)

    def index_daily(self, symbol: str, start: str, end: str) -> Rows:
        # 实测 index_zh_a_hist 在部分网络下会被断开连接，而 stock_zh_index_daily_em 稳定
        # （英文列 date/open/close/high/low/volume/amount），故先试后者，失败再退回前者。
        try:
            return records(
                self._ak.stock_zh_index_daily_em(
                    symbol=_em_index_symbol(symbol), start_date=start, end_date=end
                )
            )
        except Exception:  # 数据源改版或断连都退回备选接口
            return records(
                self._ak.index_zh_a_hist(
                    symbol=symbol, period="daily", start_date=start, end_date=end
                )
            )

    def cninfo_disclosure(self, code: str, start: str, end: str) -> Rows:
        df = self._ak.stock_zh_a_disclosure_report_cninfo(
            symbol=code, market="沪深京", start_date=start, end_date=end
        )
        return records(df)

    def gsrl_dynamics(self, date: str) -> Rows:
        try:
            return records(self._ak.stock_gsrl_gsdt_em(date=date))
        except TypeError:
            # 当日无数据时接口返回 result=None，函数内部 None["data"] 抛 TypeError：按空结果处理
            return []

    def cctv_news(self, date: str) -> Rows:
        # 20160203 不进任何分支返回 None；records(None) 已按空结果处理
        return records(self._ak.news_cctv(date=date))

    def cls_flash(self, symbol: str) -> Rows:
        return records(self._ak.stock_info_global_cls(symbol=symbol))

    def em_news(self, symbol: str) -> Rows:
        return records(self._ak.stock_news_em(symbol=symbol))


# ---------- 限速 ----------


def intervals_from_env(env: Mapping[str, str] | None = None) -> dict[str, int]:
    """默认间隔 + ``REPLAY_RATE_<HOST>_MS`` 覆盖。"""
    env = os.environ if env is None else env
    out = dict(DEFAULT_INTERVALS_MS)
    for host in list(out):
        raw = env.get(f"REPLAY_RATE_{host.upper()}_MS")
        if raw is not None and raw.strip().isdigit():
            out[host] = int(raw)
    return out


class RateLimiter:
    """按主机的最小间隔限速：同一主机两次调用的起点至少相隔 ``interval``。"""

    def __init__(
        self,
        intervals_ms: Mapping[str, int],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._intervals = dict(intervals_ms)
        self._clock = clock
        self._sleep = sleep
        self._next_at: dict[str, float] = {}

    def acquire(self, host: str) -> float:
        """阻塞到允许调用为止，返回实际等待的秒数。"""
        interval = self._intervals.get(host, 0) / 1000.0
        now = self._clock()
        ready = self._next_at.get(host, now)
        wait = max(0.0, ready - now)
        if wait > 0:
            self._sleep(wait)
        self._next_at[host] = max(now, ready) + interval
        return wait


# ---------- 重试与熔断 ----------

_NETWORK_PACKAGES = {"requests", "urllib3", "curl_cffi", "http", "socket", "ssl"}


def is_retryable(exc: BaseException) -> bool:
    """可重试：网络类异常、JSONDecodeError、``KeyError("result")``。

    requests / curl_cffi 的异常按所属包名判断，避免在此处导入它们。
    """
    if isinstance(exc, json.JSONDecodeError | OSError | TimeoutError):
        return True
    if isinstance(exc, KeyError) and exc.args == ("result",):
        return True
    return any(
        (cls.__module__ or "").split(".")[0] in _NETWORK_PACKAGES for cls in type(exc).__mro__
    )


class CircuitOpen(RuntimeError):
    """连续失败过多，熔断；CLI 以退出码 2 结束。"""


@dataclass
class RetryPolicy:
    """首次调用之外最多重试 ``len(backoffs)`` 次，退避 2s/4s/8s 加 0–1s 抖动。"""

    backoffs: tuple[float, ...] = (2.0, 4.0, 8.0)
    jitter: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)

    def delay(self, attempt: int) -> float:
        return self.backoffs[attempt] + self.rng.uniform(0.0, self.jitter)


class Gateway:
    """限速 + 重试 + 熔断 + 请求日志，包住一个 ``AkClient``。

    ``call("kline_daily", code=..., ...)`` 返回 ``list[dict]``。熔断按“重试用尽后仍失败的调用”
    连续计数（成功清零，默认 10 次）。每次调用（成功或失败）写一条日志。
    """

    def __init__(
        self,
        client: AkClient,
        *,
        limiter: RateLimiter,
        retry: RetryPolicy | None = None,
        log: Callable[[dict[str, Any]], None] | None = None,
        breaker_threshold: int = 10,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        self.client = client
        self._limiter = limiter
        self._retry = retry or RetryPolicy()
        self._log = log
        self._threshold = breaker_threshold
        self._clock = clock
        self._utc_now = utc_now or utc_now_iso
        self._consecutive_failures = 0

    @property
    def version(self) -> str:
        return self.client.version

    def call(self, method: str, /, **kwargs: Any) -> Rows:
        if method not in HOST_OF:
            raise ValueError(f"unknown client method: {method}")
        if self._consecutive_failures >= self._threshold:
            raise CircuitOpen(f"{self._consecutive_failures} consecutive failures")
        fn = getattr(self.client, method)
        host = HOST_OF[method]
        started = self._clock()
        attempt = 0
        while True:
            self._limiter.acquire(host)
            try:
                rows = fn(**kwargs)
            except Exception as exc:  # 分类后要么重试要么原样抛出
                if is_retryable(exc) and attempt < len(self._retry.backoffs):
                    self._retry.sleep(self._retry.delay(attempt))
                    attempt += 1
                    continue
                self._consecutive_failures += 1
                self._write_log(method, kwargs, False, 0, started, f"{type(exc).__name__}: {exc}")
                if self._consecutive_failures >= self._threshold:
                    raise CircuitOpen(
                        f"{self._consecutive_failures} consecutive failures; last: {exc!r}"
                    ) from exc
                raise
            self._consecutive_failures = 0
            self._write_log(method, kwargs, True, len(rows), started, None)
            return rows

    def _write_log(
        self,
        method: str,
        args: Mapping[str, Any],
        ok: bool,
        rows: int,
        started: float,
        error: str | None,
    ) -> None:
        if self._log is None:
            return
        self._log(
            {
                "ts_utc": self._utc_now(),
                "fn": method,
                "args": dict(args),
                "ok": ok,
                "rows": rows,
                "ms": int((self._clock() - started) * 1000),
                "error": error,
            }
        )
