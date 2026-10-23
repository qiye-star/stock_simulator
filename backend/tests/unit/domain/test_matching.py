"""撮合：手续费、限价单修复、T+1、资金与持仓、成交记录快照。"""

from decimal import Decimal

import pytest

from stocksim.domain.errors import (
    MARKET_CLOSED,
    ORDER_LIMIT_NOT_REACHED,
    STOCK_NOT_FOUND,
    TRADE_CIRCUIT_BREAKER_ACTIVE,
    TRADE_INSUFFICIENT_FUNDS,
    TRADE_INSUFFICIENT_HOLDINGS,
    TRADE_PRICE_DEVIATION_CONFIRM,
    TRADE_PRICE_DEVIATION_EXCEEDED,
    TRADE_PRICE_OUT_OF_LIMIT,
    TRADE_T1_BUY_BLOCKED,
    TRADE_T1_SELL_BLOCKED,
    VALIDATION_ERROR,
    DomainError,
)
from stocksim.domain.matching import execute_order
from stocksim.domain.types import Account, Holding, OrderRequest, Quote, TradeSettings

DAY = 5
TEN = 600  # 10:00
SET = TradeSettings()  # 买 0.03%，卖 0.13%，T+1
T0 = TradeSettings(t0_mode=True)


def quote(price=1000, prev=1000, code="600036", breaker=False):
    return Quote(
        code=code,
        name="招商银行",
        industry="银行",
        price_cents=price,
        prev_close_cents=prev,
        circuit_breaker_active=breaker,
    )


def run(req, *, acct=None, q=None, settings=SET, trades=(), minute=TEN, day=DAY):
    return execute_order(
        req,
        account=acct or Account(10_000_000),
        quote=q or quote(),
        settings=settings,
        trades=list(trades),
        trading_day=day,
        minute_of_day=minute,
    )


def buy(qty=100, **kw):
    return OrderRequest(code="600036", side="buy", quantity=qty, **kw)


def sell(qty=100, **kw):
    return OrderRequest(code="600036", side="sell", quantity=qty, **kw)


def holding(qty, total_cost):
    return Holding(code="600036", name="招商银行", quantity=qty, total_cost_cents=total_cost)


def err(fn, *a, **k):
    with pytest.raises(DomainError) as exc:
        fn(*a, **k)
    return exc.value


# --- 基本买卖与费用 -------------------------------------------------------


def test_market_buy_fee_and_cash():
    r = run(buy(100))
    assert r.fill_price_cents == 1000
    assert r.amount_cents == 100_000
    assert r.fee_cents == 30  # 10 万 * 0.03%
    assert r.account.fund_cents == 10_000_000 - 100_030
    assert r.account.holdings["600036"].quantity == 100
    assert r.account.holdings["600036"].total_cost_cents == 100_030
    assert r.trade["cash_cents"] == -100_030 and r.trade["pnl_cents"] == 0


def test_avg_cost_uses_total_cost_cents():
    first = run(buy(100))
    second = run(
        buy(
            100,
        ),
        acct=first.account,
        q=quote(price=1200, prev=1200),
    )
    h = second.account.holdings["600036"]
    assert h.quantity == 200
    assert h.total_cost_cents == 100_030 + (120_000 + 36)  # 手续费 0.03% * 12 万 = 36
    assert h.avg_cost_cents == 1100  # 220066 / 200 = 1100.33 -> 1100


def test_sell_pnl_includes_sell_fee_and_avg_cost():
    acct = Account(10_000_000, {"600036": holding(100, 100_030)})
    r = run(sell(100), acct=acct, q=quote(price=1200, prev=1000), settings=T0)
    assert r.fill_price_cents == 1200
    assert r.fee_cents == 156  # 12 万 * 0.13%
    assert r.pnl_cents == (1200 - 1000) * 100 - 156  # avg = 1000
    assert r.account.fund_cents == 10_000_000 + 120_000 - 156
    assert "600036" not in r.account.holdings  # 清仓


def test_fee_rounds_separately_half_up():
    # 金额 10 分 * 费率 5% = 0.5 分 -> 1 分（half up）
    settings = TradeSettings(buy_fee_rate=Decimal("0.05"))
    r = execute_order(
        OrderRequest("600036", "buy", 10),
        account=Account(10_000),
        quote=quote(price=1, prev=1),
        settings=settings,
        trades=[],
        trading_day=0,
        minute_of_day=TEN,
    )
    assert r.amount_cents == 10 and r.fee_cents == 1
    # 金额 10 分 * 费率 4% = 0.4 分 -> 0 分
    settings = TradeSettings(buy_fee_rate=Decimal("0.04"))
    r = execute_order(
        OrderRequest("600036", "buy", 10),
        account=Account(10_000),
        quote=quote(price=1, prev=1),
        settings=settings,
        trades=[],
        trading_day=0,
        minute_of_day=TEN,
    )
    assert r.fee_cents == 0


def test_insufficient_funds_and_holdings():
    e = err(run, buy(100), acct=Account(100))
    assert e.code == TRADE_INSUFFICIENT_FUNDS and e.params["available_cents"] == 100
    e = err(run, sell(100), acct=Account(0))
    assert e.code == TRADE_INSUFFICIENT_HOLDINGS and e.params == {"held": 0, "requested": 100}


def test_invalid_quantity_and_unit():
    e = err(run, buy(50), settings=TradeSettings(trade_unit=100))
    assert e.code == "TRADE_INVALID_QUANTITY"
    assert err(run, buy(0)).code == "TRADE_INVALID_QUANTITY"


def test_market_closed_and_stock_mismatch_and_breaker():
    assert err(run, buy(100), minute=0).code == MARKET_CLOSED
    assert err(run, OrderRequest("000001", "buy", 100)).code == STOCK_NOT_FOUND
    assert err(run, buy(100), q=quote(breaker=True)).code == TRADE_CIRCUIT_BREAKER_ACTIVE


# --- 限价单（修复后的规则） -------------------------------------------------


def test_limit_buy_crossing_fills_at_market_price():
    r = run(buy(100, price_type="limit", limit_price_cents=1050))
    assert r.fill_price_cents == 1000  # 限价 >= 市价：按市价成交
    assert r.trade["price_cents"] == 1000 and r.trade["price_type"] == "limit"
    assert r.account.holdings["600036"].avg_cost_cents == 1000


def test_limit_buy_not_crossing_is_rejected():
    e = err(run, buy(100, price_type="limit", limit_price_cents=990))
    assert e.code == ORDER_LIMIT_NOT_REACHED


def test_limit_sell_crossing_fills_at_market_and_not_crossing_rejected():
    acct = Account(0, {"600036": holding(100, 100_000)})
    r = run(sell(100, price_type="limit", limit_price_cents=950), acct=acct, settings=T0)
    assert r.fill_price_cents == 1000
    e = err(run, sell(100, price_type="limit", limit_price_cents=1010), acct=acct, settings=T0)
    assert e.code == ORDER_LIMIT_NOT_REACHED


def test_limit_must_be_within_daily_limits_on_both_sides():
    assert (
        err(run, buy(100, price_type="limit", limit_price_cents=1101)).code
        == TRADE_PRICE_OUT_OF_LIMIT
    )
    acct = Account(0, {"600036": holding(100, 100_000)})
    assert (
        err(run, sell(100, price_type="limit", limit_price_cents=899), acct=acct, settings=T0).code
        == TRADE_PRICE_OUT_OF_LIMIT
    )


def test_limit_price_deviation_thresholds():
    q = quote(price=900, prev=1000)  # 市价 9.00
    # 限价 10.80：偏离 20%（恰好），不超过硬阻断，但超过 10% 需确认
    assert (
        err(run, buy(100, price_type="limit", limit_price_cents=1080), q=q).code
        == TRADE_PRICE_DEVIATION_CONFIRM
    )
    r = run(buy(100, price_type="limit", limit_price_cents=1080, confirm_deviation=True), q=q)
    assert r.fill_price_cents == 900
    # 限价 11.00：偏离 >20%，硬阻断
    e = err(run, buy(100, price_type="limit", limit_price_cents=1100, confirm_deviation=True), q=q)
    assert e.code == TRADE_PRICE_DEVIATION_EXCEEDED


def test_limit_price_validation():
    assert err(run, buy(100, price_type="limit", limit_price_cents=None)).code == VALIDATION_ERROR
    assert err(run, buy(100, price_type="limit", limit_price_cents=0)).code == VALIDATION_ERROR


# --- T+1 ------------------------------------------------------------------

TODAY_BUY = {"code": "600036", "side": "buy", "quantity": 100, "trading_day": DAY}
YESTERDAY_BUY = {"code": "600036", "side": "buy", "quantity": 100, "trading_day": DAY - 1}


def test_t1_blocks_selling_shares_bought_today():
    acct = Account(0, {"600036": holding(150, 150_000)})
    e = err(run, sell(100), acct=acct, trades=[TODAY_BUY])
    assert e.code == TRADE_T1_SELL_BLOCKED and e.params == {"bought": 100, "available": 50}
    assert run(sell(50), acct=acct, trades=[TODAY_BUY]).account.holdings["600036"].quantity == 100


def test_t1_allows_selling_yesterdays_shares():
    acct = Account(0, {"600036": holding(100, 100_000)})
    assert run(sell(100), acct=acct, trades=[YESTERDAY_BUY]).trade["quantity"] == 100


def test_t0_mode_ignores_t1():
    acct = Account(0, {"600036": holding(100, 100_000)})
    assert run(sell(100), acct=acct, trades=[TODAY_BUY], settings=T0).trade["quantity"] == 100


def test_t1_buy_blocked_after_same_day_sell():
    today_sell = {"code": "600036", "side": "sell", "quantity": 10, "trading_day": DAY}
    e = err(run, buy(100), trades=[today_sell])
    assert e.code == TRADE_T1_BUY_BLOCKED
    assert run(buy(100), trades=[today_sell], settings=T0).trade["quantity"] == 100


# --- 快照与纯度 ---------------------------------------------------------------


def test_trade_record_captures_trade_time_snapshots():
    acct = Account(10_000_000)
    r = run(buy(100), acct=acct, q=quote(price=1020, prev=1000))
    t = r.trade
    assert t["prev_close_cents"] == 1000 and t["fund_before_cents"] == 10_000_000
    assert t["trading_day"] == DAY and t["minute_of_day"] == TEN and t["source"] == "manual"
    assert t["industry"] == "银行"


def test_execute_order_does_not_mutate_inputs():
    acct = Account(10_000_000, {"600036": holding(100, 100_030)})
    trades = [YESTERDAY_BUY]
    run(sell(50), acct=acct, trades=trades, settings=T0)
    assert acct.fund_cents == 10_000_000 and acct.holdings["600036"].quantity == 100
    assert trades == [YESTERDAY_BUY]


def test_insufficient_funds_uses_fee_inclusive_total():
    # 金额 10 万 + 手续费 30 分 > 余额 10 万
    e = err(run, buy(100), acct=Account(100_000))
    assert e.code == TRADE_INSUFFICIENT_FUNDS and e.params["required_cents"] == 100_030
