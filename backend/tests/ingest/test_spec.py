from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from stocksim.replay_ingest.spec import (
    SpecError,
    compute_window,
    load_spec,
    parse_spec,
)

INDUSTRIES = {"券商", "银行"}


@pytest.fixture
def raw_spec(fixture_dir: Path) -> dict[str, Any]:
    return json.loads((fixture_dir / "spec_min.json").read_text(encoding="utf-8"))


def test_fixture_spec_parses(spec_min) -> None:
    assert spec_min.slug == "fixture-min"
    assert spec_min.codes == ("600001", "300001", "000001")
    assert spec_min.total_days == 25
    assert spec_min.stocks[2].name == ""  # 缺省，构建时回退到原始数据


def _mut(fn: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def apply(d: dict[str, Any]) -> dict[str, Any]:
        d = copy.deepcopy(d)
        fn(d)
        return d

    return apply


BAD = {
    "slug": _mut(lambda d: d.update(slug="Bad Slug")),
    "no-title-masked": _mut(lambda d: d.pop("title_masked")),
    "difficulty": _mut(lambda d: d.update(difficulty=4)),
    "d0-format": _mut(lambda d: d.update(d0="2023/07/04")),
    "one-stock": _mut(lambda d: d.update(stocks=d["stocks"][:1])),
    "dup-code": _mut(lambda d: d["stocks"][1].update(code="600001")),
    "code-format": _mut(lambda d: d["stocks"][0].update(code="6000")),
    "industry": _mut(lambda d: d["stocks"][0].update(industry="不存在的行业")),
    "st": _mut(lambda d: d["stocks"][0].update(is_st=True)),
    "role": _mut(lambda d: d["stocks"][0].update(role="boss")),
    "source": _mut(lambda d: d["sources"].update(weibo=True)),
    "manual-code": _mut(lambda d: d["manual_events"][0].update(codes=["111111"])),
    "manual-time": _mut(lambda d: d["manual_events"][0].update(local_time="7月9日")),
    "manual-dup-id": _mut(lambda d: d["manual_events"][1].update(id="m1")),
    "q-opens-range": _mut(lambda d: d["questions"][0]["opens"].update(day=6)),
    "q-horizon": _mut(lambda d: d["questions"][0].update(horizon_days=11)),
    "q-closes-before-opens": _mut(
        lambda d: d["questions"][0].update(closes={"day": 0, "phase": "close"})
    ),
    "q-phase": _mut(lambda d: d["questions"][0]["opens"].update(phase="noon")),
    "q-base": _mut(lambda d: d["questions"][0].update(base="open")),
    "q-edges": _mut(lambda d: d["questions"][0].update(edges_bp=[100, -100])),
    "q-rank-topk": _mut(lambda d: d["questions"][1].update(top_k=3, codes=["600001", "300001"])),
    "q-dup-id": _mut(lambda d: d["questions"][1].update(id="q1")),
    "commentary": _mut(lambda d: d.update(commentary="x" * 2001)),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_invalid_specs_are_rejected(raw_spec: dict[str, Any], name: str) -> None:
    with pytest.raises(SpecError):
        parse_spec(BAD[name](raw_spec), industries=INDUSTRIES)


def test_not_json_object(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("[1]", encoding="utf-8")
    with pytest.raises(SpecError, match="对象"):
        load_spec(p)
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(SpecError, match="JSON"):
        load_spec(p)


def test_industry_check_is_optional(raw_spec: dict[str, Any]) -> None:
    raw_spec["stocks"][0]["industry"] = "不存在的行业"
    parse_spec(raw_spec)  # 不传 industries 时不校验


def test_unmasked_level_may_omit_masked_texts(raw_spec: dict[str, Any]) -> None:
    for k in ("title_masked", "teaser_masked"):
        raw_spec.pop(k)
    raw_spec["masked_allowed"] = False
    assert parse_spec(raw_spec).title_masked == ""


# ---------- 窗口 ----------
def test_window_geometry(spec_min) -> None:
    cal = [f"d{i:03d}" for i in range(100)]
    spec = type(spec_min)(**{**spec_min.__dict__, "d0": "d050"})
    w = compute_window(cal, spec)
    assert w.start == 35
    assert len(w.dates) == 25
    assert w.anchor_date == "d049"
    assert w.prev_start_date == "d034"
    assert w.day_idx("d050") == 0
    assert w.day_idx("d049") == -1
    assert w.day_idx("d035") == -15
    assert w.event_start_date() == "d040"  # 回看期最后 10 个交易日
    with pytest.raises(ValueError, match="不是交易日"):
        w.day_idx("zzz")


def test_window_errors(spec_min) -> None:
    cls = type(spec_min)
    cal = [f"d{i:03d}" for i in range(100)]

    def spec_at(d0: str, **kw: Any) -> Any:
        return cls(**{**spec_min.__dict__, "d0": d0, **kw})

    with pytest.raises(SpecError, match="不是交易日"):
        compute_window(cal, spec_at("d050x"))
    with pytest.raises(SpecError, match="回看期"):
        compute_window(cal, spec_at("d010"))
    with pytest.raises(SpecError, match="揭示期"):
        compute_window(cal, spec_at("d095"))
    with pytest.raises(SpecError, match="升序"):
        compute_window(["b", "a"], spec_at("a"))
