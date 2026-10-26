"""每日挑战命令行（03 §11.2）：`stocksim-challenge <子命令>`。

- run-due：执行一次 run_due（生成、开始、推进、关闭钩子、结算、清理）。
- loop --interval N：循环执行 run_due，Ctrl-C 退出。部署为 compose 的 challenge-runner 服务。
- show --date YYYY-MM-DD：打印状态与承诺；结算（settled/void）后才打印 seed 与盐，结算前绝不打印。
- void --date YYYY-MM-DD --reason TEXT：作废挑战（reason ≤ 32 字符）。已结算的不可作废。

配置经 `core.config.get_settings()` 读取（环境变量或 backend/.env），与 Web 服务使用同一数据库。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from stocksim.core.config import get_settings
from stocksim.core.errors import AppError
from stocksim.db.session import make_engine, make_session_factory
from stocksim.services.challenges import config as challenge_config
from stocksim.services.challenges import generate, registry, runner, timeutil
from stocksim.services.challenges import views as challenge_views
from stocksim.services.challenges.timeutil import local_date

REASON_MAX = 32


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "loop" and args.interval <= 0:
        parser.error("--interval 必须为正数（秒）")
    if args.command == "void" and len(args.reason) > REASON_MAX:
        parser.error(f"--reason 不得超过 {REASON_MAX} 字符")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    challenge_config.use_settings(settings)
    engine = make_engine(settings.DATABASE_URL)
    factory = make_session_factory(engine)
    try:
        if args.command == "run-due":
            return _run_once(factory)
        if args.command == "loop":
            return _loop(factory, args.interval)
        if args.command == "show":
            return _show(factory, args.date)
        return _void(factory, args.date, args.reason)
    except AppError as exc:
        params = json.dumps(exc.params, ensure_ascii=False)
        print(f"error: {exc.code.value} {params}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stocksim-challenge", description="每日挑战维护命令")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-due", help="执行一次 run_due")
    loop = sub.add_parser("loop", help="循环执行 run_due（Ctrl-C 退出）")
    loop.add_argument("--interval", type=float, default=15.0, help="两次执行的间隔（秒），默认 15")
    show = sub.add_parser("show", help="查看挑战状态与承诺（结算后才显示 seed）")
    show.add_argument("--date", type=_parse_date, default=None, help="UTC+8 日期，默认今天")
    void = sub.add_parser("void", help="作废挑战")
    void.add_argument("--date", type=_parse_date, required=True, help="UTC+8 日期")
    void.add_argument("--reason", required=True, help=f"作废原因，≤ {REASON_MAX} 字符")
    return parser


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期应为 YYYY-MM-DD：{text!r}") from exc


def _run_once(factory: sessionmaker[Session]) -> int:
    report = runner.run_due(factory, timeutil.now())
    print(json.dumps(asdict(report), ensure_ascii=False))
    return 1 if report.errors else 0


def _loop(factory: sessionmaker[Session], interval: float) -> int:
    try:
        while True:
            report = runner.run_due(factory, timeutil.now())
            if report.errors:
                logging.getLogger(__name__).warning("run_due reported %d error(s)", report.errors)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def _show(factory: sessionmaker[Session], day: date | None) -> int:
    target = day or local_date(timeutil.now())
    with factory() as db:
        ch = registry.challenge_for_date(db, target)
        if ch is None:
            print(f"no challenge for {target.isoformat()}", file=sys.stderr)
            return 1
        info: dict[str, object] = {
            "challenge_date": target.isoformat(),
            "status": ch.status,
            "schedule_mode": ch.schedule_mode,
            "seed_commitment": ch.seed_commitment,
            "commitment_scheme": "sha256/stocksim-challenge|v1",
            "starts_at": ch.starts_at.isoformat(),
            "entry_closes_at": ch.entry_closes_at.isoformat(),
            "settle_expected_at": ch.settle_expected_at.isoformat(),
            "participants": challenge_views.participant_count(db, ch),
            "void_reason": ch.void_reason,
        }
        if ch.status in ("settled", "void"):  # 只有结算或作废后才公开 seed（03 §1.4）
            info["reveal"] = challenge_views.reveal_out(db, ch)
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
    return 0


def _void(factory: sessionmaker[Session], day: date, reason: str) -> int:
    with factory() as db:
        ch = registry.challenge_for_date(db, day)
        if ch is None:
            print(f"no challenge for {day.isoformat()}", file=sys.stderr)
            return 1
        generate.void_challenge(db, ch, reason)
        result = {"challenge_date": day.isoformat(), "status": ch.status}
        print(json.dumps({**result, "void_reason": ch.void_reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
