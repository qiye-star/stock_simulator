"""报名的合格标记（03 §7.4、§9）：不合格者仍可报名并建存档，只是 eligible=false；重复报名幂等。"""

from datetime import timedelta

from stocksim.services.challenges import entries, generate

from .test_challenge_scoring_db import CHALLENGE_NOW, DAY, aware


def test_ineligible_join_creates_archive_flagged_and_is_idempotent(
    db, fake_clock, make_user, challenge_play
):
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    starts = aware(ch.starts_at)
    late = make_user("late_join")
    late.created_at = starts + timedelta(hours=1)  # 注册晚于开局，不满足账号年龄门槛
    db.commit()
    fake_clock.value = starts

    entry, created = entries.join(db, ch, late, fake_clock.value)
    assert created is True
    assert entry.eligible is False
    assert entry.save_id is not None  # 仍建玩家存档，可作答、可交易

    again, created_again = entries.join(db, ch, late, fake_clock.value)
    assert created_again is False and again.id == entry.id
