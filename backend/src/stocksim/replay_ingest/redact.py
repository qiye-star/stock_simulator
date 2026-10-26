"""匿名模式的文本脱敏（05 §1.7）。只用标准库。

做三件事：
1. 把关卡股票的 ``redact_terms`` / 真名 / 真实代码替换成别名；
2. 把年份与具体日期替换成“近日”等模糊说法；
3. 扫描残留（年份数字、漏网的真名/真代码），交给 ``redaction_report`` 供作者人工确认。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_YEAR = r"(?:19|20)\d{2}"

# 顺序重要：长模式在前。
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"{_YEAR}\s*年\s*\d{{1,2}}\s*月\s*\d{{1,2}}\s*[日号]"), "近日"),
    (re.compile(rf"{_YEAR}[-/.]\d{{1,2}}[-/.]\d{{1,2}}"), "近日"),
    (re.compile(rf"{_YEAR}\s*年\s*\d{{1,2}}\s*月"), "近期"),
    (re.compile(r"(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*[日号]"), "近日"),
    (re.compile(rf"{_YEAR}\s*年度"), "本年度"),
    (re.compile(rf"{_YEAR}\s*年"), ""),
)

# 残留年份：4 位年份数字，且后面不是金额/数量单位（“2000 万元”不算）
_RESIDUAL_YEAR = re.compile(rf"(?<![\d.,]){_YEAR}(?![\d,]|\.\d)(?!\s*[万亿元股%％吨手])")


@dataclass(frozen=True)
class StockMask:
    key: str
    real_code: str
    real_name: str
    alias_code: str
    alias_name: str
    terms: tuple[str, ...] = ()

    def all_terms(self) -> tuple[str, ...]:
        """真名与 redact_terms，去重，长词在前。"""
        uniq = {t for t in (self.real_name, *self.terms) if t}
        return tuple(sorted(uniq, key=lambda t: (-len(t), t)))


def scrub_dates(text: str) -> str:
    for pattern, repl in _DATE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def mask_text(text: str, masks: Sequence[StockMask], *, placeholder: str | None = None) -> str:
    """脱敏一段文本。``placeholder`` 不为 None 时，所有命中的名称都替换成它（如 ``{name}``）。"""
    pairs: list[tuple[str, str]] = []
    for m in masks:
        for term in m.all_terms():
            pairs.append((term, placeholder if placeholder is not None else m.alias_name))
    pairs.sort(key=lambda p: (-len(p[0]), p[0]))
    for term, repl in pairs:
        text = text.replace(term, repl)
    for m in masks:
        text = re.sub(rf"(?<!\d){re.escape(m.real_code)}(?!\d)", m.alias_code, text)
    return scrub_dates(text)


def find_residuals(text: str, masks: Sequence[StockMask]) -> list[str]:
    """脱敏后仍残留的可疑片段（去重、保持出现顺序）。"""
    hits: list[str] = []
    for m in masks:
        for term in m.all_terms():
            if term in text:
                hits.append(term)
        if re.search(rf"(?<!\d){re.escape(m.real_code)}(?!\d)", text):
            hits.append(m.real_code)
    hits.extend(match.group(0) for match in _RESIDUAL_YEAR.finditer(text))
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out
