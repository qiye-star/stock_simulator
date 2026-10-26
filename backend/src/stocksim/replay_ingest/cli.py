"""命令行：``python -m stocksim.replay_ingest <子命令>``。

退出码：0 成功；1 业务失败（规格/构建/校验不通过，或有抓取项失败）；2 熔断（连续失败过多）；
argparse 用法错误也是 2。除 calendar/fetch/fetch-kline/collect/daily 外都不联网。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from . import rawstore
from .build import build_pack, canonical_dumps
from .client import AkClient, CircuitOpen, Gateway, RateLimiter, RetryPolicy, intervals_from_env
from .collect import CLS_INTERVAL_S, CN_TZ, UNIVERSE_ENV, Collector, load_universe
from .errors import BuildError, CollectError, SpecError
from .fetch import Fetcher
from .rawstore import RawStore
from .spec import load_spec
from .verify import verify_pack

INDUSTRIES_ENV = "REPLAY_INDUSTRIES_FILE"
EXIT_FAIL = 1
EXIT_CIRCUIT = 2
WARN_PRINT_LIMIT = 10

ClientFactory = Callable[[], AkClient]


def _default_client() -> AkClient:
    from .client import AkshareClient  # 构造时才导入 akshare

    return AkshareClient()


def load_industries() -> set[str] | None:
    """82 个行业标签（``stocksim/data/industries.json``）；找不到文件则不校验。"""
    path = Path(
        os.environ.get(INDUSTRIES_ENV)
        or Path(__file__).resolve().parents[1] / "data" / "industries.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(item["name"]) for item in data}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _iso(text: str) -> str:
    t = text.strip().replace("-", "")
    if len(t) != 8 or not t.isdigit():
        raise argparse.ArgumentTypeError(f"日期需为 YYYYMMDD 或 YYYY-MM-DD: {text!r}")
    return f"{t[:4]}-{t[4:6]}-{t[6:]}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m stocksim.replay_ingest",
        description="真实复盘离线数据管道：抓取原始数据、构建并校验关卡包。",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        help="原始数据根目录（默认环境变量 REPLAY_DATA_DIR，否则 backend/.replay-data）",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<子命令>")

    sub.add_parser("calendar", help="抓取交易日历（联网）")

    s = sub.add_parser("fetch", help="按关卡规格增量补齐全部原始数据（联网）")
    s.add_argument("--spec", type=Path, required=True)
    s.add_argument("--force", action="store_true", help="忽略已有文件，强制重抓")

    s = sub.add_parser("fetch-kline", help="单独抓日 K（不复权与后复权）（联网）")
    s.add_argument("--codes", required=True, help="逗号分隔的 6 位代码")
    s.add_argument("--start", type=_iso, required=True, help="YYYYMMDD")
    s.add_argument("--end", type=_iso, required=True, help="YYYYMMDD")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("build", help="构建关卡包（只用标准库，不联网，输出逐字节确定）")
    s.add_argument("--spec", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True, help="如 replay/packs/<slug>/v1.json")
    s.add_argument("--version", type=int, required=True, help="内容任何变化都要 +1")
    s.add_argument(
        "--built-at", help="写入 provenance.built_at 的 UTC 时间；默认取所读原始文件最大 fetched_at"
    )
    s.add_argument(
        "--overwrite", action="store_true", help="允许覆盖内容不同的已有包（同版本不可变，慎用）"
    )

    s = sub.add_parser("verify", help="校验关卡包并输出脱敏与归属抽查报告（不联网）")
    s.add_argument("--pack", type=Path, required=True)
    s.add_argument("--json", action="store_true", help="以 JSON 输出报告")

    s = sub.add_parser("collect", help="定时抓存财联社电报与东财个股新闻（联网）")
    mode = s.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="一轮电报（全部+重点）+ 轮转一只个股新闻")
    mode.add_argument(
        "--loop",
        action="store_true",
        help="常驻：电报每 --interval 秒，个股新闻每 10 秒一只，20:30 补抓",
    )
    s.add_argument(
        "--interval", type=_interval, default=CLS_INTERVAL_S, help="电报间隔秒数（最小 30）"
    )
    s.add_argument(
        "--universe", help=f"pool（股票池）或逗号分隔的 6 位代码；默认取 {UNIVERSE_ENV}，否则 pool"
    )

    s = sub.add_parser("daily", help="当日盘后补抓：新闻联播、公司动态、股票池当季公告（联网）")
    s.add_argument("--universe", help=f"同 collect；默认取 {UNIVERSE_ENV}，否则 pool")
    return p


def _interval(text: str) -> int:
    if not text.isdigit() or int(text) < 30:
        raise argparse.ArgumentTypeError(f"--interval 需为不小于 30 的整数秒: {text!r}")
    return int(text)


def _stop_flag() -> threading.Event:
    """SIGTERM（docker stop）时在本轮结束后退出常驻循环；非主线程无法注册，则不置位。"""
    flag = threading.Event()
    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, lambda *_: flag.set())
    return flag


def _gateway(store: RawStore, factory: ClientFactory) -> Gateway:
    return Gateway(
        factory(),
        limiter=RateLimiter(intervals_from_env()),
        retry=RetryPolicy(),
        log=store.log_fetch,
    )


def _say(msg: str) -> None:
    print(msg, flush=True)


def _report_fetch(fetcher: Fetcher) -> int:
    summary = fetcher.summary
    _say(f"完成：抓取 {summary.fetched}，跳过 {summary.skipped}，失败 {len(summary.failed)}")
    for w in summary.warnings[:WARN_PRINT_LIMIT]:
        _say(f"WARN {w}")
    if len(summary.warnings) > WARN_PRINT_LIMIT:
        _say(f"WARN ……另有 {len(summary.warnings) - WARN_PRINT_LIMIT} 条警告")
    for f in summary.failed:
        _say(f"FAIL {f}")
    return 0 if summary.ok else EXIT_FAIL


def run(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    store = RawStore(args.data_dir or rawstore.default_data_dir())
    factory = client_factory or _default_client
    try:
        return _dispatch(args, store, factory)
    except CircuitOpen as exc:
        print(f"熔断：{exc}", file=sys.stderr)
        return EXIT_CIRCUIT
    except (SpecError, BuildError, CollectError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_FAIL


def _dispatch(args: argparse.Namespace, store: RawStore, factory: ClientFactory) -> int:
    if args.cmd == "calendar":
        fetcher = Fetcher(store, _gateway(store, factory), progress=_say)
        fetcher.calendar()
        return _report_fetch(fetcher)

    if args.cmd == "fetch":
        spec = load_spec(args.spec, industries=load_industries())
        fetcher = Fetcher(store, _gateway(store, factory), force=args.force, progress=_say)
        fetcher.fetch_spec(spec)
        return _report_fetch(fetcher)

    if args.cmd == "fetch-kline":
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        fetcher = Fetcher(store, _gateway(store, factory), force=args.force, progress=_say)
        fetcher.fetch_kline_range(codes, args.start, args.end)
        return _report_fetch(fetcher)

    if args.cmd == "build":
        spec = load_spec(args.spec, industries=load_industries())
        result = build_pack(spec, store, version=args.version, built_at=args.built_at)
        report = verify_pack(result.pack)
        for w in (*result.warnings, *report.warnings):
            _say(f"WARN {w}")
        if not report.ok:
            for e in report.errors:
                print(f"ERROR {e}", file=sys.stderr)
            return EXIT_FAIL
        text = canonical_dumps(result.pack)
        out: Path = args.out
        if out.exists() and out.read_text(encoding="utf-8") != text and not args.overwrite:
            print(
                f"错误：{out} 已存在且内容不同；内容变化须提升 --version（或明确 --overwrite）",
                file=sys.stderr,
            )
            return EXIT_FAIL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        _say(f"已写入 {out}（{len(text.encode('utf-8'))} 字节）")
        return 0

    if args.cmd in ("collect", "daily"):
        universe = load_universe(args.universe or os.environ.get(UNIVERSE_ENV))
        collector = Collector(store, _gateway(store, factory), universe, progress=_say)
        if args.cmd == "daily":
            collector.run_daily(datetime.now(CN_TZ).date())
        elif args.once:
            collector.tick_once()
        else:
            with contextlib.suppress(KeyboardInterrupt):
                collector.run_loop(interval_s=args.interval, stop=_stop_flag().is_set)
            return 0
        return 0 if collector.failed_count == 0 else EXIT_FAIL

    if args.cmd == "verify":
        pack: Any = json.loads(args.pack.read_text(encoding="utf-8"))
        report = verify_pack(pack)
        if args.json:
            _say(
                json.dumps(
                    {"errors": report.errors, "warnings": report.warnings, "info": report.info},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for line in report.info:
                _say(f"INFO {line}")
            for w in report.warnings:
                _say(f"WARN {w}")
            for e in report.errors:
                _say(f"ERROR {e}")
            _say("校验通过" if report.ok else f"校验失败：{len(report.errors)} 个错误")
        return 0 if report.ok else EXIT_FAIL

    raise AssertionError(args.cmd)  # argparse 已保证 cmd 合法
