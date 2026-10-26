"""每日挑战结算的计分与排行（C6）：同伴分、交易分、竞赛排名、日/周/总榜与 me。

每个用例都从库里读出原始数据（回合作答、持仓、主行情价格）独立复算，不信任结算写入的结果。
时间由 fake_clock 控制；作答与交易走服务层（见 conftest 的 challenge_play）。
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from stocksim.core.errors import AppError, ErrorCode
from stocksim.domain.challenge.constants import CHALLENGE_PEER_MIN
from stocksim.domain.challenge.ranking import competition_ranks, iso_week_key
from stocksim.domain.challenge.scoring import trade_scores
from stocksim.domain.money import round_half_up_div
from stocksim.models import ChallengeAnswer, ChallengeEntry, ChallengeRound, LedgerEntry, Save
from stocksim.services import equity as equity_service
from stocksim.services import market as market_service
from stocksim.services.challenges import boards, generate, registry

DAY = date(2026, 10, 26)
CHALLENGE_NOW = datetime(2026, 10, 26, 1, 0, 0, tzinfo=UTC)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def settled_challenge(db, fake_clock, make_user, challenge_play, *, eligible: int, ineligible: int):
    """生成挑战，报名 eligible 个合格与 ineligible 个不合格（注册晚于开局），打完并结算。"""
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    starts = aware(ch.starts_at)
    users = [make_user(f"ok{i}") for i in range(eligible)]
    for i in range(ineligible):
        late = make_user(f"late{i}")
        late.created_at = starts + timedelta(hours=1)
        db.commit()
        users.append(late)
    rows = challenge_play.join(ch, users)
    challenge_play.play_rounds(ch, rows)
    assert challenge_play.settle(ch) is True
    db.refresh(ch)
    return ch, rows


def eligible_entries(db, ch) -> list[ChallengeEntry]:
    return list(
        db.scalars(
            select(ChallengeEntry)
            .where(ChallengeEntry.challenge_id == ch.id, ChallengeEntry.eligible.is_(True))
            .order_by(ChallengeEntry.id)
        )
    )


def all_entries(db, ch) -> list[ChallengeEntry]:
    return list(db.scalars(select(ChallengeEntry).where(ChallengeEntry.challenge_id == ch.id)))


def answers_by_round(db, ch) -> dict[int, list[ChallengeAnswer]]:
    out: dict[int, list[ChallengeAnswer]] = {}
    for rnd in db.scalars(select(ChallengeRound).where(ChallengeRound.challenge_id == ch.id)):
        out[rnd.round_index] = list(
            db.scalars(select(ChallengeAnswer).where(ChallengeAnswer.round_id == rnd.id))
        )
    return out


def test_peer_scores_sum_to_zero_and_ineligible_get_baseline(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    ch, _ = settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=2)
    eligible_ids = {e.id for e in eligible_entries(db, ch)}
    n = len(eligible_ids)
    assert n == 5 and ch.eligible_count == 5
    per_round = answers_by_round(db, ch)
    checked = 0
    for answers in per_round.values():
        qids = {qid for a in answers for qid in a.results}
        for qid in qids:
            peer_sum = 0
            for a in answers:
                res = a.results[qid]
                if a.entry_id in eligible_ids:
                    assert res["used"] == "peer"
                    assert res["score"] == res["peer"]
                    peer_sum += res["score"]
                else:
                    assert res["used"] == "baseline" and res["score"] == res["baseline"]
                checked += 1
            assert abs(peer_sum) <= n, (qid, peer_sum)
    assert checked > 0


def test_four_eligible_degrades_to_baseline(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    ch, _ = settled_challenge(
        db, fake_clock, make_user, challenge_play, eligible=CHALLENGE_PEER_MIN - 1, ineligible=2
    )
    assert ch.eligible_count == CHALLENGE_PEER_MIN - 1
    for answers in answers_by_round(db, ch).values():
        for a in answers:
            for res in a.results.values():
                assert res["used"] == "baseline" and res["score"] == res["baseline"]
    # 交易分同样退化：参考集 < 5 时按原始收益折算
    entries = eligible_entries(db, ch)
    returns = [e.return_bp for e in entries]
    assert [e.trade_score for e in entries] == trade_scores(returns, [True] * len(entries))


def test_entry_fields_recomputed_from_raw_state(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    ch, _ = settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=2)
    master = registry.market_save_for(db, ch)
    state, _ = market_service.load_market(db, master)
    prices = {s["code"]: int(s["price"]) for s in state["stocks"]}
    entries = all_entries(db, ch)
    forecast = {}
    for answers in answers_by_round(db, ch).values():
        for a in answers:
            forecast[a.entry_id] = forecast.get(a.entry_id, 0) + a.round_score
    for e in entries:
        save = db.get(Save, e.save_id)
        held = equity_service.holding_quantities(db, save.id)
        equity = save.cash_cents + sum(q * prices[c] for c, q in held.items())
        assert e.final_equity_cents == equity
        assert e.return_bp == round_half_up_div(
            (equity - save.initial_fund_cents) * 10_000, save.initial_fund_cents
        )
        assert e.forecast_score == forecast.get(e.id, 0)
        assert e.total_score == e.forecast_score + e.trade_score
        assert e.settled_at is not None
    elig = eligible_entries(db, ch)
    assert [e.trade_score for e in elig] == trade_scores(
        [e.return_bp for e in elig], [True] * len(elig)
    )
    assert all(e.trade_score == 0 for e in entries if not e.eligible)
    ranks = competition_ranks([e.total_score for e in elig])
    assert sorted(e.rank for e in elig) == sorted(ranks)
    assert all(e.rank is None for e in entries if not e.eligible)
    assert any(e.trade_count and e.trade_count > 0 for e in elig)


def test_day_board_standard_ranking_and_me_outside_page(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    ch, rows = settled_challenge(
        db, fake_clock, make_user, challenge_play, eligible=5, ineligible=2
    )
    board = boards.day_board(db, ch, board="total", limit=100, cursor=None, viewer_id=None)
    items = board["items"]
    assert board["scope"] == "day" and board["key"] == DAY.isoformat()
    assert len(items) == 5 and board["eligible_count"] == 5
    scores = [it["total_score"] for it in items]
    assert scores == sorted(scores, reverse=True)
    for it in items:
        greater = sum(1 for s in scores if s > it["total_score"])
        assert it["rank"] == 1 + greater
    assert all(it["username"].startswith("ok") for it in items)

    viewer = next(e.user_id for e in eligible_entries(db, ch) if e.total_score == scores[-1])
    page = boards.day_board(db, ch, board="total", limit=2, cursor=None, viewer_id=viewer)
    assert len(page["items"]) == 2 and page["next_cursor"] is not None
    assert page["me"] is not None and page["me"]["is_me"] is True
    assert page["me"]["rank"] == items[-1]["rank"]
    rest = boards.day_board(
        db, ch, board="total", limit=2, cursor=page["next_cursor"], viewer_id=None
    )
    assert [it["username"] for it in page["items"] + rest["items"][:1]] == [
        it["username"] for it in items[:3]
    ]
    ineligible = boards.day_board(
        db, ch, board="total", limit=100, cursor=None, viewer_id=rows[-1].user_id
    )
    assert ineligible["me"] is None  # 不合格者不上榜


@pytest.mark.parametrize("board_name", ["forecast", "trade"])
def test_day_board_other_boards_sort_by_their_score(
    challenge_app, db, fake_clock, make_user, challenge_play, board_name
):
    ch, _ = settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=0)
    field = f"{board_name}_score"
    board = boards.day_board(db, ch, board=board_name, limit=100, cursor=None, viewer_id=None)
    values = [it[f"{board_name}_score"] for it in board["items"]]
    assert values == sorted(values, reverse=True)
    stored = sorted(getattr(e, field) for e in eligible_entries(db, ch))
    assert sorted(values) == stored


def test_day_board_before_settlement_is_409(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    ch = generate.ensure_challenge(db, DAY, now=CHALLENGE_NOW)
    fake_clock.value = aware(ch.starts_at)
    with pytest.raises(AppError) as exc:
        boards.day_board(db, ch, board="total", limit=50, cursor=None, viewer_id=None)
    assert exc.value.code == ErrorCode.CHALLENGE_NOT_SETTLED


def test_period_boards_sum_days_and_me(challenge_app, db, fake_clock, make_user, challenge_play):
    ch, _ = settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=2)
    week = iso_week_key(DAY)
    entries = eligible_entries(db, ch)
    viewer = entries[0].user_id
    board = boards.period_board(
        db,
        scope="week",
        week=week,
        sort="sum",
        limit=100,
        cursor=None,
        viewer_id=viewer,
        now=fake_clock.value,
    )
    assert board["key"] == week and board["scope"] == "week"
    totals = {e.user_id: e.total_score for e in entries}
    assert sorted(it["total_score"] for it in board["items"]) == sorted(totals.values())
    assert all(it["days_played"] == 1 for it in board["items"])
    assert all(it["return_bp"] is None for it in board["items"])
    assert board["me"] is not None and board["me"]["is_me"] is True
    assert board["me"]["total_score"] == totals[viewer]

    total = boards.period_board(
        db,
        scope="all",
        week=None,
        sort="sum",
        limit=100,
        cursor=None,
        viewer_id=None,
        now=fake_clock.value,
    )
    assert total["key"] == "all"
    assert sorted(it["total_score"] for it in total["items"]) == sorted(totals.values())


def test_period_avg_requires_five_days(challenge_app, db, fake_clock, make_user, challenge_play):
    settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=0)
    avg = boards.period_board(
        db,
        scope="all",
        week=None,
        sort="avg",
        limit=100,
        cursor=None,
        viewer_id=None,
        now=fake_clock.value,
    )
    assert avg["items"] == []  # 只打了 1 天，不满 5 天不进平均榜


def test_period_week_outside_range_is_excluded(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=0)
    other = boards.period_board(
        db,
        scope="week",
        week="2026-W01",
        sort="sum",
        limit=100,
        cursor=None,
        viewer_id=None,
        now=fake_clock.value,
    )
    assert other["items"] == []


def test_invalid_week_and_cursor_are_422(challenge_app, db, fake_clock):
    with pytest.raises(AppError) as exc:
        boards.period_board(
            db,
            scope="week",
            week="2026-W99",
            sort="sum",
            limit=10,
            cursor=None,
            viewer_id=None,
            now=fake_clock.value,
        )
    assert exc.value.code == ErrorCode.VALIDATION_ERROR and exc.value.params["field"] == "week"
    with pytest.raises(AppError) as exc:
        boards.period_board(
            db,
            scope="all",
            week=None,
            sort="sum",
            limit=10,
            cursor="!!!",
            viewer_id=None,
            now=fake_clock.value,
        )
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_ledger_rewards_match_reward_table(
    challenge_app, db, fake_clock, make_user, challenge_play
):
    from stocksim.domain.challenge.ranking import reward_points

    ch, _ = settled_challenge(db, fake_clock, make_user, challenge_play, eligible=5, ineligible=2)
    for e in all_entries(db, ch):
        if not e.eligible:
            assert e.points_awarded == 0
            continue
        expected = reward_points(e.rank, ch.eligible_count)
        assert e.points_awarded == expected
        rows = db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.idempotency_key == f"challenge:{ch.id}:{e.user_id}"
            )
        ).all()
        if expected > 0:
            assert len(rows) == 1 and rows[0].delta == expected and rows[0].reason == "challenge"
        else:
            assert rows == []
