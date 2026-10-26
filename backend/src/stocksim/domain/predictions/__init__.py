"""预测卡纯函数包（02 §4、§8）：题型、出题、答案校验与称号目录。零 I/O。

契约见 docs/10.26-plan/02-预测卡.md。
"""

from .constants import (
    DIRECTION_WINDOW_DAYS,
    PREDICTION_DAILY_POINTS_CAP,
    PREDICTION_TICK_BASE,
    WELCOME_POINTS,
)
from .questions import (
    QuestionContext,
    Structure,
    bucket_edges_bp,
    build_questions,
    impact_at,
    rank_truth,
    resolve_rank,
    validate_answers,
)
from .titles import (
    TITLE_CATALOG,
    ScoredAnswer,
    ScoredCard,
    TitleDef,
    TitleStats,
    compute_title_stats,
    evaluate_titles,
)
from .types import BinaryQ, BucketQ, QuestionSpec, RankQ

__all__ = [
    "DIRECTION_WINDOW_DAYS",
    "PREDICTION_DAILY_POINTS_CAP",
    "PREDICTION_TICK_BASE",
    "TITLE_CATALOG",
    "WELCOME_POINTS",
    "BinaryQ",
    "BucketQ",
    "QuestionContext",
    "QuestionSpec",
    "RankQ",
    "ScoredAnswer",
    "ScoredCard",
    "Structure",
    "TitleDef",
    "TitleStats",
    "bucket_edges_bp",
    "build_questions",
    "compute_title_stats",
    "evaluate_titles",
    "impact_at",
    "rank_truth",
    "resolve_rank",
    "validate_answers",
]
