"""事件数据：产业链、个股暴露度、新闻模板（由 scripts/ 下的转换脚本生成）。"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from stocksim.domain.events import constants as c
from stocksim.domain.events import render_title
from stocksim.domain.events.news import placeholders

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "backend" / "src" / "stocksim" / "data"
SRC_MD = ROOT / "docs" / "10.26-plan" / "01a-产业链草稿.md"


def _load_script(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


convert = _load_script(ROOT / "scripts" / "convert_supply_chain.py")
exposure_script = _load_script(ROOT / "scripts" / "build_stock_exposure.py")
templates_script = _load_script(ROOT / "scripts" / "news" / "build_templates.py")


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


_HEADER = "| " + " | ".join(convert.HEADER) + " |\n" + "| " + " | ".join(["---"] * 7) + " |\n"
INDUSTRIES = [i["name"] for i in _load("industries.json")]
POOL = _load("stock_pool.json")


# ------------------------------------------------------------ supply_chain.json
def test_supply_chain_nodes_match_industries_in_order():
    data = _load("supply_chain.json")
    assert data["version"] == c.EVENT_RULESET_VERSION
    assert [n["id"] for n in data["nodes"]] == INDUSTRIES and len(INDUSTRIES) == 82
    assert all(0 <= n["layer"] <= 5 for n in data["nodes"])


def test_supply_chain_edges_satisfy_contract():
    data = _load("supply_chain.json")
    index = {n: i for i, n in enumerate(INDUSTRIES)}
    keys = [(index[e["from"]], index[e["to"]]) for e in data["edges"]]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert len({frozenset(k) for k in keys}) == len(keys)  # 每对行业只出现一次
    for e in data["edges"]:
        assert e["from"] != e["to"] and e["id"] == f"{e['from']}>{e['to']}"
        assert e["relation"] in c.RELATIONS and e["sign"] in (1, -1)
        assert e["strength"] in (1, 2, 3) and 0 <= e["lag_days"] <= 5
        if e["relation"] == "substitute":
            assert e["sign"] == -1
        if e["relation"] == "same_theme":
            assert e["sign"] == 1
        assert "|" not in e["note"]
    used = {e["from"] for e in data["edges"]} | {e["to"] for e in data["edges"]}
    assert used == set(INDUSTRIES)


def test_supply_chain_json_is_up_to_date_with_draft():
    data, _ = convert.convert_text(SRC_MD.read_text(encoding="utf-8"), INDUSTRIES)
    assert convert.dumps(data) == (DATA / "supply_chain.json").read_text(encoding="utf-8")


def test_supply_chain_markdown_roundtrip_is_lossless():
    data, _ = convert.convert_text(SRC_MD.read_text(encoding="utf-8"), INDUSTRIES)
    md = convert.render_md(data)
    again, _ = convert.convert_text(md, INDUSTRIES)
    assert again == data
    assert convert.render_md(again) == md


def test_converter_reports_invalid_rows():
    header = _HEADER
    bad = {
        "未知行业": "| 火星 | 银行 | supply | - | 2 | 1 | x |",
        "自环": "| 银行 | 银行 | supply | - | 2 | 1 | x |",
        "替代必须为负": "| 银行 | 保险 | substitute | + | 2 | 1 | x |",
        "同题材必须为正": "| 银行 | 保险 | same_theme | - | 2 | 1 | x |",
        "强度越界": "| 银行 | 保险 | supply | - | 4 | 1 | x |",
        "滞后越界": "| 银行 | 保险 | supply | - | 2 | 9 | x |",
        "关系未知": "| 银行 | 保险 | magic | - | 2 | 1 | x |",
    }
    for label, row in bad.items():
        with pytest.raises(convert.ValidationFailed, match=r"^\d+:"):
            convert.convert_text(header + row + "\n", INDUSTRIES)
        assert label
    dup = (
        header
        + "| 银行 | 保险 | supply | - | 2 | 1 | x |\n| 银行 | 保险 | supply | - | 2 | 1 | y |\n"
    )
    with pytest.raises(convert.ValidationFailed, match="重复"):
        convert.convert_text(dup, INDUSTRIES)
    reverse = (
        header
        + "| 银行 | 保险 | same_theme | + | 2 | 0 | x |\n"
        + "| 保险 | 银行 | same_theme | + | 2 | 0 | y |\n"
    )
    with pytest.raises(convert.ValidationFailed, match="反向重复"):
        convert.convert_text(reverse, INDUSTRIES)


def test_converter_accepts_aliases():
    header = _HEADER
    row = "| `银行` | 保险 | 同题材 | 利好 | 2 | 0日 | 别名 |\n"
    data, _ = convert.convert_text(header + row, INDUSTRIES)
    assert data["edges"][0]["relation"] == "same_theme" and data["edges"][0]["sign"] == 1
    assert data["edges"][0]["lag_days"] == 0


def test_layers_ignore_back_edges():
    ind = ["a", "b", "c"]
    edges = [
        {"from": "a", "to": "b", "relation": "supply"},
        {"from": "b", "to": "c", "relation": "demand"},
        {"from": "c", "to": "a", "relation": "supply"},  # 回边
    ]
    assert convert.compute_layers(ind, edges) == {"a": 0, "b": 1, "c": 2}


# ------------------------------------------------------------ stock_exposure.json
def test_stock_exposure_covers_pool_and_constraints():
    data = _load("stock_exposure.json")
    assert data["version"] == c.EVENT_RULESET_VERSION
    assert data["default_beta_ppm"] == c.DEFAULT_BETA_PPM
    assert data["leader_beta_ppm"] == c.LEADER_BETA_PPM
    assert set(data["stocks"]) == {s["code"] for s in POOL} and len(data["stocks"]) == 385
    by_code = {s["code"]: s for s in POOL}
    for code, item in data["stocks"].items():
        extra = item["extra"]
        assert len(extra) <= 2 and sum(w for _, w in extra) <= 500_000
        assert len({n for n, _ in extra}) == len(extra)
        for name, weight in extra:
            assert name in INDUSTRIES and name != by_code[code]["industry"] and weight > 0
    for ind in INDUSTRIES:
        members = [s["code"] for s in POOL if s["industry"] == ind]
        leaders = [m for m in members if data["stocks"][m]["leader"]]
        assert leaders, f"{ind} 没有龙头"


def test_stock_exposure_is_up_to_date():
    overrides = json.loads(exposure_script.DEFAULT_OVERRIDES.read_text(encoding="utf-8"))
    data, errors = exposure_script.build(POOL, overrides)
    assert not errors
    assert exposure_script.dumps(data) == (DATA / "stock_exposure.json").read_text(encoding="utf-8")


def test_exposure_builder_rejects_bad_overrides():
    _, errors = exposure_script.build(POOL, {"600036": {"extra": [["银行", 100_000]]}})
    assert any("主行业" in e for e in errors)
    _, errors = exposure_script.build(
        POOL, {"600036": {"extra": [["券商", 300_000], ["保险", 300_000]]}}
    )
    assert any("合计" in e for e in errors)
    _, errors = exposure_script.build(POOL, {"000000": {}})
    assert any("不在股票池" in e for e in errors)


# ------------------------------------------------------------ news_templates.json
TEMPLATES = _load("news_templates.json")


def test_templates_file_is_valid_and_up_to_date():
    assert TEMPLATES["version"] == c.EVENT_RULESET_VERSION
    assert templates_script.validate(TEMPLATES, INDUSTRIES) == []
    built = templates_script.build(TEMPLATES)
    assert templates_script.dumps(built) == (DATA / "news_templates.json").read_text(
        encoding="utf-8"
    )
    assert len(TEMPLATES["templates"]) >= 100


def test_templates_meet_coverage_constraints():
    tpls = TEMPLATES["templates"]
    assert len({t["id"] for t in tpls}) == len(tpls)
    for kind, tier in templates_script.DRAWN_COMBOS:
        assert sum(1 for t in tpls if t["kind"] == kind and tier in t["tiers"]) >= 3
    subtypes = {}
    for t in tpls:
        if t["subtype"]:
            subtypes[t["subtype"]] = subtypes.get(t["subtype"], 0) + 1
    assert set(subtypes) == set(templates_script.SUBTYPE_SIGN) and min(subtypes.values()) >= 2
    for t in tpls:
        if t["kind"] == "rumor":
            assert t["confirm"] and t["deny"] and not t["can_price_in"]
        if t["can_price_in"]:
            assert t["precursor"]


def test_script_drawn_combos_match_domain_kind_weights():
    drawn = {(k, "major") for k, _ in c.KIND_WEIGHTS_MAJOR} | {
        (k, "minor") for k, _ in c.KIND_WEIGHTS_MINOR
    }
    assert drawn == set(templates_script.DRAWN_COMBOS)


def test_every_template_renders_with_every_possible_slot_value():
    slot_values = {
        k: [{"zh-CN": o, "en-US": None} if isinstance(o, str) else o for o in v]
        for k, v in TEMPLATES["slot_values"].items()
    }
    rendered = 0
    for t in TEMPLATES["templates"]:
        inds = t["industries"] or INDUSTRIES
        for stage in ("title", "precursor", "confirm", "deny"):
            text = t[stage]
            if not text:
                continue
            for industry in inds if t["scope"] != "market" else [None]:
                ctx = {}
                if industry:
                    ctx["industry"] = industry
                if t["scope"] == "stock":
                    ctx |= {"stock": "测试股", "code": "000001"}
                names = [
                    n for n in placeholders(text["zh-CN"]) if n not in ("stock", "code", "industry")
                ]
                for name in set(names):
                    key = (
                        next(
                            k for k in (f"{name}@{industry}", f"{name}@*", name) if k in slot_values
                        )
                        if name not in ("pct", "amount")
                        else None
                    )
                    for pick in range(len(slot_values[key]) if key else 3):
                        out = render_title(text["zh-CN"], slot_values, {name: pick}, "zh-CN", ctx)
                        assert out and "{" not in out
                        rendered += 1
                if not names:
                    assert "{" not in render_title(text["zh-CN"], slot_values, {}, "zh-CN", ctx)
    assert rendered > 1000


def test_render_title_errors_and_language_fallback():
    slots = {"region": [{"zh-CN": "华东", "en-US": "East China"}, {"zh-CN": "华南", "en-US": None}]}
    assert render_title("{region}订单", slots, {"region": 0}, "en-US", {}) == "East China订单"
    assert render_title("{region}订单", slots, {"region": 1}, "en-US", {}) == "华南订单"
    assert render_title("涨{pct}%", slots, {"pct": 3}, "zh-CN", {}) == "涨8%"
    assert render_title("{amount}亿", slots, {"amount": 49}, "zh-CN", {}) == "50亿"
    with pytest.raises(ValueError):
        render_title("{nonexistent}", slots, {}, "zh-CN", {})
    with pytest.raises(ValueError):
        render_title("{stock}", slots, {}, "zh-CN", {"industry": "银行"})


def test_template_validator_catches_problems():
    def check(mutate, expect):
        data = copy.deepcopy(TEMPLATES)
        mutate(data)
        errors = templates_script.validate(data, INDUSTRIES)
        assert any(expect in e for e in errors), (expect, errors[:3])

    def rumor_without_deny(d):
        next(t for t in d["templates"] if t["kind"] == "rumor")["deny"] = None

    def price_in_without_precursor(d):
        next(t for t in d["templates"] if t["can_price_in"])["precursor"] = None

    def unknown_slot(d):
        d["templates"][0]["title"]["zh-CN"] += "{bogus}"

    def stock_slot_in_industry_scope(d):
        next(t for t in d["templates"] if t["scope"] == "industry")["title"]["zh-CN"] += "{stock}"

    def bad_subtype_sign(d):
        next(t for t in d["templates"] if t["subtype"] == "buyback")["sign"] = -1

    def drop_subtype(d):
        d["templates"] = [t for t in d["templates"] if t["subtype"] != "pledge"]

    def bad_industry(d):
        d["templates"][0]["industries"] = ["火星"]

    check(rumor_without_deny, "confirm 与 deny")
    check(price_in_without_precursor, "precursor")
    check(unknown_slot, "bogus")
    check(stock_slot_in_industry_scope, "不能使用")
    check(bad_subtype_sign, "sign 应为")
    check(drop_subtype, "pledge")
    check(bad_industry, "未知行业")
