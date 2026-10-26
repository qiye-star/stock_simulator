"""关卡包手动导入：`python -m stocksim.services.replay.cli import <文件或目录>`（05 §3.3）。

目录按 `<dir>/<slug>/*.json` 扫描，与启动时的自动导入相同。失败时以非零退出码结束。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from stocksim.core.config import get_settings
from stocksim.db.session import make_engine, make_session_factory
from stocksim.services.replay import levels


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stocksim.services.replay.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="导入关卡包（文件或目录）")
    imp.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    factory = make_session_factory(engine)
    try:
        if args.path.is_dir():
            results = levels.import_directory(factory, args.path)
            failed = len(list(args.path.glob("*/*.json"))) - len(results)
            for r in results:
                print(f"{r.status}: {r.slug} v{r.version}")
            return 1 if failed else 0
        raw = json.loads(args.path.read_text(encoding="utf-8"))
        with factory() as db:
            try:
                result = levels.import_pack(db, raw)
                db.commit()
            except (ValueError, levels.PackConflict) as exc:
                db.rollback()
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"{result.status}: {result.slug} v{result.version}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
