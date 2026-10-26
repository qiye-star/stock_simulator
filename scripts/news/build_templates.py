"""校验 templates_src.json 并生成 backend/src/stocksim/data/news_templates.json。

用法：
    python3 scripts/news/build_templates.py           # 校验 -> 按 id 排序 -> 写 data 文件（幂等）
    python3 scripts/news/build_templates.py --check   # 只校验，并检查 data 文件是否最新（不写文件）

约束见 docs/10.26-plan/01-事件行情.md §7.4。纯标准库。校验失败逐条列出并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "backend" / "src" / "stocksim" / "data"
DEFAULT_SRC = HERE / "templates_src.json"
DEFAULT_OUT = DATA / "news_templates.json"

VERSION = 1
KINDS = ("announcement", "news", "policy", "sudden", "rumor")
SCOPES = ("stock", "industry", "market")
TIERS = ("major", "minor")
CHANNELS = ("demand", "cost", "sentiment")
LANGS = ("zh-CN", "en-US")
CONTEXT_SLOTS = ("stock", "code", "industry")
BUILTIN_PICKS = ("pct", "amount")
MAX_PICKS = 32
MIN_PER_COMBO = 3
MIN_PER_SUBTYPE = 2
# 事件生成实际会抽到的 (kind, tier)，与 domain/events/constants.py 的 KIND_WEIGHTS_* 一致
DRAWN_COMBOS = [(k, "major") for k in KINDS] + [
    ("announcement", "minor"),
    ("news", "minor"),
    ("rumor", "minor"),
]
# DuEE-fin 13 类公告与默认 sign（01 §4.1）；0 表示由 RNG 决定方向
SUBTYPE_SIGN = {
    "pledge": -1,
    "pledge_release": 1,
    "buyback": 1,
    "holder_reduce": -1,
    "holder_increase": 1,
    "loss": -1,
    "acquisition": 0,
    "financing": -1,
    "bankruptcy": -1,
    "listing": 1,
    "exec_change": 0,
    "summoned": -1,
    "bid_win": 1,
}
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
STAGE_FIELDS = ("title", "precursor", "confirm", "deny")


def _options(slot_values: dict, name: str, industry: str | None) -> list | None:
    for key in (f"{name}@{industry}", f"{name}@*", name):
        if key in slot_values:
            return slot_values[key]
    return None


def _opt_text(option, lang: str) -> str:
    if isinstance(option, str):
        return option
    return option.get(lang) or option["zh-CN"]


def validate(src: dict, industries: list[str]) -> list[str]:
    errors: list[str] = []
    if src.get("version") != VERSION:
        errors.append(f"version 应为 {VERSION}")
    slot_values = src.get("slot_values", {})
    for key, opts in slot_values.items():
        if not isinstance(opts, list) or not opts:
            errors.append(f"slot_values[{key}] 必须是非空数组")
            continue
        for opt in opts:
            ok = isinstance(opt, str) or (
                isinstance(opt, dict) and isinstance(opt.get("zh-CN"), str)
            )
            if not ok:
                errors.append(f"slot_values[{key}] 含非法项 {opt!r}")
    names = {k.split("@")[0] for k in slot_values} | set(BUILTIN_PICKS)
    if names & set(CONTEXT_SLOTS):
        errors.append(f"slot_values 不能占用内置槽位 {sorted(names & set(CONTEXT_SLOTS))}")
    if len(names) > MAX_PICKS:
        errors.append(f"槽位名超过 {MAX_PICKS} 个")
    industry_set = set(industries)
    for key in slot_values:
        if "@" in key:
            _base, ind = key.split("@", 1)
            if ind != "*" and ind not in industry_set:
                errors.append(f"slot_values[{key}] 的行业不在 82 个标签内")
    ids: set[str] = set()
    templates = src.get("templates", [])
    combo_count: dict[tuple[str, str], int] = {}
    subtype_count: dict[str, int] = {}
    for t in templates:
        tid = t.get("id", "?")
        err = lambda msg, tid=tid: errors.append(f"{tid}: {msg}")  # noqa: E731
        if tid in ids:
            err("id 重复")
        ids.add(tid)
        for field in ("kind", "scope", "tiers", "channel", "sign", "weight", "title"):
            if field not in t:
                err(f"缺少字段 {field}")
        if any(
            f not in t for f in ("kind", "scope", "tiers", "channel", "sign", "weight", "title")
        ):
            continue
        if t["kind"] not in KINDS:
            err(f"未知 kind {t['kind']!r}")
        if t["scope"] not in SCOPES:
            err(f"未知 scope {t['scope']!r}")
        if not t["tiers"] or any(x not in TIERS for x in t["tiers"]):
            err("tiers 必须是 major/minor 的非空子集")
        if t["channel"] not in CHANNELS:
            err(f"未知 channel {t['channel']!r}")
        if t["sign"] not in (-1, 0, 1):
            err("sign 必须是 -1/0/1")
        if not isinstance(t["weight"], int) or t["weight"] <= 0:
            err("weight 必须是正整数")
        if t["kind"] == "announcement":
            if t["scope"] != "stock":
                err("公告的 scope 必须是 stock")
            sub = t.get("subtype")
            if sub not in SUBTYPE_SIGN:
                err(f"公告 subtype 必须是 13 类之一，实际 {sub!r}")
            else:
                subtype_count[sub] = subtype_count.get(sub, 0) + 1
                if t["sign"] != SUBTYPE_SIGN[sub]:
                    err(f"subtype {sub} 的 sign 应为 {SUBTYPE_SIGN[sub]}")
        elif t.get("subtype") is not None:
            err("非公告的 subtype 必须为 null")
        if t["sign"] == 0 and t["kind"] != "announcement":
            err("只有公告可以 sign=0")
        wl = t.get("industries")
        if wl is not None:
            if not wl or any(n not in industry_set for n in wl):
                err("industries 白名单含未知行业或为空")
            if t["scope"] == "market":
                err("market 模板不能有行业白名单")
        tilts = t.get("tilts")
        if tilts is not None:
            if t["scope"] != "market":
                err("只有 market 模板可以带 tilts")
            for x in tilts:
                if x.get("industry") not in industry_set or not isinstance(
                    x.get("weight_ppm"), int
                ):
                    err(f"tilts 项非法 {x!r}")
                elif not 0 < abs(x["weight_ppm"]) <= 1_000_000:
                    err("tilts 的 weight_ppm 绝对值须在 (0, 1e6]")
        if t["kind"] == "rumor":
            if not t.get("confirm") or not t.get("deny"):
                err("传闻必须给出 confirm 与 deny")
            if t.get("can_price_in"):
                err("传闻不能 can_price_in")
        if t.get("can_price_in") and not t.get("precursor"):
            err("can_price_in=true 必须给出 precursor")
        if t["kind"] != "rumor" and (t.get("confirm") or t.get("deny")):
            err("只有传闻可以有 confirm/deny")
        for tier in t["tiers"]:
            combo_count[(t["kind"], tier)] = combo_count.get((t["kind"], tier), 0) + 1
        errors.extend(_check_texts(t, slot_values, industries, wl))
    for combo in DRAWN_COMBOS:
        if combo_count.get(combo, 0) < MIN_PER_COMBO:
            errors.append(f"({combo[0]}, {combo[1]}) 至少需要 {MIN_PER_COMBO} 条模板")
    for combo, n in combo_count.items():
        if n < MIN_PER_COMBO:
            errors.append(f"({combo[0]}, {combo[1]}) 只有 {n} 条模板，至少 {MIN_PER_COMBO}")
    for sub in SUBTYPE_SIGN:
        if subtype_count.get(sub, 0) < MIN_PER_SUBTYPE:
            errors.append(f"公告 subtype {sub} 至少需要 {MIN_PER_SUBTYPE} 条模板")
    return errors


def _check_texts(
    t: dict, slot_values: dict, industries: list[str], wl: list[str] | None
) -> list[str]:
    """逐条文案检查槽位合法，并用全部可能的槽位取值渲染一遍。"""
    errors: list[str] = []
    tid = t["id"]
    scope = t["scope"]
    allowed_ctx = {
        "stock": scope == "stock",
        "code": scope == "stock",
        "industry": scope != "market",
    }
    candidates = wl if wl is not None else industries
    for field in STAGE_FIELDS:
        text = t.get(field)
        if text is None:
            continue
        if not isinstance(text, dict) or not isinstance(text.get("zh-CN"), str):
            errors.append(f"{tid}.{field}: 必须是 {{zh-CN, en-US}} 对象且 zh-CN 为字符串")
            continue
        base = set(PLACEHOLDER_RE.findall(text["zh-CN"]))
        for lang in LANGS:
            value = text.get(lang)
            if value is None:
                continue
            found = set(PLACEHOLDER_RE.findall(value))
            if found != base and lang != "zh-CN":
                errors.append(f"{tid}.{field}.{lang}: 槽位集合与 zh-CN 不一致")
            if "{" in PLACEHOLDER_RE.sub("", value) or "}" in PLACEHOLDER_RE.sub("", value):
                errors.append(f"{tid}.{field}.{lang}: 含未配对的花括号")
            for name in found:
                if name in CONTEXT_SLOTS:
                    if not allowed_ctx[name]:
                        errors.append(f"{tid}.{field}.{lang}: scope={scope} 不能使用 {{{name}}}")
                elif name in BUILTIN_PICKS:
                    continue
                else:
                    for industry in candidates if scope != "market" else [None]:
                        opts = _options(slot_values, name, industry)
                        if opts is None:
                            errors.append(
                                f"{tid}.{field}.{lang}: 未知槽位 {{{name}}}（行业 {industry}）"
                            )
                            break
                        for opt in opts:
                            rendered = PLACEHOLDER_RE.sub(
                                lambda m, o=opt, n=name, lg=lang: (
                                    _opt_text(o, lg) if m.group(1) == n else m.group(0)
                                ),
                                value,
                            )
                            if not rendered:
                                errors.append(f"{tid}.{field}.{lang}: 渲染为空")
                        else:
                            continue
                        break
    return errors


def dumps(data: dict) -> str:
    """slot_values 每键一行，templates 每条一行，便于 diff。"""
    lines = ["{", f'  "version": {data["version"]},', '  "slot_values": {']
    items = list(data["slot_values"].items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(
            f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}{comma}"
        )
    lines += ["  },", '  "templates": [']
    tpls = data["templates"]
    for i, t in enumerate(tpls):
        lines.append(
            "    " + json.dumps(t, ensure_ascii=False) + ("," if i < len(tpls) - 1 else "")
        )
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def build(src: dict) -> dict:
    return {
        "version": src["version"],
        "slot_values": dict(sorted(src["slot_values"].items())),
        "templates": sorted(src["templates"], key=lambda t: t["id"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    industries = [
        i["name"] for i in json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
    ]
    src = json.loads(args.src.read_text(encoding="utf-8"))
    errors = validate(src, industries)
    if errors:
        for e in errors:
            print(f"ERROR {e}", file=sys.stderr)
        return 1
    rendered = dumps(build(src))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != rendered:
            print(
                f"ERROR {args.out} 不是最新，请运行 python3 scripts/news/build_templates.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK {len(src['templates'])} templates")
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out} ({len(src['templates'])} templates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
