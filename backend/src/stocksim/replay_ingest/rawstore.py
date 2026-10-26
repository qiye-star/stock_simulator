"""原始数据落盘：文件而非数据库，原子写，JSONL 追加写，读时跳过坏行。

根目录取环境变量 ``REPLAY_DATA_DIR``，默认 ``backend/.replay-data/``。布局见 README。
只用标准库。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_DIR_ENV = "REPLAY_DATA_DIR"
FETCH_LOG = "_state/fetch_log.jsonl"
COLLECT_CURSOR = "_state/collect_cursor.json"
COLLECT_LOG = "_state/collect_log.jsonl"


def default_data_dir() -> Path:
    """环境变量优先；否则 backend/.replay-data（相对本文件向上三级的 backend 目录）。"""
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / ".replay-data"


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 相对路径约定（单一来源，抓取与构建共用） ----------


def calendar_path() -> str:
    return "calendar/trade_dates.json"


def kline_path(adjust: str, code: str) -> str:
    """adjust: ``none`` 或 ``hfq``（不使用 qfq，见 05 §2.1）。"""
    if adjust not in ("none", "hfq"):
        raise ValueError(f"unsupported adjust: {adjust!r}")
    return f"kline/{adjust}/{code}.jsonl"


def index_path(symbol: str) -> str:
    return f"index/{symbol}.jsonl"


def cninfo_path(code: str, year: int, quarter: int) -> str:
    return f"cninfo/{code}/{year}Q{quarter}.json"


def gsrl_path(iso_date: str) -> str:
    return f"gsrl/{iso_date[:4]}/{iso_date}.json"


def cctv_path(iso_date: str) -> str:
    return f"cctv/{iso_date[:4]}/{iso_date}.json"


def cls_path(iso_date: str) -> str:
    return f"cls/{iso_date[:7]}/{iso_date}.jsonl"


def em_news_path(code: str, year_month: str) -> str:
    """个股新闻按代码与发布月分文件：``em_news/<code>/<yyyy-mm>.jsonl``（05 §2.3）。"""
    return f"em_news/{code}/{year_month}.jsonl"


def cls_key(pub_date: str, pub_time: str, title: str, content: str) -> str:
    """财联社电报去重键 ``sha1(发布日期 + 发布时间 + 标题 + 内容前 50 字)``（05 §2.5）。

    抓存与构建器（events.py）共用这一个公式；title/content 应已去首尾空白。
    """
    return hashlib.sha1(f"{pub_date}{pub_time}{title}{content[:50]}".encode()).hexdigest()


def wrap_payload(
    fn: str, args: Mapping[str, Any], rows: list[dict[str, Any]], *, fetched_at: str, version: str
) -> dict[str, Any]:
    """整段文件的统一格式（05 §2.3）。"""
    return {
        "fn": fn,
        "args": dict(args),
        "fetched_at": fetched_at,
        "akshare_version": version,
        "rows": rows,
    }


class RawStore:
    """``REPLAY_DATA_DIR`` 下的文件读写。所有相对路径禁止 ``..`` 与绝对路径。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"unsafe relative path: {rel!r}")
        return self.root / p

    def exists(self, rel: str) -> bool:
        return self.path(rel).is_file()

    # ----- 整段 JSON -----

    def write_json(self, rel: str, payload: Any) -> None:
        """原子写：先写 ``*.tmp`` 再 ``os.replace``。"""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def read_json(self, rel: str) -> Any | None:
        """不存在或内容损坏时返回 None。"""
        target = self.path(rel)
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ----- JSONL -----

    def read_jsonl(self, rel: str) -> list[dict[str, Any]]:
        """逐行读取，跳过空行与坏行（例如写入中途被打断的半行）。"""
        target = self.path(rel)
        rows: list[dict[str, Any]] = []
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return rows
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows

    def append_jsonl(self, rel: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """追加写，每行以 ``\\n`` 结尾。若文件末尾缺换行（上次中断），先补一个。"""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for r in rows
        ]
        if not lines:
            return 0
        needs_nl = False
        if target.is_file() and target.stat().st_size > 0:
            with target.open("rb") as fh:
                fh.seek(-1, os.SEEK_END)
                needs_nl = fh.read(1) != b"\n"
        with target.open("a", encoding="utf-8") as fh:
            if needs_nl:
                fh.write("\n")
            fh.writelines(lines)
        return len(lines)

    def write_jsonl(self, rel: str, rows: Iterable[Mapping[str, Any]]) -> None:
        """整文件原子重写（合并、去重后使用）。"""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                fh.write("\n")
        os.replace(tmp, target)

    # ----- 日志与校验 -----

    def log_fetch(self, entry: Mapping[str, Any]) -> None:
        self.append_jsonl(FETCH_LOG, [entry])

    def sha256(self, rel: str) -> str:
        h = hashlib.sha256()
        with self.path(rel).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
