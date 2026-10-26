from __future__ import annotations

from pathlib import Path

import pytest

from stocksim.replay_ingest import rawstore
from stocksim.replay_ingest.rawstore import RawStore


def test_write_json_is_atomic_and_leaves_no_tmp(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.write_json("a/b.json", {"k": "中文", "n": 1})
    assert store.read_json("a/b.json") == {"k": "中文", "n": 1}
    assert [p.name for p in (tmp_path / "a").iterdir()] == ["b.json"]
    store.write_json("a/b.json", {"k": "v2"})  # 覆盖也走 os.replace
    assert store.read_json("a/b.json") == {"k": "v2"}
    assert [p.name for p in (tmp_path / "a").iterdir()] == ["b.json"]


def test_read_json_missing_or_corrupt_returns_none(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    assert store.read_json("nope.json") is None
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert store.read_json("bad.json") is None


def test_read_jsonl_skips_bad_lines(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    (tmp_path / "x.jsonl").write_text('{"a":1}\n\n{broken\n[1,2]\n{"a":2}\n', encoding="utf-8")
    assert store.read_jsonl("x.jsonl") == [{"a": 1}, {"a": 2}]
    assert store.read_jsonl("missing.jsonl") == []


def test_append_jsonl_repairs_missing_trailing_newline(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    assert store.append_jsonl("x.jsonl", [{"a": 1}]) == 1
    with (tmp_path / "x.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"a":2')  # 上次写到一半被打断，没有换行
    store.append_jsonl("x.jsonl", [{"a": 3}])
    assert store.read_jsonl("x.jsonl") == [{"a": 1}, {"a": 3}]  # 半行被跳过，新行完整
    assert (tmp_path / "x.jsonl").read_text(encoding="utf-8").endswith("\n")
    assert store.append_jsonl("x.jsonl", []) == 0


def test_write_jsonl_replaces_whole_file(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.append_jsonl("x.jsonl", [{"a": 1}, {"a": 2}])
    store.write_jsonl("x.jsonl", [{"a": 9}])
    assert store.read_jsonl("x.jsonl") == [{"a": 9}]


@pytest.mark.parametrize("rel", ["../escape.json", "/abs.json", "a/../../b.json"])
def test_unsafe_paths_rejected(tmp_path: Path, rel: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        RawStore(tmp_path).path(rel)


def test_path_conventions() -> None:
    assert rawstore.kline_path("hfq", "600030") == "kline/hfq/600030.jsonl"
    assert rawstore.cninfo_path("600030", 2023, 3) == "cninfo/600030/2023Q3.json"
    assert rawstore.gsrl_path("2023-08-25") == "gsrl/2023/2023-08-25.json"
    assert rawstore.cls_path("2023-08-25") == "cls/2023-08/2023-08-25.jsonl"
    with pytest.raises(ValueError, match="adjust"):
        rawstore.kline_path("qfq", "600030")  # 前复权不使用（05 §2.1）


def test_default_data_dir_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(rawstore.DATA_DIR_ENV, str(tmp_path))
    assert rawstore.default_data_dir() == tmp_path
    monkeypatch.delenv(rawstore.DATA_DIR_ENV)
    assert rawstore.default_data_dir().name == ".replay-data"


def test_sha256_and_fetch_log(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    (tmp_path / "f.txt").write_bytes(b"abc")
    assert (
        store.sha256("f.txt") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    store.log_fetch({"fn": "x", "ok": True})
    assert store.read_jsonl(rawstore.FETCH_LOG) == [{"fn": "x", "ok": True}]
