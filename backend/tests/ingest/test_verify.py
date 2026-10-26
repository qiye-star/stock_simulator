from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from stocksim.replay_ingest import cli
from stocksim.replay_ingest.verify import verify_pack

LB = 15


def test_fixture_pack_verifies_with_expected_warnings_and_stats(pack_min: dict[str, Any]) -> None:
    r = verify_pack(pack_min)
    assert r.ok, r.errors
    assert any("2019" in w for w in r.warnings)  # 脱敏残留要提示人工确认
    assert any("体积" in line for line in r.info)
    assert any("pre_open 重要巨潮公告" in line for line in r.info)  # Q10 抽查统计


def _mutate(pack: dict[str, Any], fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    p = copy.deepcopy(pack)
    fn(p)
    return p


CASES: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "format": (lambda p: p.update(format="other"), "format"),
    "calendar-length": (lambda p: p["calendar"].pop(), "calendar"),
    "anchor": (lambda p: p.update(anchor_date="2000-01-01"), "anchor_date"),
    "bars-length": (lambda p: p["bars"]["s1"].pop(), "bars 长度"),
    "ohlc": (lambda p: p["bars"]["s1"][3].__setitem__(1, 1), "OHLC"),
    "over-limit": (
        lambda p: p["bars"]["s3"][LB + 2].__setitem__(3, p["bars"]["s3"][LB + 2][3] * 2),
        "涨跌幅",
    ),
    "suspended-with-volume": (lambda p: p["bars"]["s1"][LB + 1].__setitem__(4, 5), "停牌"),
    "scale": (lambda p: p["stocks"][0].update(mask_scale_ppm=10), "缩放"),
    "bench": (lambda p: p["benchmark"]["closes_adj"].__setitem__(0, 0), "closes_adj"),
    "event-order": (lambda p: p["events"].reverse(), "排序"),
    "event-id": (lambda p: p["events"][0].update(id="x1"), "id"),
    "event-slot": (lambda p: p["events"][0].update(slot="noon"), "day_idx/slot"),
    "stock-keys": (lambda p: p["events"][0].update(stock_keys=["zz"]), "stock_keys"),
    "leak-name": (lambda p: p["events"][0].update(title_masked="测试甲出事了"), "真名"),
    "leak-code": (lambda p: p["events"][0].update(body_masked="代码 600001"), "真名"),
    "leak-prompt": (
        lambda p: p["questions"][0].update(prompt_masked="测试丙涨吗"),
        "prompt_masked",
    ),
    "answer-bucket": (lambda p: p["questions"][0]["answer"].update(bucket=0), "不一致"),
    "answer-rank": (lambda p: p["questions"][1]["answer"]["relevance"].update(s1=3), "不一致"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_tampered_packs_fail(pack_min: dict[str, Any], name: str) -> None:
    fn, needle = CASES[name]
    r = verify_pack(_mutate(pack_min, fn))
    assert not r.ok
    assert any(needle in e for e in r.errors), r.errors


def test_missing_field_is_an_error_not_a_crash(pack_min: dict[str, Any]) -> None:
    p = copy.deepcopy(pack_min)
    del p["bars"]
    assert not verify_pack(p).ok


def test_cli_verify_exit_codes_and_json(
    fixture_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["verify", "--pack", str(fixture_dir / "pack_min.json")]) == 0
    assert "校验通过" in capsys.readouterr().out
    assert cli.run(["verify", "--pack", str(fixture_dir / "pack_min.json"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] == []
    bad = json.loads((fixture_dir / "pack_min.json").read_text(encoding="utf-8"))
    bad["anchor_date"] = "2000-01-01"
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert cli.run(["verify", "--pack", str(p)]) == 1
