"""预测市场 LMSR 纯函数（04 §4、§11.1）：价格和为 1、单调、补贴上界、往返与拆单不套利、金值表。

随机输入一律走 rng.rand_below（测试命名空间 tick = PM_TEST_TICK_BASE − 序号，
不与 domain 占用段冲突）。
金值（b_milli、q0、buy_cost、sell_proceeds、prices_ppm）是跨平台可复现性的契约，不得为过测试而改。
"""

from decimal import Decimal

import pytest

from stocksim.domain.errors import VALIDATION_ERROR, DomainError
from stocksim.domain.prediction_market import (
    b_for_subsidy,
    buy_cost,
    cost_points,
    max_loss_points,
    max_shares_for_budget,
    prices_ppm,
    quote,
    sell_proceeds,
    subsidy_for,
)
from stocksim.domain.rng import rand_below

PM_TEST_TICK_BASE = -(1 << 36)
SEED = 20261026
UNIFORM5 = (200_000,) * 5
RUMOR = (300_000, 700_000)


class Rng:
    """每个测试序列一个 tick，k 递增：确定性、互不相关。"""

    def __init__(self, stream: int) -> None:
        self.tick = PM_TEST_TICK_BASE - stream
        self.k = 0

    def below(self, n: int) -> int:
        v = rand_below(SEED, self.tick, 0, self.k, n)
        self.k += 1
        return v

    def between(self, lo: int, hi: int) -> int:
        return lo + self.below(hi - lo + 1)


def _shift(q, i, d):
    out = list(q)
    out[i] += d
    return out


# ---------------------------------------------------------------- 价格


def test_prices_sum_to_one_on_random_inputs():
    r = Rng(1)
    for _ in range(300):
        n = r.between(2, 5)
        q = [r.between(0, 5000) for _ in range(n)]
        b = r.between(1000, 50_000)
        p = prices_ppm(q, b)
        assert len(p) == n
        assert sum(p) == 1_000_000
        assert all(x >= 0 for x in p)


def test_prices_tie_goes_to_smaller_index():
    # 三个选项对称：1e6 = 3·333333 + 1，余数 1 分给下标 0
    assert prices_ppm((0, 0, 0), 5000) == (333_334, 333_333, 333_333)


def test_prices_monotone_when_buying_up_to_one_ppm():
    """买 i 后 p_i 不降、其余不升；最大余数取整可能让某个尾部选项摆动 1 ppm，因此容差为 1 ppm。"""
    r = Rng(2)
    for _ in range(300):
        n = r.between(2, 5)
        q = [r.between(0, 400) for _ in range(n)]
        b = r.between(1000, 30_000)
        i = r.below(n)
        d = r.between(1, 50)
        before = prices_ppm(q, b)
        after = prices_ppm(_shift(q, i, d), b)
        assert after[i] >= before[i] - 1
        assert all(after[j] <= before[j] + 1 for j in range(n) if j != i)


def test_extreme_gap_does_not_overflow():
    # q 差 1e6 且 b 很小：指数下溢为 0，价格仍和为 1
    p = prices_ppm((0, 1_000_000, 0), 1000)
    assert sum(p) == 1_000_000
    assert p[1] == 1_000_000
    assert buy_cost((0, 1_000_000), 1000, 0, 200) >= 1
    assert sell_proceeds((0, 1_000_000), 1000, 1, 200) > 0


# ---------------------------------------------------------------- 花费与回款的取整


def test_buy_rounds_up_and_sell_rounds_down():
    q = (0, 0, 0, 0, 0)
    exact = cost_points(_shift(q, 0, 1), 6213) - cost_points(q, 6213)  # 精确花费，诊断用
    assert Decimal("21") < exact < Decimal("22")
    assert buy_cost(q, 6213, 0, 1) == 22  # 向上取整
    # 买 1 份后立即卖回：精确回款同为 exact，向下取整得 21
    assert sell_proceeds(_shift(q, 0, 1), 6213, 0, 1) == 21


def test_buy_at_least_one_point():
    # 尾部选项（概率趋于 0）买入的理论花费趋于 0，但最少收 1 积分
    assert buy_cost((0, 10_000), 1000, 0, 1) == 1


def test_sell_can_be_zero():
    # 卖出一份在极度失衡时回款可能为 0，服务层据此拒绝（PM_TRADE_TOO_SMALL）
    assert sell_proceeds((0, 10_000), 1000, 0, 1) == 0


# ---------------------------------------------------------------- 不套利与拆单


def test_roundtrip_never_profits():
    r = Rng(3)
    for _ in range(300):
        n = r.between(2, 5)
        q = [r.between(0, 300) for _ in range(n)]
        b = r.between(1000, 30_000)
        i = r.below(n)
        d = r.between(1, 60)
        c = buy_cost(q, b, i, d)
        y = sell_proceeds(_shift(q, i, d), b, i, d)
        assert y <= c


def test_split_buy_never_cheaper():
    r = Rng(4)
    for _ in range(300):
        n = r.between(2, 5)
        q = [r.between(0, 300) for _ in range(n)]
        b = r.between(1000, 30_000)
        i = r.below(n)
        d = r.between(2, 60)
        a = r.between(1, d - 1)
        whole = buy_cost(q, b, i, d)
        split = buy_cost(q, b, i, a) + buy_cost(_shift(q, i, a), b, i, d - a)
        assert whole <= split


def test_closed_loop_nets_nonpositive():
    """任意买入后按随机顺序全部卖出：交易者合计净收益 ≤ 0（路径无关）。"""
    r = Rng(5)
    for _ in range(100):
        n = r.between(2, 4)
        q = [0] * n
        b = r.between(2000, 20_000)
        held = [0] * n
        cash = 0
        for _ in range(r.between(3, 8)):
            i = r.below(n)
            d = r.between(1, 30)
            cash -= buy_cost(q, b, i, d)
            q = _shift(q, i, d)
            held[i] += d
        while any(held):
            i = r.below(n)
            if held[i] == 0:
                continue
            d = r.between(1, held[i])
            cash += sell_proceeds(q, b, i, d)
            q = _shift(q, i, -d)
            held[i] -= d
        assert cash <= 0


def test_full_set_costs_between_100_and_100_plus_n():
    b, q0 = b_for_subsidy(1000, UNIFORM5)
    q = list(q0)
    total = 0
    for i in range(len(q)):
        total += buy_cost(q, b, i, 1)
        q[i] += 1
    assert 100 <= total <= 100 + len(q)
    assert total == 102  # 04 §4.3：5 档、b=6.213 时为 102


def test_max_shares_for_budget_is_exact():
    r = Rng(6)
    for _ in range(200):
        n = r.between(2, 5)
        q = [r.between(0, 400) for _ in range(n)]
        b = r.between(1000, 30_000)
        i = r.below(n)
        budget = r.between(1, 3000)
        cap = 200
        k = max_shares_for_budget(q, b, i, budget, cap)
        assert 0 <= k <= cap
        if k > 0:
            assert buy_cost(q, b, i, k) <= budget
        if k < cap:
            assert buy_cost(q, b, i, k + 1) > budget


def test_max_shares_zero_budget_and_cap():
    assert max_shares_for_budget((0, 0), 1000, 0, 0, 200) == 0
    assert max_shares_for_budget((0, 0), 1000, 0, 100, 0) == 0


def test_quote_fields():
    q0 = (0, 0, 0, 0, 0)
    qt = quote(q0, 6213, "buy", 0, 1)
    assert qt.points == 22
    assert qt.outcome == 0 and qt.shares == 1 and qt.side == "buy"
    assert qt.price_before_ppm == 200_000
    assert qt.prices_after_ppm[0] == 226_998  # 精确 0.226998…，最大余数取整
    assert qt.avg_price_ppm == 220_000  # 22 积分 / 1 份 = 0.22 = 220000 ppm


# ---------------------------------------------------------------- 补贴上界与 b 选取（04 §4.4）


@pytest.mark.parametrize(
    "subsidy,prior,b_expected,q0_expected",
    [
        (1000, UNIFORM5, 6213, (0, 0, 0, 0, 0)),
        (2000, UNIFORM5, 12426, (0, 0, 0, 0, 0)),
        (4000, UNIFORM5, 24853, (0, 0, 0, 0, 0)),
        (1000, RUMOR, 8305, (0, 7)),
        (2000, RUMOR, 16611, (0, 14)),
        (4000, RUMOR, 33223, (0, 28)),
    ],
)
def test_b_for_subsidy_table(subsidy, prior, b_expected, q0_expected):
    b, q0 = b_for_subsidy(subsidy, prior)
    assert b == b_expected
    assert q0 == q0_expected
    assert min(q0) == 0
    assert max_loss_points(b, q0) <= subsidy


def test_subsidy_tiers():
    assert subsidy_for(0) == 1000
    assert subsidy_for(29) == 1000
    assert subsidy_for(30) == 2000
    assert subsidy_for(149) == 2000
    assert subsidy_for(150) == 4000


def test_b_for_subsidy_rejects_bad_prior():
    with pytest.raises(DomainError) as e:
        b_for_subsidy(1000, (300_000, 600_000))
    assert e.value.code == VALIDATION_ERROR


@pytest.mark.parametrize("subsidy", [1000, 2000, 4000])
@pytest.mark.parametrize("prior", [UNIFORM5, RUMOR])
def test_subsidy_never_exceeded(subsidy, prior):
    """随机成交序列（7 成买、3 成卖，卖不超过持仓）：每一步、每个 i 下，池余额都非负。"""
    b, q0 = b_for_subsidy(subsidy, prior)
    n = len(prior)
    r = Rng(100 + subsidy + prior[0])
    for _ in range(30):
        q = list(q0)
        held = [0] * n
        seq = []
        cash = 0
        worst = None
        for _ in range(25):
            i = r.below(n)
            if r.below(10) < 7 or held[i] == 0:
                d = r.between(1, 40)
                cash += buy_cost(q, b, i, d)
                q[i] += d
                held[i] += d
                seq.append(("buy", i, d))
            else:
                d = r.between(1, held[i])
                proceeds = sell_proceeds(q, b, i, d)
                cash -= proceeds
                q[i] -= d
                held[i] -= d
                seq.append(("sell", i, d))
            for j in range(n):
                pool = subsidy + cash - 100 * (q[j] - q0[j])
                worst = pool if worst is None else min(worst, pool)
        assert worst >= 0


def test_settlement_pool_nonnegative_for_every_winner():
    """结算时对任一获胜选项 w：S + Σ买 − Σ卖 − 100·(q_w − q0_w) ≥ 0。"""
    b, q0 = b_for_subsidy(1000, UNIFORM5)
    r = Rng(200)
    for _ in range(50):
        q = list(q0)
        cash = 0
        for _ in range(20):
            i = r.below(5)
            d = r.between(1, 60)
            cash += buy_cost(q, b, i, d)
            q[i] += d
        for w in range(5):
            assert 1000 + cash - 100 * (q[w] - q0[w]) >= 0


def test_max_loss_bound():
    for subsidy in (1000, 2000, 4000):
        for prior in (UNIFORM5, RUMOR):
            b, q0 = b_for_subsidy(subsidy, prior)
            assert max_loss_points(b, q0) <= subsidy
            assert max_loss_points(b, q0) >= Decimal(subsidy) * Decimal("0.99")


# ---------------------------------------------------------------- 可复现与金值


def test_same_trades_same_result():
    b, q0 = b_for_subsidy(2000, RUMOR)

    def run():
        r = Rng(300)
        q = list(q0)
        ledger = []
        for _ in range(40):
            i = r.below(2)
            d = r.between(1, 25)
            c = buy_cost(q, b, i, d)
            q[i] += d
            ledger.append(c)
        return tuple(q), tuple(ledger), prices_ppm(q, b)

    assert run() == run()


# 金值表：(q, b_milli, i, Δ) → (buy_cost, sell_proceeds_of_same_Δ_after_buy, prices_ppm_after_buy)
# 由同一实现采集（2026-10-26）；跨平台逐位一致是 04 §4.6 的承诺，禁止为过测试而改。
GOLDEN_INPUTS = [
    ((0, 0, 0, 0, 0), 6213, 0, 1),
    ((0, 0, 0, 0, 0), 6213, 2, 5),
    ((0, 0, 0, 0, 0), 6213, 4, 10),
    ((0, 0, 0, 0, 0), 12426, 1, 7),
    ((0, 0, 0, 0, 0), 24853, 3, 20),
    ((0, 7), 8305, 0, 5),
    ((0, 7), 8305, 0, 10),
    ((0, 7), 8305, 1, 3),
    ((0, 14), 16611, 0, 20),
    ((0, 28), 33223, 0, 12),
    ((3, 0, 9, 1, 4), 6213, 1, 6),
    ((10, 25, 5, 0, 40), 6213, 2, 15),
    ((120, 100, 80, 60, 40), 12426, 0, 30),
    ((500, 0), 2000, 1, 50),
    ((0, 1200), 3000, 0, 100),
    ((7, 7, 7), 4000, 2, 8),
    ((0, 0), 1000, 0, 200),
    ((2000, 1000, 0), 9000, 1, 60),
    ((15, 0, 0, 0, 0, 0), 5000, 0, 9),
    ((0, 0, 0, 0, 0, 0, 0, 0), 7000, 6, 2),
]


def test_golden_table():
    """金值：固定 20 组输入的花费、回款与买后价格。"""
    results = []
    for q, b, i, d in GOLDEN_INPUTS:
        c = buy_cost(q, b, i, d)
        after = _shift(q, i, d)
        results.append((c, sell_proceeds(after, b, i, d), prices_ppm(after, b)))
    assert results == GOLDEN_EXPECTED


GOLDEN_EXPECTED = [
    (22, 21, (226998, 193251, 193251, 193250, 193250)),
    (138, 137, (160355, 160355, 358580, 160355, 160355)),
    (366, 365, (111106, 111106, 111105, 111105, 555578)),
    (176, 175, (173716, 305136, 173716, 173716, 173716)),
    (550, 549, (160357, 160357, 160357, 358573, 160356)),
    (185, 184, (440085, 559915)),
    (442, 441, (589338, 410662)),
    (221, 220, (230748, 769252)),
    (884, 883, (589332, 410668)),
    (409, 408, (381876, 618124)),
    (95, 94, (139923, 226774, 367533, 101412, 164358)),
    (21, 20, (7022, 78515, 35112, 1404, 877947)),
    (2751, 2750, (978168, 17494, 3498, 700, 140)),
    (1, 0, (1000000, 0)),
    (1, 0, (0, 1000000)),
    (457, 456, (106507, 106507, 786986)),
    (19931, 19930, (1000000, 0)),
    (1, 0, (1000000, 0, 0)),
    (810, 809, (960478, 7905, 7905, 7904, 7904, 7904)),
    (29, 28, (120038, 120038, 120038, 120038, 120038, 120038, 159735, 120037)),
]
