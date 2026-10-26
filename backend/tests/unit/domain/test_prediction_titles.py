"""用户级称号（02 §8）：目录顺序、边界、统计口径。"""

from stocksim.domain.predictions import (
    TITLE_CATALOG,
    ScoredAnswer,
    ScoredCard,
    compute_title_stats,
    evaluate_titles,
)
from stocksim.domain.predictions.titles import TitleStats


def _stats(**kw) -> TitleStats:
    base = dict(
        cards_answered=0,
        perfect_bucket=0,
        perfect_rank=0,
        rumor_hits=0,
        best_streak=0,
        calibrated=0,
        analyst=0,
        intel_purchases=0,
        lifetime_earned=0,
    )
    base.update(kw)
    return TitleStats(**base)


def test_catalog_has_eleven_unique_titles():
    ids = [t.id for t in TITLE_CATALOG]
    assert len(ids) == 11 and len(set(ids)) == 11


def test_cards_thresholds_are_edges():
    assert evaluate_titles(_stats(cards_answered=0), []) == []
    assert evaluate_titles(_stats(cards_answered=1), []) == ["forecaster_1"]
    assert "forecaster_20" not in evaluate_titles(_stats(cards_answered=19), [])
    assert "forecaster_20" in evaluate_titles(_stats(cards_answered=20), [])
    assert "forecaster_100" in evaluate_titles(_stats(cards_answered=100), [])


def test_evaluate_returns_only_new_in_catalog_order():
    st = _stats(cards_answered=100, perfect_bucket=1, lifetime_earned=10_000)
    new = evaluate_titles(st, unlocked=["forecaster_1"])
    assert new == ["forecaster_20", "forecaster_100", "bullseye", "points_10k"]
    assert evaluate_titles(st, unlocked=[t.id for t in TITLE_CATALOG]) == []


def test_single_threshold_titles_edges():
    assert "bullseye" not in evaluate_titles(_stats(perfect_bucket=0), [])
    assert "bullseye" in evaluate_titles(_stats(perfect_bucket=1), [])
    assert "chain_reader" not in evaluate_titles(_stats(perfect_rank=2), [])
    assert "chain_reader" in evaluate_titles(_stats(perfect_rank=3), [])
    assert "rumor_buster" not in evaluate_titles(_stats(rumor_hits=4), [])
    assert "rumor_buster" in evaluate_titles(_stats(rumor_hits=5), [])
    assert "intel_buyer" not in evaluate_titles(_stats(intel_purchases=4), [])
    assert "intel_buyer" in evaluate_titles(_stats(intel_purchases=5), [])
    assert "points_10k" not in evaluate_titles(_stats(lifetime_earned=9_999), [])


def test_compound_titles_flags():
    assert "streak_10" in evaluate_titles(_stats(best_streak=10), [])
    assert "calibrated" in evaluate_titles(_stats(calibrated=1), [])
    assert "analyst" in evaluate_titles(_stats(analyst=1), [])


def _card(*baselines: int) -> ScoredCard:
    return ScoredCard(
        answers=tuple(
            ScoredAnswer(qid="rank", score=50, baseline=b, hit=None, claimed_pct=None)
            for b in baselines
        )
    )


def test_compute_stats_streak_and_analyst():
    good = [_card(40) for _ in range(10)]
    st = compute_title_stats(good, intel_purchases=0, lifetime_earned=0)
    assert st.best_streak == 10
    assert st.analyst == 0  # 只有 10 张卡
    bad = [_card(-10) for _ in range(10)]
    assert compute_title_stats(bad, intel_purchases=0, lifetime_earned=0).best_streak == 0
    many = [_card(35) for _ in range(50)]
    assert compute_title_stats(many, intel_purchases=0, lifetime_earned=0).analyst == 1


def test_compute_stats_counts_perfect_and_hits():
    cards = [
        ScoredCard(
            answers=(
                ScoredAnswer("dir", 100, 80, True, 70),
                ScoredAnswer("rank", 100, 60, None, None),
                ScoredAnswer("rumor", 30, -20, False, 60),
            )
        )
        for _ in range(3)
    ]
    st = compute_title_stats(cards, intel_purchases=2, lifetime_earned=5)
    assert (st.cards_answered, st.perfect_bucket, st.perfect_rank, st.rumor_hits) == (3, 3, 3, 0)
    assert st.intel_purchases == 2 and st.lifetime_earned == 5


def test_calibration_flag_needs_forty_samples_and_low_error():
    # 40 个 70% 声称，命中 28 个 → 误差 |2800−2800|=0 → 通过
    cards = [ScoredCard(answers=(ScoredAnswer("dir", 50, 0, i < 28, 70),)) for i in range(40)]
    assert compute_title_stats(cards, intel_purchases=0, lifetime_earned=0).calibrated == 1
    few = cards[:39]
    assert compute_title_stats(few, intel_purchases=0, lifetime_earned=0).calibrated == 0
