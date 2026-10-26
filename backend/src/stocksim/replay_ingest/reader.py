"""构建器读取原始数据的入口：记录用到了哪些文件（用于 provenance 的 sha256 与 built_at）。"""

from __future__ import annotations

from typing import Any

from .rawstore import RawStore


class RawReader:
    def __init__(self, store: RawStore) -> None:
        self.store = store
        self._used: set[str] = set()
        self._fetched_at: list[str] = []

    def json(self, rel: str) -> dict[str, Any] | None:
        data = self.store.read_json(rel)
        if not isinstance(data, dict):
            return None
        self._used.add(rel)
        fetched = data.get("fetched_at")
        if isinstance(fetched, str):
            self._fetched_at.append(fetched)
        return data

    def rows(self, rel: str) -> list[dict[str, Any]]:
        """整段 JSON 文件里的 ``rows``；文件不存在返回 []。"""
        data = self.json(rel)
        rows = data.get("rows") if data else None
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def jsonl(self, rel: str) -> list[dict[str, Any]]:
        if not self.store.exists(rel):
            return []
        self._used.add(rel)
        return self.store.read_jsonl(rel)

    def exists(self, rel: str) -> bool:
        return self.store.exists(rel)

    def used_files(self) -> dict[str, str]:
        """相对路径 -> sha256，按路径排序。"""
        return {rel: self.store.sha256(rel) for rel in sorted(self._used)}

    def latest_fetched_at(self) -> str | None:
        return max(self._fetched_at) if self._fetched_at else None
