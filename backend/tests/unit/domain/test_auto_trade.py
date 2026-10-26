"""自动交易：条件、tick 冷却、全局上限只计成功、复用 matching.execute_order。"""

from stocksim.domain import matching
from stocksim.domain.auto_trade import executor
from stocksim.domain.auto_trade.conditions import AutoTradeConfig, should_trigger
from stocksim.domain.auto_trade.executor import AutoRuntime, run_auto_trades
from stocksim.domain.types import Account, Holding, Quote, TradeSettings

CODE = "600036"
TEN = 600
SET = TradeSettings()
T0 = TradeSettings(t0_mode=True)


def q(price=1000, prev=1000):
    return {CODE: Quote(CODE, "招商银行", "银行", price, prev)}


def cfg(**kw):
    base = dict(
        id="c1",
        code=CODE,
        name="招商银行",
        direction="buy",
        condition_type="price",
        condition_operator="above",
        condition_value_cents=990,
        quantity=100,
    )
    base.update(kw)
    return AutoTradeConfig(**base)


def run(
    configs,
    *,
    tick=0,
    quotes=None,
    acct=None,
    runtime=None,
    trades=(),
    settings=SET,
    minute=TEN,
    max_total=100,
):
    return run_auto_trades(
        configs,
        runtime or AutoRuntime(),
        tick=tick,
        trading_day=2,
        minute_of_day=minute,
        quotes=quotes if quotes is not None else q(),
        account=acct or Account(10_000_000),
        settings=settings,
        trades=list(trades),
        max_total_trades=max_total,
    )


def test_reuses_matching_execute_order():
    assert executor.execute_order is matching.execute_order


def test_price_condition_triggers_buy_and_records_auto_source():
    res = run([cfg()])
    assert len(res.events) == 1 and res.events[0].success
    assert res.new_trades[0]["source"] == "auto"
    assert res.account.holdings[CODE].quantity == 100
    assert res.runtime.total_success == 1 and res.runtime.trade_counts == {f"{CODE}-buy": 1}


def test_price_condition_not_met_does_nothing():
    res = run([cfg(condition_value_cents=1100)])
    assert res.events == () and res.new_trades == ()


def test_equal_operator_exact_cent():
    assert should_trigger(
        cfg(condition_operator="equal", condition_value_cents=1000), q()[CODE], None
    )
    assert not should_trigger(
        cfg(condition_operator="equal", condition_value_cents=1001), q()[CODE], None
    )


def test_percentage_condition_uses_basis_points():
    # 现价 1050，昨收 1000：涨幅 5% = 500 bp
    quote = q(price=1050, prev=1000)[CODE]
    above = cfg(condition_type="percentage", condition_operator="above", condition_value_bp=490)
    below = cfg(condition_type="percentage", condition_operator="below", condition_value_bp=490)
    assert should_trigger(above, quote, None)
    assert not should_trigger(below, quote, None)


def test_cooldown_is_two_ticks_for_price_and_ten_for_time():
    runtime = AutoRuntime()
    first = run([cfg(condition_value_cents=900)], tick=0, runtime=runtime)
    assert first.events[0].success
    blocked = run(
        [cfg(condition_value_cents=900)],
        tick=1,
        runtime=first.runtime,
        acct=first.account,
        trades=first.new_trades,
    )
    assert blocked.events == ()
    ok = run(
        [cfg(condition_value_cents=900)],
        tick=2,
        runtime=blocked.runtime,
        acct=blocked.account,
        trades=first.new_trades,
    )
    assert len(ok.events) == 1

    t = cfg(id="t", condition_type="time", condition_operator=None, condition_value_cents=0)
    r0 = run([t], tick=0)
    assert run([t], tick=9, runtime=r0.runtime, acct=r0.account, trades=r0.new_trades).events == ()
    assert (
        len(run([t], tick=10, runtime=r0.runtime, acct=r0.account, trades=r0.new_trades).events)
        == 1
    )


def test_stop_loss_and_take_profit_sell_positions():
    acct = Account(0, {CODE: Holding(CODE, "招商银行", 100, 100_000)})  # 均价 1000
    sl = cfg(
        id="sl",
        direction="sell",
        condition_type="price",
        condition_operator="above",
        condition_value_cents=10**9,
        stop_loss_cents=5_000,
    )
    # 现价 9.00：浮亏 -1000 元 <= -50 元 -> 止损卖出
    res = run([sl], quotes=q(price=900, prev=1000), acct=acct, settings=T0)
    assert res.events[0].success and res.events[0].reason is None
    tp = cfg(
        id="tp",
        direction="sell",
        condition_type="price",
        condition_operator="above",
        condition_value_cents=10**9,
        take_profit_cents=10_000,
    )
    # 现价 12.00：浮盈 2000 元 >= 100 元 -> 止盈
    res = run([tp], quotes=q(price=1200, prev=1000), acct=acct, settings=T0)
    assert res.events[0].success
    assert res.events[0].pnl_cents == (1200 - 1000) * 100 - 156


def test_profit_condition_in_cents():
    acct = Account(0, {CODE: Holding(CODE, "招商银行", 100, 100_000)})
    c = cfg(
        id="p",
        direction="sell",
        condition_type="profit",
        condition_operator="above",
        condition_value_cents=1_000_00,
    )
    assert not should_trigger(c, q(price=1050)[CODE], acct.holdings[CODE])  # 浮盈 50 元
    assert should_trigger(c, q(price=2000)[CODE], acct.holdings[CODE])  # 浮盈 1000 元


def test_limit_order_not_reached_is_failed_event_not_counted():
    res = run([cfg(price_type="limit", limit_price_cents=950)])
    ev = res.events[0]
    assert not ev.success and ev.reason == "ORDER_LIMIT_NOT_REACHED"
    assert res.runtime.total_success == 0 and res.account.fund_cents == 10_000_000


def test_failed_attempts_do_not_count_toward_global_limit():
    # 资金不足的失败不计入全局上限；随后的成功仍然成交（max_total=1）
    poor = run([cfg(quantity=100)], acct=Account(100))
    assert not poor.events[0].success and poor.runtime.total_success == 0
    rich = run([cfg()], runtime=poor.runtime, acct=Account(10_000_000), tick=5, max_total=1)
    assert rich.events[0].success and rich.runtime.total_success == 1


def test_global_limit_notifies_once():
    base = AutoRuntime(total_success=3)
    first = run([cfg()], runtime=base, max_total=3)
    assert not first.events[0].success
    assert first.events[0].reason == "AUTO_LIMIT_REACHED"
    assert first.events[0].params["notify"] is True
    assert first.runtime.limit_notified
    second = run([cfg()], runtime=first.runtime, max_total=3, tick=9)
    assert second.events[0].params["notify"] is False


def test_per_config_max_trades():
    c = cfg(max_trades=1)
    r = run([c])
    assert r.events[0].success
    r2 = run([c], runtime=r.runtime, acct=r.account, trades=r.new_trades, tick=5)
    assert r2.events[0].reason == "AUTO_LIMIT_REACHED" and r2.events[0].params["scope"] == "config"


def test_max_amount_limit():
    r = run([cfg(max_amount_cents=50_000)])
    assert r.events[0].reason == "AUTO_MAX_AMOUNT_EXCEEDED"


def test_auto_sell_respects_t1():
    acct = Account(0, {CODE: Holding(CODE, "招商银行", 100, 100_000)})
    today_buy = {"code": CODE, "side": "buy", "quantity": 100, "trading_day": 2}
    sell = cfg(id="s", direction="sell", condition_type="time", condition_operator=None)
    blocked = run([sell], acct=acct, trades=[today_buy])
    assert blocked.events[0].reason == "TRADE_T1_SELL_BLOCKED"
    allowed = run([sell], acct=acct, trades=[today_buy], settings=T0)
    assert allowed.events[0].success


def test_market_closed_returns_unchanged():
    r = run([cfg()], minute=0)
    assert r.events == () and r.account.fund_cents == 10_000_000 and r.runtime.total_success == 0


def test_missing_quote_is_skipped_silently():
    r = run([cfg()], quotes={})
    assert r.events == ()


def test_v2_auto_trade_idle_at_close_and_lunch_but_runs_inside_window():
    v2 = TradeSettings(clock_rules=2)
    assert run([cfg()], minute=690, settings=v2).events == ()
    assert run([cfg()], minute=900, settings=v2).events == ()
    assert run([cfg()], minute=899, settings=v2).account.fund_cents < 10_000_000
