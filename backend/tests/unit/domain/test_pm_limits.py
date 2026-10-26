"""预测市场下单限额（04 §5.5）：每条规则的边界值（等于上限通过，超过即拒绝）。

卖出不受投入上限约束。
"""

import pytest

from stocksim.domain.errors import VALIDATION_ERROR, DomainError
from stocksim.domain.prediction_market import check_trade, market_cap_points
from stocksim.domain.prediction_market.limits import (
    PM_DAILY_LIMIT,
    PM_INSUFFICIENT_SHARES,
    PM_POSITION_LIMIT,
    PM_TRADE_TOO_SMALL,
)
from stocksim.domain.prediction_market.types import LimitState


def _state(**kw) -> LimitState:
    base = dict(
        subsidy_points=1000,
        market_net_cost_points=0,
        challenge_buy_points=0,
        held_shares=0,
    )
    base.update(kw)
    return LimitState(**base)


def _code(**kw) -> str | None:
    try:
        check_trade(**kw)
    except DomainError as e:
        return e.code
    return None


def test_market_cap_is_max_200_and_quarter_subsidy():
    assert market_cap_points(1000) == 250
    assert market_cap_points(2000) == 500
    assert market_cap_points(4000) == 1000
    assert market_cap_points(400) == 200  # max(200, 100)
    assert market_cap_points(0) == 200


@pytest.mark.parametrize("subsidy,cap", [(1000, 250), (4000, 1000)])
def test_position_cap_boundary(subsidy, cap):
    # 等于上限通过，超过 1 拒绝
    ok = _state(subsidy_points=subsidy, market_net_cost_points=cap - 10)
    assert _code(side="buy", shares=5, amount_points=10, state=ok) is None
    over = _state(subsidy_points=subsidy, market_net_cost_points=cap - 10)
    assert _code(side="buy", shares=5, amount_points=11, state=over) == PM_POSITION_LIMIT


def test_position_cap_error_params():
    with pytest.raises(DomainError) as e:
        check_trade(
            side="buy",
            shares=3,
            amount_points=50,
            state=_state(subsidy_points=1000, market_net_cost_points=230),
        )
    assert e.value.code == PM_POSITION_LIMIT
    assert e.value.params == {"limit_points": 250, "used_points": 230}


def test_net_cost_may_be_negative_after_profitable_sells():
    # 净投入为负（卖出回款超过买入花费）时，上限空间扩大
    st = _state(subsidy_points=1000, market_net_cost_points=-100)
    assert _code(side="buy", shares=5, amount_points=349, state=st) is None  # 净 249 ≤ 250
    assert _code(side="buy", shares=5, amount_points=351, state=st) == PM_POSITION_LIMIT  # 净 251


def test_challenge_daily_cap_boundary():
    ok = _state(challenge_buy_points=2_900, subsidy_points=4000)
    assert _code(side="buy", shares=1, amount_points=100, state=ok) is None  # 恰为 3000
    over = _state(challenge_buy_points=2_900, subsidy_points=4000)
    assert _code(side="buy", shares=1, amount_points=101, state=over) == PM_DAILY_LIMIT


def test_both_caps_checked_position_first():
    st = _state(subsidy_points=1000, market_net_cost_points=240, challenge_buy_points=2999)
    assert _code(side="buy", shares=1, amount_points=20, state=st) == PM_POSITION_LIMIT


def test_sell_is_not_limited_by_buy_caps():
    st = _state(
        subsidy_points=1000,
        market_net_cost_points=10_000,
        challenge_buy_points=99_999,
        held_shares=50,
    )
    assert _code(side="sell", shares=50, amount_points=10_000, state=st) is None


def test_shares_range_boundaries():
    st = _state(held_shares=500, subsidy_points=4000)
    assert _code(side="buy", shares=1, amount_points=1, state=st) is None
    assert _code(side="buy", shares=200, amount_points=1, state=st) is None
    with pytest.raises(DomainError) as e:
        check_trade(side="buy", shares=201, amount_points=1, state=st)
    assert e.value.code == VALIDATION_ERROR
    with pytest.raises(DomainError) as e:
        check_trade(side="sell", shares=0, amount_points=1, state=st)
    assert e.value.code == VALIDATION_ERROR


def test_sell_cannot_exceed_holdings():
    st = _state(held_shares=7)
    assert _code(side="sell", shares=7, amount_points=5, state=st) is None
    with pytest.raises(DomainError) as e:
        check_trade(side="sell", shares=8, amount_points=5, state=st)
    assert e.value.code == PM_INSUFFICIENT_SHARES
    assert e.value.params == {"held": 7, "requested": 8}


def test_zero_proceeds_rejected():
    st = _state(held_shares=3)
    with pytest.raises(DomainError) as e:
        check_trade(side="sell", shares=1, amount_points=0, state=st)
    assert e.value.code == PM_TRADE_TOO_SMALL


def test_unknown_side_rejected():
    with pytest.raises(DomainError) as e:
        check_trade(side="hold", shares=1, amount_points=1, state=_state())
    assert e.value.code == VALIDATION_ERROR


def test_negative_subsidy_rejected():
    with pytest.raises(ValueError):
        market_cap_points(-1)
