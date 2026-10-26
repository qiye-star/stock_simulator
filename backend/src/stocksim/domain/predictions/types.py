"""预测卡题型（02 §4）。全部不可变；`to_public()` 只输出公开字段（保密规则 §4.5）。

- `tt_end`、`edges_bp` 等服务端字段不出现在 to_public 中（RankQ.tt_end 只用于结算）。
- 存入 `prediction_cards.questions` 的就是 `to_public()` 的结果，API 原样输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TargetKind = Literal["industry", "stock", "market"]


@dataclass(frozen=True)
class BucketQ:
    """方向+幅度题（kind=bucket，RPS）。"""

    target_kind: TargetKind
    target: str | None  # industry：行业名；stock：股票代码；market：None
    target_name: str | None  # 展示名：行业名 / 股票名 / None
    edges_bp: tuple[int, int, int, int]
    from_day: int
    to_day: int
    qid: str = "dir"
    kind: str = "bucket"
    k: int = 5

    def to_public(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "kind": self.kind,
            "target_kind": self.target_kind,
            "target": self.target,
            "target_name": self.target_name,
            "edges_bp": list(self.edges_bp),
            "from_day": self.from_day,
            "to_day": self.to_day,
        }


@dataclass(frozen=True)
class RankQ:
    """产业链冲击排序题（kind=rank，NDCG@3）。candidates 按行业下标升序。"""

    candidates: tuple[str, ...]
    exclude: str  # 源行业
    at_day: int  # 排序口径的收盘日（= 窗口末日）
    tt_end: int  # 服务端：at_day 最后一个交易 tick（理论冲击的计算点，不外发）
    qid: str = "rank"
    kind: str = "rank"
    k: int = 3

    def to_public(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "kind": self.kind,
            "k": self.k,
            "exclude": self.exclude,
            "candidates": list(self.candidates),
            "at_day": self.at_day,
        }


@dataclass(frozen=True)
class BinaryQ:
    """传闻真假题（kind=binary，2 档 RPS）。揭晓 tick 与真值不外发。"""

    qid: str = "rumor"
    kind: str = "binary"
    k: int = 2

    def to_public(self) -> dict[str, Any]:
        return {"qid": self.qid, "kind": self.kind}


QuestionSpec = BucketQ | RankQ | BinaryQ

__all__ = ["BinaryQ", "BucketQ", "QuestionSpec", "RankQ", "TargetKind"]
