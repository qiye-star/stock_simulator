"""由已解析的 JSON 数据构造 ``EventRuleset``（domain 不读文件，调用方负责 json.load）。

输入：supply_chain.json / stock_exposure.json / news_templates.json 的解析结果，
以及 industries.json、stock_pool.json 的解析结果。任何不一致都抛 ValueError。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..clock import CLOCK_RULES_V1, timebase
from .constants import (
    DEFAULT_BETA_PPM,
    EVENT_RULESET_VERSION,
    LEADER_BETA_PPM,
    MAX_PICKS,
)
from .graph import build_out_edges
from .types import EventRuleset, StockInfo, SupplyEdge, Template

SCOPES = ("stock", "industry", "market")
TIERS = ("major", "minor")
PICK_BUILTINS = ("pct", "amount")  # 不依赖 slot_values 的数值槽位


def _lang(value: Any) -> dict[str, str | None]:
    """字符串（只有中文）或 {zh-CN, en-US} 对象 -> 统一为 {"zh-CN": str, "en-US": str|None}。"""
    if isinstance(value, str):
        return {"zh-CN": value, "en-US": None}
    if isinstance(value, Mapping) and isinstance(value.get("zh-CN"), str):
        return {"zh-CN": value["zh-CN"], "en-US": value.get("en-US")}
    raise ValueError(f"invalid localized text: {value!r}")


def _opt_lang(value: Any) -> dict[str, str | None] | None:
    return None if value is None else _lang(value)


def build_ruleset(
    *,
    supply_chain: Mapping[str, Any],
    exposure: Mapping[str, Any],
    templates: Mapping[str, Any],
    industries: Sequence[Mapping[str, Any]],
    stock_pool: Sequence[Mapping[str, Any]],
    version: int = EVENT_RULESET_VERSION,
    clock_rules: int = CLOCK_RULES_V1,
    ticks_per_day: int | None = None,
) -> EventRuleset:
    """构造规则集。时间基由 clock_rules 决定（domain.clock.timebase）；ticks_per_day 只用于
    测试显式指定时，必须与时间基一致。"""
    ticks_per_day_ref = timebase(clock_rules).ticks_per_day
    if ticks_per_day is None:
        ticks_per_day = ticks_per_day_ref
    elif ticks_per_day != ticks_per_day_ref:
        raise ValueError("ticks_per_day does not match clock_rules")
    for name, data in (
        ("supply_chain", supply_chain),
        ("stock_exposure", exposure),
        ("news_templates", templates),
    ):
        if data.get("version") != version:
            raise ValueError(f"{name}.json version {data.get('version')} != ruleset {version}")

    names = tuple(str(i["name"]) for i in industries)
    index = {n: i for i, n in enumerate(names)}
    if len(index) != len(names):
        raise ValueError("duplicate industry names")
    if [n["id"] for n in supply_chain["nodes"]] != list(names):
        raise ValueError("supply_chain nodes must equal industries.json (same order)")
    layers = tuple(int(n["layer"]) for n in supply_chain["nodes"])

    # ---- 股票
    exp_stocks = exposure["stocks"]
    stocks: list[StockInfo] = []
    members: list[list[tuple[int, int]]] = [[] for _ in names]
    main_members: list[list[int]] = [[] for _ in names]
    counts = [0] * len(names)
    for idx, s in enumerate(stock_pool):
        code = str(s["code"])
        if code not in exp_stocks:
            raise ValueError(f"stock {code} missing in stock_exposure")
        ind = index[str(s["industry"])]
        raw = exp_stocks[code]
        extra = tuple((index[str(n)], int(w)) for n, w in raw.get("extra", []))
        main_w = 1_000_000 - sum(w for _, w in extra)
        if main_w <= 0 or len(extra) > 2 or any(n == ind for n, _ in extra):
            raise ValueError(f"invalid exposure for {code}")
        stocks.append(
            StockInfo(
                idx=idx,
                code=code,
                name=str(s["name"]),
                industry=ind,
                profile=str(s.get("profile", "normal")),
                leader=bool(raw["leader"]),
                extra=extra,
            )
        )
        counts[ind] += 1
        main_members[ind].append(idx)
        members[ind].append((idx, main_w))
        for n, w in extra:
            members[n].append((idx, w))
    if len(exp_stocks) != len(stocks):
        raise ValueError("stock_exposure has stocks not in the pool")
    for want, got in zip((int(i["stock_count"]) for i in industries), counts, strict=True):
        if want != got:
            raise ValueError("industries.json stock_count does not match stock pool")

    # ---- 边
    edges: list[SupplyEdge] = []
    seen: set[tuple[int, int]] = set()
    for e in supply_chain["edges"]:
        a, b = index[str(e["from"])], index[str(e["to"])]
        if a == b or (a, b) in seen or (b, a) in seen:
            raise ValueError(f"invalid or duplicate edge {e['id']}")
        seen.add((a, b))
        edges.append(
            SupplyEdge(
                a,
                b,
                str(e["relation"]),
                int(e["sign"]),
                int(e["strength"]),
                int(e["lag_days"]),
                str(e.get("note", "")),
            )
        )
    out_edges = build_out_edges(len(names), edges)
    degree = tuple(len(o) for o in out_edges)

    # ---- 文案
    slot_options: dict[str, tuple[Any, ...]] = {
        key: tuple(_lang(v) for v in values) for key, values in templates["slot_values"].items()
    }
    pick_names = tuple(sorted({k.split("@")[0] for k in slot_options} | set(PICK_BUILTINS)))
    if len(pick_names) > MAX_PICKS:
        raise ValueError(f"too many slot names: {len(pick_names)} > {MAX_PICKS}")
    parsed: list[Template] = []
    for t in templates["templates"]:
        whitelist = t.get("industries")
        if whitelist is not None and any(n not in index for n in whitelist):
            raise ValueError(f"template {t['id']}: unknown industry in whitelist")
        tilts = t.get("tilts")
        if tilts is not None and any(x["industry"] not in index for x in tilts):
            raise ValueError(f"template {t['id']}: unknown industry in tilts")
        if t["scope"] not in SCOPES or any(x not in TIERS for x in t["tiers"]):
            raise ValueError(f"template {t['id']}: bad scope/tiers")
        parsed.append(
            Template(
                id=str(t["id"]),
                kind=str(t["kind"]),
                subtype=t.get("subtype"),
                scope=str(t["scope"]),
                tiers=tuple(t["tiers"]),
                channel=str(t["channel"]),
                sign=int(t["sign"]),
                industries=None if whitelist is None else tuple(whitelist),
                can_price_in=bool(t.get("can_price_in", False)),
                weight=int(t["weight"]),
                tilts=None
                if tilts is None
                else tuple((x["industry"], int(x["weight_ppm"])) for x in tilts),
                title=_lang(t["title"]),
                precursor=_opt_lang(t.get("precursor")),
                confirm=_opt_lang(t.get("confirm")),
                deny=_opt_lang(t.get("deny")),
            )
        )
    parsed.sort(key=lambda t: t.id)
    by_kt: dict[tuple[str, str], list[Template]] = {}
    for t in parsed:
        for tier in t.tiers:
            by_kt.setdefault((t.kind, tier), []).append(t)

    return EventRuleset(
        version=version,
        industries=names,
        industry_index=index,
        layers=layers,
        stock_counts=tuple(counts),
        stocks=tuple(stocks),
        stock_index={s.code: s.idx for s in stocks},
        industry_stocks=tuple(tuple(m) for m in main_members),
        industry_members=tuple(tuple(m) for m in members),
        edges=tuple(edges),
        out_edges=out_edges,
        degree=degree,
        templates=tuple(parsed),
        templates_by_kind_tier={k: tuple(v) for k, v in by_kt.items()},
        template_index={t.id: t for t in parsed},
        slot_options=slot_options,
        pick_names=pick_names,
        default_beta_ppm=int(exposure.get("default_beta_ppm", DEFAULT_BETA_PPM)),
        leader_beta_ppm=int(exposure.get("leader_beta_ppm", LEADER_BETA_PPM)),
        ticks_per_day=ticks_per_day,
        clock_rules=clock_rules,
    )
