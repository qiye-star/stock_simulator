"""预测市场全部可调常量（04 §4–§5；§14 未决问题采用建议值，见修订说明）。调参只改这里。

单位：积分为整数；份额为整数；b 以 milli（×1000）存整数 `b_milli`；价格为 ppm（1e6 = 100%）。
"""

from __future__ import annotations

from typing import Final

PRICE_PPM_TOTAL: Final = 1_000_000  # 概率 100% 的 ppm 表示；prices_ppm 之和恒等于它

# ---------------------------------------------------------------- 份额与兑付（04 §4.3）
POINTS_PER_SHARE: Final = 100  # C(q) 的积分换算：100 积分对应“1 份”的做市商成本单位
SHARE_PAYOUT_POINTS: Final = 100  # 每份获胜份额兑付 100 积分
MAX_SHARES_PER_TRADE: Final = 200  # 单笔份额上限 1..200
# 取整前先把花费/回款量化到 1e-12 积分，消除 prec=50 的尾差（如全套花费理论上是整数）
COST_SNAP_EXP: Final = -12

# ---------------------------------------------------------------- 补贴与 b（04 §4.4）
# (expected_participants 下界, 补贴 S 积分)：N<30 → 1000，30≤N<150 → 2000，N≥150 → 4000
SUBSIDY_TIERS: Final = ((0, 1_000), (30, 2_000), (150, 4_000))
B_SHRINK_MAX_ITERS: Final = 20  # 最大亏损超过 S 时 b 的收缩次数上限
B_SHRINK_DIVISOR: Final = 200  # 每次收缩 b -= max(1, b // 200)

# ---------------------------------------------------------------- 限额（04 §5.5）
MARKET_NET_COST_CAP_MIN: Final = 200  # 单市场净投入上限 max(200, S // 4)
CHALLENGE_BUY_CAP_POINTS: Final = 3_000  # 单场挑战累计买入上限（“每日额度”）
RATE_LIMIT_TRADES: Final = 12  # 每用户每 60 秒成交笔数上限（跨市场；服务层计数）
RATE_LIMIT_WINDOW_S: Final = 60
MAX_MARKETS_PER_CHALLENGE: Final = 8  # 每场挑战市场数上限（按 (首次出现 tick, id, kind) 截断）

# ---------------------------------------------------------------- 合约时点（04 §3.2、§3.3）
# bucket 合约最短开盘时长（tick）：v1 10；v2 约 N/8 = 30
MIN_OPEN_TICKS: Final = {1: 10, 2: 30}
# rumor 合约在揭晓（或挑战末）前提前停止交易的 tick 数：v1 1；v2 = round(242/20) = 12
RUMOR_CLOSE_LEAD_TICKS: Final = {1: 1, 2: 12}

# ---------------------------------------------------------------- 开盘先验（04 §4.5）
# 传闻：(deny, confirm)，00 决策 5：约三成传闻被辟谣
RUMOR_PRIOR_PPM: Final = (300_000, 700_000)
# 分档先验按 (scope, sentiment) 分组（sentiment ∈ {-1, +1}，事件生成器的取值），由
# scripts/pm_prior_report.py --seeds 20 --days 120 离线统计（v2，3298 个已结算重大事件）。
# 每组 5 档之和 = 1e6，每档 ≥ PRIOR_FLOOR_PPM。`pm_prior_report.py --check` 校验一致。
PRIOR_FLOOR_PPM: Final = 100_000
BUCKET_PRIOR_PPM: Final[dict[tuple[str, int], tuple[int, ...]]] = {
    ("industry", -1): (259839, 290322, 236613, 113226, 100000),
    ("industry", 1): (100000, 109559, 255415, 276251, 258775),
    ("stock", -1): (110204, 330612, 318368, 140816, 100000),
    ("stock", 1): (100000, 110850, 356305, 316716, 116129),
    ("market", -1): (397163, 226950, 175887, 100000, 100000),
    ("market", 1): (100000, 100000, 130371, 219259, 450370),
}
