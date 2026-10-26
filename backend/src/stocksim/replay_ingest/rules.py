"""公告过滤与归类规则（05 §2.6），可被关卡规格覆盖。只用标准库。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_DROP_PATTERNS: tuple[str, ...] = (
    r"法律意见书",
    r"独立董事",
    r"核查意见",
    r"保荐",
    r"监事会决议",
    r"董事会决议公告$",
    r"章程",
    r"制度",
    r"提示性公告$",
)

# 顺序即优先级：先匹配先归类
CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("earnings", r"业绩预告|业绩快报|年度报告|半年度报告|季度报告"),
    ("operation", r"停产|减产|事故|检修|火灾"),
    ("contract", r"中标|签订|合同"),
    ("holding", r"增持|减持|回购|质押"),
    ("risk", r"风险提示|异常波动|退市|立案|处罚|问询"),
)

# 归类 -> importance（other 默认不展示，只在揭示期使用）
CATEGORY_IMPORTANCE: dict[str, int] = {
    "earnings": 2,
    "operation": 3,
    "contract": 2,
    "holding": 2,
    "risk": 2,
    "other": 1,
}

DEFAULT_CCTV_KEYWORDS: tuple[str, ...] = (
    "国务院",
    "常务会议",
    "中国人民银行",
    "央行",
    "降准",
    "降息",
    "证监会",
    "金融监管",
    "财政部",
    "印花税",
    "发改委",
    "工信部",
    "稳增长",
    "房地产",
)

CCTV_BODY_LIMIT = 300
EVENT_BODY_LIMIT = 500


@dataclass(frozen=True)
class CninfoRules:
    drop: tuple[re.Pattern[str], ...]

    @classmethod
    def from_spec(cls, source: Any) -> CninfoRules:
        """``sources.cninfo`` 为 true 用默认；为对象时 ``drop`` 整体替换、``drop_extra`` 追加。"""
        patterns: Sequence[str] = DEFAULT_DROP_PATTERNS
        if isinstance(source, Mapping):
            patterns = tuple(source.get("drop", patterns)) + tuple(source.get("drop_extra", ()))
        return cls(tuple(re.compile(p) for p in patterns))

    def is_routine(self, title: str) -> bool:
        return any(p.search(title) for p in self.drop)


def classify_title(title: str) -> str:
    for category, pattern in CATEGORY_PATTERNS:
        if re.search(pattern, title):
            return category
    return "other"


def cctv_keywords(source: Any, extra: Sequence[str] = ()) -> tuple[str, ...]:
    """规格 ``sources.cctv.keywords`` 优先；缺省为默认关键词加关卡行业词。"""
    if isinstance(source, Mapping) and source.get("keywords"):
        return tuple(source["keywords"])
    return DEFAULT_CCTV_KEYWORDS + tuple(extra)


def cctv_hit(title: str, content: str, keywords: Sequence[str]) -> bool:
    return any(k in title or k in content for k in keywords)
