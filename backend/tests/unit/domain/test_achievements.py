"""成就：目录完整性、统计推导（trade-time 快照）、判定（不重复、隐藏不解锁）。"""

from stocksim.domain.achievements.catalog import (
    CATALOG,
    CATALOG_BY_ID,
    catalog_as_dicts,
    visible_catalog,
)
from stocksim.domain.achievements.evaluator import evaluate
from stocksim.domain.achievements.stats import AchievementStats, compute_stats
from stocksim.domain.types import Holding

INITIAL = 1_000_000_00  # 100 万元
FUND_ZERO = 0


def tr(
    side="buy",
    code="600036",
    qty=100,
    price=1000,
    prev=1000,
    industry="银行",
    day=0,
    minute=600,
    pnl=0,
    fee=0,
    amount=None,
    fund_before=INITIAL,
):
    amt = price * qty if amount is None else amount
    return {
        "code": code,
        "name": code,
        "industry": industry,
        "side": side,
        "price_type": "market",
        "quantity": qty,
        "price_cents": price,
        "amount_cents": amt,
        "fee_cents": fee,
        "cash_cents": 0,
        "pnl_cents": pnl,
        "trading_day": day,
        "minute_of_day": minute,
        "prev_close_cents": prev,
        "fund_before_cents": fund_before,
        "source": "manual",
    }


def stats(trades=(), holdings=None, prices=None, fund=INITIAL, watch=0):
    return compute_stats(
        trades=list(trades),
        holdings=holdings or {},
        prices=prices or {},
        fund_cents=fund,
        initial_fund_cents=INITIAL,
        watchlist_count=watch,
    )


def test_catalog_has_54_unique_ids_and_hidden_have_reasons():
    assert len(CATALOG) == 54 and len(CATALOG_BY_ID) == 54
    hidden = [a for a in CATALOG if a.hidden]
    assert len(hidden) == 15 and len(visible_catalog()) == 39
    assert all(a.hidden_reason for a in hidden)
    assert all(a.stat for a in CATALOG if not a.hidden and a.op == "gte")
    names = {f.name for f in AchievementStats.__dataclass_fields__.values()}
    assert all(a.stat in names for a in CATALOG if a.stat)
    assert len(catalog_as_dicts()) == 54


def test_nothing_unlocks_on_empty_game():
    assert evaluate(stats(), []) == []


def test_first_trade_and_profit_thresholds():
    s = stats([tr()], fund=INITIAL + 1)  # 净赚 1 分
    got = evaluate(s, [])
    assert "first_trade" in got and "first_profit" in got
    assert "profit_1k" not in got


def test_sectors_are_a_set_not_a_count_of_trades():
    same = [tr(industry="银行", day=d) for d in range(10)]
    assert stats(same).sector_count == 1
    diff = [tr(industry=f"行业{i}") for i in range(5)]
    assert stats(diff).sector_count == 5
    assert "all_sectors" in evaluate(stats(diff), [])
    assert "all_sectors" not in evaluate(stats(same), [])


def test_fomo_uses_trade_time_prev_close_snapshot():
    # 成交时昨收 10 元，涨停价 11 元；买入价 11 元 -> FOMO
    s = stats([tr(price=1100, prev=1000)])
    assert s.fomo_trades == 1
    # 同一笔成交的快照不随之后的昨收变化而变化（统计只读快照字段）
    again = stats([tr(price=1100, prev=1000)])
    assert again.fomo_trades == 1
    assert stats([tr(price=1100, prev=1100)]).fomo_trades == 0


def test_panic_seller_at_limit_down():
    s = stats([tr(side="sell", price=900, prev=1000, pnl=-100)])
    assert s.panic_sells == 1


def test_all_in_uses_fund_before_trade_not_current_fund():
    # 买入 90% 资金（含手续费）：金额 90000 分、手续费 27 分，资金前 100000 分
    t = tr(qty=90, price=1000, fee=27, fund_before=100_000)
    assert stats([t], fund=0).all_in_trades == 1
    assert stats([tr(qty=10, price=1000, fee=3, fund_before=100_000)]).all_in_trades == 0


def test_day_trader_same_day_round_trip():
    s = stats([tr(day=3), tr(side="sell", day=3, pnl=10)])
    assert s.day_trades == 1
    assert stats([tr(day=3), tr(side="sell", day=4, pnl=10)]).day_trades == 0


def test_yo_yo_three_trades_same_stock_same_day():
    trades = [tr(day=1), tr(day=1), tr(side="sell", day=1, pnl=5)]
    assert stats(trades).yo_yo_trades == 1
    assert stats([tr(day=1), tr(day=2), tr(day=1)]).yo_yo_trades == 0


def test_max_holdings_replays_trades():
    trades = [tr(code=f"60000{i}") for i in range(5)]
    assert stats(trades).max_holdings == 5
    trades.append(tr(side="sell", code="600000", qty=100, pnl=1))
    assert stats(trades).max_holdings == 5  # 历史峰值保持
    assert (
        stats([tr(code="A"), tr(side="sell", code="A", qty=100, pnl=1), tr(code="B")]).max_holdings
        == 1
    )


def test_profit_streak_counts_consecutive_profitable_sells():
    seq = [1, 1, -1, 1, 1, 1]
    trades = [tr(side="sell", pnl=p) for p in seq]
    assert stats(trades).profit_streak == 3


def test_perfect_game_needs_sells_and_all_profitable():
    assert stats([tr(side="sell", pnl=1), tr(side="sell", pnl=2)]).perfect_game == 1
    assert stats([tr(side="sell", pnl=1), tr(side="sell", pnl=-2)]).perfect_game == 0
    assert stats([tr()]).perfect_game == 0


def test_palindrome_profit_uses_whole_yuan():
    assert stats([tr(side="sell", pnl=122_100)]).palindrome_profit == 1  # 1221 元
    assert stats([tr(side="sell", pnl=123_400)]).palindrome_profit == 0  # 1234 元


def test_early_and_night_windows():
    assert stats([tr(minute=570)]).early_trades == 1
    assert stats([tr(minute=700)]).late_trades == 1
    assert stats([tr(minute=600)]).early_trades == 0


def test_tax_payer_uses_recorded_fees():
    trades = [tr(fee=1_000_000)]
    assert "tax_payer" in evaluate(stats(trades), [])
    assert stats([tr(fee=999_999)]).total_fees_cents == 999_999


def test_maotai_and_large_trade_and_round_number():
    s = stats([tr(code="600519", qty=1000, price=20_000)])  # 20 万元，整数价
    assert s.maotai_bought == 1 and s.large_trades == 1 and s.round_number_trades == 1
    ev = evaluate(s, [])
    assert {"maotai_holder", "large_trade", "round_number"} <= set(ev)


def test_holdings_drive_double_bagger_and_stock_god():
    h = {"600036": Holding("600036", "招商银行", 100, 100_000)}  # 均价 1000
    assert stats(holdings=h, prices={"600036": 2000}).double_bagger_count == 1
    assert stats(holdings=h, prices={"600036": 1999}).double_bagger_count == 0
    assert stats(holdings=h, prices={"600036": 6000}).stock_god == 1
    assert stats(holdings=h, prices={"600036": 5999}).stock_god == 0


def test_return_thresholds_are_basis_points():
    # 资金翻倍 -> 收益率 100%
    s = compute_stats(
        trades=[], holdings={}, prices={}, fund_cents=2 * INITIAL, initial_fund_cents=INITIAL
    )
    assert s.max_return_bp == 10_000
    got = evaluate(s, [])
    assert {"return_10", "return_50", "return_100"} <= set(got)


def test_evaluator_is_idempotent_and_skips_hidden():
    s = stats([tr()], fund=INITIAL + 1)
    first = evaluate(s, [])
    assert evaluate(s, first) == [x for x in evaluate(s, []) if x not in first]
    assert not set(evaluate(s, [])) & {a.id for a in CATALOG if a.hidden}


def test_all_achievements_requires_all_visible_others():
    others = [a.id for a in visible_catalog() if a.id != "all_achievements"]
    assert "all_achievements" not in evaluate(stats(), others[:-1])
    assert "all_achievements" in evaluate(stats(), others)


def test_watchlist_threshold():
    assert "watchlist_10" in evaluate(stats(watch=10), [])
    assert "watchlist_10" not in evaluate(stats(watch=9), [])


def test_hidden_achievement_never_unlocks():
    everything = stats([tr(side="sell", pnl=1) for _ in range(300)], fund=INITIAL * 10)
    got = set(evaluate(everything, []))
    assert not got & {a.id for a in CATALOG if a.hidden}


def test_v2_night_owl_window_is_last_five_minutes_before_close():
    from stocksim.domain.achievements.stats import compute_stats

    def late(minute, rules):
        return compute_stats(
            trades=[
                {
                    "side": "buy",
                    "code": "600036",
                    "quantity": 100,
                    "price_cents": 1000,
                    "amount_cents": 100_000,
                    "fee_cents": 0,
                    "prev_close_cents": 1000,
                    "minute_of_day": minute,
                    "pnl_cents": 0,
                    "fund_before_cents": INITIAL,
                    "trading_day": 0,
                }
            ],
            holdings={},
            prices={},
            fund_cents=INITIAL,
            initial_fund_cents=INITIAL,
            clock_rules=rules,
        ).late_trades

    assert late(899, 2) == 1
    assert late(895, 2) == 1
    assert late(894, 2) == 0
    assert late(700, 2) == 0
    assert late(700, 1) == 1  # v1 夜猫窗口 695–700 保持不变
