"""按关卡规格补齐原始数据（增量、可重入）。只用标准库；网络访问全部经 ``Gateway``。

增量规则（05 §2.4）：
- K 线：读 jsonl 最后一行日期，从下一天抓到 end；文件不覆盖所需起点时整段重抓并合并。
- 公告：按季度分片，季度已结束且文件存在就跳过；当前季度每次重抓并覆盖。
- 公司动态、新闻联播：按日，文件存在就跳过，``force`` 强制重抓。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import rawstore
from .adjust import to_fraction
from .client import CircuitOpen, Gateway
from .events import _quarters, natural_days
from .rawstore import RawStore
from .spec import Spec, Window, compute_window

GSRL_TRUNCATION_ROWS = 5000  # stock_gsrl_gsdt_em 的 pageSize，达到即可能被截断
CCTV_FIRST_DAY = "2016-02-04"  # 20160203 当天接口返回 None，之后才可靠


@dataclass
class FetchSummary:
    fetched: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def compact(iso_date: str) -> str:
    return iso_date.replace("-", "")


def _num(value: Any) -> str | None:
    """数值 -> 十进制字符串（浮点取最短 repr，避免二进制误差）；缺失返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    return format(Decimal(repr(value) if isinstance(value, float) else str(value)), "f")


def normalize_kline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AKShare 中文列 -> 落盘格式 ``{d,o,h,l,c,v_lot,amt}``（价格为字符串，成交量为手）。"""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        prices = [_num(r.get(k)) for k in ("开盘", "最高", "最低", "收盘")]
        if any(p is None for p in prices) or r.get("日期") is None:
            continue
        d = str(r["日期"])[:10]
        out[d] = {
            "d": d,
            "o": prices[0],
            "h": prices[1],
            "l": prices[2],
            "c": prices[3],
            "v_lot": int(to_fraction(r.get("成交量") or 0)),
            "amt": _num(r.get("成交额")),
        }
    return [out[d] for d in sorted(out)]


_INDEX_COLUMNS = {
    "d": ("日期", "date"),
    "o": ("开盘", "open"),
    "h": ("最高", "high"),
    "l": ("最低", "low"),
    "c": ("收盘", "close"),
    "v": ("成交量", "volume"),
    "amt": ("成交额", "amount"),
}


def normalize_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """指数日线 -> ``{d,o,h,l,c,v,amt}``。兼容两个接口的中文列与英文列。"""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        picked = {
            k: next((r[c] for c in cols if c in r), None) for k, cols in _INDEX_COLUMNS.items()
        }
        if picked["d"] is None or any(picked[k] is None for k in "ohlc"):
            continue
        d = str(picked["d"])[:10]
        out[d] = {
            "d": d,
            "o": _num(picked["o"]),
            "h": _num(picked["h"]),
            "l": _num(picked["l"]),
            "c": _num(picked["c"]),
            "v": None if picked["v"] is None else int(to_fraction(picked["v"])),
            "amt": _num(picked["amt"]),
        }
    return [out[d] for d in sorted(out)]


def quarter_range(year: int, quarter: int) -> tuple[str, str]:
    start = date(year, 3 * quarter - 2, 1)
    nxt = date(year + (quarter == 4), (3 * quarter) % 12 + 1, 1)
    return start.isoformat(), (nxt - timedelta(days=1)).isoformat()


class Fetcher:
    def __init__(
        self,
        store: RawStore,
        gateway: Gateway,
        *,
        today: Callable[[], str] = lambda: date.today().isoformat(),
        utc_now: Callable[[], str] = rawstore.utc_now_iso,
        force: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.gw = gateway
        self._today = today
        self._utc_now = utc_now
        self.force = force
        self._progress = progress or (lambda _msg: None)
        self.summary = FetchSummary()

    # ----- 小工具 -----

    def _wrap(self, fn: str, args: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        return rawstore.wrap_payload(
            fn, args, rows, fetched_at=self._utc_now(), version=self.gw.version
        )

    def _guard(self, label: str, action: Callable[[], None]) -> None:
        """单项失败只记录并继续；熔断（CircuitOpen）继续向上抛。"""
        try:
            action()
        except CircuitOpen:
            raise
        except Exception as exc:  # 单项失败不拖垮整批（例如退市股触发 KeyError）
            self.summary.failed.append(f"{label}: {type(exc).__name__}: {exc}")
            self._progress(f"FAIL {label}: {exc}")

    # ----- 日历 -----

    def calendar(self) -> list[str]:
        rows = self.gw.call("trade_calendar")
        dates = sorted({str(r["trade_date"])[:10] for r in rows if r.get("trade_date")})
        self.store.write_json(
            rawstore.calendar_path(),
            self._wrap("tool_trade_date_hist_sina", {}, dates),  # type: ignore[arg-type]
        )
        self.summary.fetched += 1
        self._progress(f"calendar: {len(dates)} days")
        return dates

    def load_calendar(self, *, need_until: str | None = None) -> list[str]:
        """读本地日历；缺失，或不覆盖 ``need_until`` 且 ``force`` 时才重抓。"""
        data = self.store.read_json(rawstore.calendar_path())
        rows = data.get("rows") if isinstance(data, dict) else None
        if (
            isinstance(rows, list)
            and rows
            and not (need_until and str(rows[-1]) < need_until and self._today() >= need_until)
        ):
            return [str(x) for x in rows]
        return self.calendar()

    # ----- K 线与指数 -----

    def kline(self, code: str, adjust: str, start: str, end: str) -> None:
        end = min(end, self._today())
        rel = rawstore.kline_path(adjust, code)
        existing = self.store.read_jsonl(rel)
        first = existing[0]["d"] if existing else None
        last = existing[-1]["d"] if existing else None
        if not self.force and existing and first <= start and last >= end:
            self.summary.skipped += 1
            return
        if not self.force and existing and first <= start:
            call_start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
            if call_start > end:
                self.summary.skipped += 1
                return
        else:
            call_start = start
        rows = self.gw.call(
            "kline_daily", code=code, start=compact(call_start), end=compact(end), adjust=adjust
        )
        fresh = normalize_kline(rows)
        if not fresh and not existing:
            self.summary.warnings.append(f"{code} {adjust}: {call_start}..{end} 没有返回数据")
            return
        if existing and call_start == start and not self.force and first > start:
            merged = {r["d"]: r for r in existing} | {r["d"]: r for r in fresh}
            self.store.write_jsonl(rel, [merged[d] for d in sorted(merged)])
        elif existing and call_start != start:
            self.store.append_jsonl(rel, [r for r in fresh if r["d"] > last])
        else:
            self.store.write_jsonl(rel, fresh)
        self.summary.fetched += 1
        self._progress(f"kline {adjust} {code}: +{len(fresh)} rows")

    def index(self, symbol: str, start: str, end: str) -> None:
        end = min(end, self._today())
        rel = rawstore.index_path(symbol)
        existing = self.store.read_jsonl(rel)
        if not self.force and existing and existing[0]["d"] <= start and existing[-1]["d"] >= end:
            self.summary.skipped += 1
            return
        rows = normalize_index(
            self.gw.call("index_daily", symbol=symbol, start=compact(start), end=compact(end))
        )
        if not rows:
            self.summary.warnings.append(f"index {symbol}: {start}..{end} 没有返回数据")
            return
        merged = {r["d"]: r for r in existing} | {r["d"]: r for r in rows}
        self.store.write_jsonl(rel, [merged[d] for d in sorted(merged)])
        self.summary.fetched += 1
        self._progress(f"index {symbol}: {len(rows)} rows")

    # ----- 公告 / 公司动态 / 新闻联播 -----

    def cninfo(self, code: str, year: int, quarter: int) -> None:
        q_start, q_end = quarter_range(year, quarter)
        today = self._today()
        if q_start > today:
            return
        rel = rawstore.cninfo_path(code, year, quarter)
        if not self.force and self.store.exists(rel) and q_end < today:
            self.summary.skipped += 1
            return
        end = min(q_end, today)
        args = {"code": code, "start": compact(q_start), "end": compact(end)}
        rows = self.gw.call("cninfo_disclosure", **args)
        self.store.write_json(rel, self._wrap("stock_zh_a_disclosure_report_cninfo", args, rows))
        self.summary.fetched += 1
        self._progress(f"cninfo {code} {year}Q{quarter}: {len(rows)} rows")

    def gsrl(self, iso_date: str) -> None:
        rel = rawstore.gsrl_path(iso_date)
        if iso_date > self._today() or (not self.force and self.store.exists(rel)):
            self.summary.skipped += 1
            return
        args = {"date": compact(iso_date)}
        rows = self.gw.call("gsrl_dynamics", **args)
        if len(rows) >= GSRL_TRUNCATION_ROWS:
            self.summary.warnings.append(f"gsrl {iso_date}: {len(rows)} 行，可能被截断")
        self.store.write_json(rel, self._wrap("stock_gsrl_gsdt_em", args, rows))
        self.summary.fetched += 1
        self._progress(f"gsrl {iso_date}: {len(rows)} rows")

    def cctv(self, iso_date: str) -> None:
        rel = rawstore.cctv_path(iso_date)
        if iso_date > self._today() or (not self.force and self.store.exists(rel)):
            self.summary.skipped += 1
            return
        args = {"date": compact(iso_date)}
        rows = self.gw.call("cctv_news", **args)
        if not rows and iso_date >= CCTV_FIRST_DAY:
            self.summary.warnings.append(
                f"cctv {iso_date}: 0 条（接口内部会静默跳过失败的条目，请核对）"
            )
        self.store.write_json(rel, self._wrap("news_cctv", args, rows))
        self.summary.fetched += 1
        self._progress(f"cctv {iso_date}: {len(rows)} rows")

    # ----- 编排 -----

    def fetch_kline_range(self, codes: list[str], start: str, end: str) -> FetchSummary:
        for code in codes:
            for adjust in ("none", "hfq"):
                self._guard(
                    f"kline {adjust} {code}", lambda c=code, a=adjust: self.kline(c, a, start, end)
                )
        return self.summary

    def fetch_spec(self, spec: Spec, window: Window | None = None) -> FetchSummary:
        if window is None:
            calendar = self.load_calendar()
            window = compute_window(calendar, spec)
        start, end = window.prev_start_date, window.dates[-1]
        self.fetch_kline_range(list(spec.codes), start, end)
        self._guard(
            f"index {spec.benchmark_symbol}",
            lambda: self.index(spec.benchmark_symbol, start, end),
        )
        event_start = window.event_start_date()
        if spec.sources.get("cninfo"):
            for code in spec.codes:
                for year, quarter in _quarters(event_start, end):
                    self._guard(
                        f"cninfo {code} {year}Q{quarter}",
                        lambda c=code, y=year, q=quarter: self.cninfo(c, y, q),
                    )
        if spec.sources.get("gsrl"):
            for d in window.calendar[window.i0 - min(10, window.lookback) : window.end]:
                self._guard(f"gsrl {d}", lambda d=d: self.gsrl(d))
        if spec.sources.get("cctv"):
            for d in natural_days(event_start, end):
                self._guard(f"cctv {d}", lambda d=d: self.cctv(d))
        return self.summary
