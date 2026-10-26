"""用户级称号（02 §8）：声明式目录 + 纯函数判定。不进存档成就（54 条断言不受影响）。

统计口径：records 为该用户已结算且作答的卡（按结算先后排序）。布尔型条件（校准、分析师、稳定发挥）
用 0/1 统计量，阈值为 1，以便与“≥ 阈值”的统一判定兼容。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from ..scoring import calibration_bins, calibration_error_bp
from .constants import (
    TITLE_ANALYST_MIN_AVG_BASELINE,
    TITLE_ANALYST_MIN_CARDS,
    TITLE_CALIBRATION_MAX_ERROR_BP,
    TITLE_CALIBRATION_MIN_SAMPLES,
    TITLE_STREAK_WINDOW,
)


@dataclass(frozen=True)
class TitleDef:
    id: str
    level: str  # bronze / silver / gold / legend
    stat: str  # TitleStats 的字段名
    threshold: int


@dataclass(frozen=True)
class ScoredAnswer:
    qid: str  # dir / rank / rumor
    score: int
    baseline: int
    hit: bool | None  # 概率题：argmax 是否命中；排序题为 None
    claimed_pct: int | None  # 概率题的声称置信度（max(probs)），并列时仍有值


@dataclass(frozen=True)
class ScoredCard:
    answers: tuple[ScoredAnswer, ...]


@dataclass(frozen=True)
class TitleStats:
    cards_answered: int
    perfect_bucket: int  # 方向题得 100 的次数
    perfect_rank: int  # 排序题得 100 的次数
    rumor_hits: int  # 传闻题命中次数
    best_streak: int  # 10 张滑窗（结算顺序）平均基线分 > 0 存在则为 TITLE_STREAK_WINDOW，否则 0
    calibrated: int  # 概率题样本 ≥ 40 且 校准误差 ≤ 800 bp 则为 1
    analyst: int  # 作答卡 ≥ 50 且平均基线分 ≥ 30 则为 1
    intel_purchases: int
    lifetime_earned: int


def _card_mean_baseline(card: ScoredCard) -> Fraction:
    vals = [a.baseline for a in card.answers]
    return Fraction(sum(vals), len(vals)) if vals else Fraction(0)


def _has_positive_window(cards: Sequence[ScoredCard], width: int) -> bool:
    if len(cards) < width:
        return False
    means = [_card_mean_baseline(c) for c in cards]
    window = sum(means[:width])
    if window > 0:
        return True
    for i in range(width, len(means)):
        window += means[i] - means[i - width]
        if window > 0:
            return True
    return False


def compute_title_stats(
    records: Sequence[ScoredCard],
    *,
    intel_purchases: int,
    lifetime_earned: int,
) -> TitleStats:
    answers = [a for c in records for a in c.answers]
    prob = [a for a in answers if a.hit is not None and a.claimed_pct is not None]
    bins = calibration_bins((a.claimed_pct, bool(a.hit)) for a in prob)  # type: ignore[arg-type]
    ece = calibration_error_bp(bins)
    calibrated = (
        len(prob) >= TITLE_CALIBRATION_MIN_SAMPLES
        and ece is not None
        and (ece <= TITLE_CALIBRATION_MAX_ERROR_BP)
    )
    avg_baseline = Fraction(sum(a.baseline for a in answers), len(answers)) if answers else None
    analyst = (
        len(records) >= TITLE_ANALYST_MIN_CARDS
        and avg_baseline is not None
        and avg_baseline >= TITLE_ANALYST_MIN_AVG_BASELINE
    )
    return TitleStats(
        cards_answered=len(records),
        perfect_bucket=sum(1 for a in answers if a.qid == "dir" and a.score == 100),
        perfect_rank=sum(1 for a in answers if a.qid == "rank" and a.score == 100),
        rumor_hits=sum(1 for a in answers if a.qid == "rumor" and a.hit),
        best_streak=(
            TITLE_STREAK_WINDOW if _has_positive_window(records, TITLE_STREAK_WINDOW) else 0
        ),
        calibrated=1 if calibrated else 0,
        analyst=1 if analyst else 0,
        intel_purchases=intel_purchases,
        lifetime_earned=lifetime_earned,
    )


TITLE_CATALOG: tuple[TitleDef, ...] = (
    TitleDef("forecaster_1", "bronze", "cards_answered", 1),
    TitleDef("forecaster_20", "silver", "cards_answered", 20),
    TitleDef("forecaster_100", "gold", "cards_answered", 100),
    TitleDef("bullseye", "silver", "perfect_bucket", 1),
    TitleDef("chain_reader", "silver", "perfect_rank", 3),
    TitleDef("rumor_buster", "silver", "rumor_hits", 5),
    TitleDef("streak_10", "gold", "best_streak", TITLE_STREAK_WINDOW),
    TitleDef("calibrated", "gold", "calibrated", 1),
    TitleDef("analyst", "legend", "analyst", 1),
    TitleDef("intel_buyer", "bronze", "intel_purchases", 5),
    TitleDef("points_10k", "gold", "lifetime_earned", 10_000),
)


def evaluate_titles(stats: TitleStats, unlocked: Iterable[str]) -> list[str]:
    """返回本次新解锁的称号 id（目录顺序，不含已解锁的）。"""
    done = set(unlocked)
    out: list[str] = []
    for t in TITLE_CATALOG:
        if t.id in done:
            continue
        if getattr(stats, t.stat) >= t.threshold:
            out.append(t.id)
    return out


__all__ = [
    "TITLE_CATALOG",
    "ScoredAnswer",
    "ScoredCard",
    "TitleDef",
    "TitleStats",
    "compute_title_stats",
    "evaluate_titles",
]
