"""涨跌停、熔断、T+1、数量校验（legacy LimitManager 4-104 与 T+1 规则）。"""

import pytest

from stocksim.domain import rules as r
from stocksim.domain.errors import TRADE_INVALID_QUANTITY, VALIDATION_ERROR, DomainError


def test_limit_prices_round_to_cent():
    assert r.limit_up_cents(1000) == 1100
    assert r.limit_down_cents(1000) == 900
    # 10.05 * 1.1 = 11.055 -> 11.06（half up，不是 11.05）
    assert r.limit_up_cents(1005) == 1106
    assert r.limit_down_cents(1005) == 905  # 10.05 * 0.9 = 9.045 -> 9.05


def test_limit_band_checks():
    assert r.is_within_limits(1100, 1000)
    assert r.is_within_limits(900, 1000)
    assert not r.is_within_limits(1101, 1000)
    assert not r.is_within_limits(899, 1000)
    assert r.clamp_to_limits(5000, 1000) == 1100
    assert r.clamp_to_limits(1, 1000) == 900
    assert r.is_limit_up(1100, 1000) and not r.is_limit_up(1099, 1000)
    assert r.is_limit_down(900, 1000) and not r.is_limit_down(901, 1000)


def test_circuit_breaker_threshold_is_per_tick_five_percent():
    assert r.breaker_move_exceeded(950, 1000)  # 5% 恰好触发
    assert not r.breaker_move_exceeded(951, 1000)
    assert not r.breaker_move_exceeded(1000, 0)


def test_circuit_breaker_cooldown_sequence():
    cd = r.tick_circuit_breakers({}, ["A"])
    assert cd == {"A": 2}  # 置位 3 后同 tick 递减（legacy 行为）
    assert r.circuit_breaker_active(cd, "A")
    cd = r.tick_circuit_breakers(cd, [])
    assert cd == {"A": 1}
    cd = r.tick_circuit_breakers(cd, [])
    assert cd == {}
    assert not r.circuit_breaker_active(cd, "A")


def test_validate_quantity_rules():
    r.validate_quantity(100, 100)
    r.validate_quantity(7, 1)
    for bad in (0, -100, 50, 1_000_000_001):
        with pytest.raises(DomainError) as exc:
            r.validate_quantity(bad, 100)
        assert exc.value.code == TRADE_INVALID_QUANTITY
    with pytest.raises(DomainError):
        r.validate_quantity(True, 1)  # type: ignore[arg-type]
    with pytest.raises(DomainError) as exc:
        r.validate_trade_unit(10)
    assert exc.value.code == VALIDATION_ERROR


TRADES = [
    {"code": "A", "side": "buy", "quantity": 100, "trading_day": 3},
    {"code": "A", "side": "buy", "quantity": 50, "trading_day": 2},
    {"code": "B", "side": "buy", "quantity": 80, "trading_day": 3},
    {"code": "A", "side": "sell", "quantity": 20, "trading_day": 3},
]


def test_t1_sellable_quantity_derived_from_trades():
    # 当日买入 100，持仓 150+ -> 当日可卖 = 持仓 - 当日买入
    assert r.bought_quantity(TRADES, "A", 3) == 100
    assert r.sellable_quantity(150, TRADES, "A", 3, t0_mode=False) == 50
    # 昨日买入 50 今日可卖
    assert r.sellable_quantity(150, TRADES, "A", 2, t0_mode=False) == 100
    assert r.sellable_quantity(150, TRADES, "A", 4, t0_mode=False) == 150
    # T+0 模式不受限制
    assert r.sellable_quantity(150, TRADES, "A", 3, t0_mode=True) == 150
    # 不会为负
    assert r.sellable_quantity(10, TRADES, "A", 3, t0_mode=False) == 0


def test_t1_buy_block_after_same_day_sell():
    assert r.t1_buy_blocked(TRADES, "A", 3, t0_mode=False)  # 当日卖出过 A
    assert not r.t1_buy_blocked(TRADES, "A", 4, t0_mode=False)
    assert not r.t1_buy_blocked(TRADES, "A", 3, t0_mode=True)
    assert not r.t1_buy_blocked(TRADES, "B", 3, t0_mode=False)
