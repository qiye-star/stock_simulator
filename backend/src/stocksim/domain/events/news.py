"""快讯文案渲染（01 §7.4）：纯字符串替换，未知槽位抛 ValueError（数据测试负责兜住）。

槽位：{stock} 名称、{code}、{industry}（来自事件上下文）；{pct}（5-30 整数）、{amount}（1-50 亿）
独立抽取，与幅度 M 无关，避免泄露幅度；其余（{product}/{region}/{agency}…）取自 slot_values。
{product} 先查 ``product@<行业>``，查不到用 ``product@*``。抽中的是下标，与语言无关。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .constants import DEFAULT_PICK_AMOUNT, DEFAULT_PICK_PCT
from .types import EventRuleset, GameEvent, LangText, NewsItem

FALLBACK_LANG = "zh-CN"
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
CONTEXT_SLOTS = ("stock", "code", "industry")


def placeholders(text: str) -> list[str]:
    """按出现顺序返回占位符名（含重复）。"""
    return PLACEHOLDER_RE.findall(text)


def pick_count(ruleset: EventRuleset, name: str, industry: str | None) -> int:
    """槽位 name 的可选项个数（RNG 抽样的 n）。pct / amount 为数值范围。"""
    if name == "pct":
        return DEFAULT_PICK_PCT[1] - DEFAULT_PICK_PCT[0] + 1
    if name == "amount":
        return DEFAULT_PICK_AMOUNT[1] - DEFAULT_PICK_AMOUNT[0] + 1
    return len(_options(ruleset.slot_options, name, industry))


def _options(
    slot_values: Mapping[str, Sequence[LangText]], name: str, industry: str | None
) -> Sequence[LangText]:
    for key in (f"{name}@{industry}", f"{name}@*", name):
        if key in slot_values:
            return slot_values[key]
    raise ValueError(f"unknown slot: {name}")


def render_title(
    template_text: str,
    slot_values: Mapping[str, Sequence[LangText]],
    picks: Mapping[str, int],
    lang: str,
    context: Mapping[str, str],
) -> str:
    """渲染一段文案。context 提供 stock/code/industry；缺少所需槽位时抛 ValueError。"""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in CONTEXT_SLOTS:
            if name not in context:
                raise ValueError(f"slot {{{name}}} not available in this scope")
            return context[name]
        if name == "pct":
            return str(
                DEFAULT_PICK_PCT[0] + picks.get("pct", 0) % pick_count_range(DEFAULT_PICK_PCT)
            )
        if name == "amount":
            return str(
                DEFAULT_PICK_AMOUNT[0]
                + picks.get("amount", 0) % pick_count_range(DEFAULT_PICK_AMOUNT)
            )
        options = _options(slot_values, name, context.get("industry"))
        option = options[picks.get(name, 0) % len(options)]
        return option.get(lang) or option[FALLBACK_LANG] or ""

    return PLACEHOLDER_RE.sub(repl, template_text)


def pick_count_range(bounds: tuple[int, int]) -> int:
    return bounds[1] - bounds[0] + 1


def event_context(ruleset: EventRuleset, event: GameEvent) -> dict[str, str]:
    ctx: dict[str, str] = {}
    if event.source_industry is not None:
        ctx["industry"] = event.source_industry
    if event.source_stock_idx is not None:
        stock = ruleset.stocks[event.source_stock_idx]
        ctx["stock"] = stock.name
        ctx["code"] = stock.code
    return ctx


def _stage_text(ruleset: EventRuleset, event: GameEvent, stage: str) -> LangText:
    tmpl = ruleset.template_index[event.template_id]
    text = {
        "precursor": tmpl.precursor,
        "publish": tmpl.title,
        "confirm": tmpl.confirm,
        "deny": tmpl.deny,
    }[stage]
    if text is None:
        raise ValueError(f"template {tmpl.id} has no text for stage {stage}")
    return text


def render_news_title(ruleset: EventRuleset, event: GameEvent, item: NewsItem, lang: str) -> str:
    """一条快讯的标题。en-US 缺失时退回 zh-CN。"""
    text = _stage_text(ruleset, event, item.stage)
    chosen = text.get(lang) or text[FALLBACK_LANG]
    assert chosen is not None
    return render_title(
        chosen, ruleset.slot_options, dict(event.slot_values), lang, event_context(ruleset, event)
    )
