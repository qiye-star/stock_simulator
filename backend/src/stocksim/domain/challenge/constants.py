"""每日挑战全部可调常量（03 §4.1、§8、§11.1；06 §4.3 奖励建议值）。调参只改这里。

时钟固定 v2（clock_rules=2）：N_TPD = 242 交易 tick/日。单段快放与 tick 数都按 N_TPD 的倍数定义。
"""

from __future__ import annotations

from decimal import Decimal

from ..clock import CLOCK_RULES_V2, timebase

CHALLENGE_FORMAT_VERSION = 1  # 承诺原文与计分规则版本
CHALLENGE_ROUNDS = 4  # 回合数（回合事件个数）
CHALLENGE_CLOCK_RULES = CLOCK_RULES_V2  # 挑战冻结的时钟规则
N_TPD = timebase(CHALLENGE_CLOCK_RULES).ticks_per_day  # 每交易日 tick 数（v2 = 242）
CHALLENGE_START_MINUTE = 570  # master 开局分钟 9:30（tt = 0，v2 对齐不变量）

CHALLENGE_WARMUP_TT = N_TPD // 2  # 第 1 个回合事件不早于此（先看半个交易日）
CHALLENGE_MIN_ROUND_GAP_TT = N_TPD // 2  # 相邻停顿至少隔半个交易日
CHALLENGE_MAX_BURST_TT = 3 * N_TPD  # 单段快放上限（含最终段），= 方向题窗口 3 日
CHALLENGE_MAX_TT = 8 * N_TPD  # end_tt 上限（约 8 个交易日）
CHALLENGE_SCAN_DAYS = 11  # 剧本筛选扫描的排期日 [0, 11)：⌈MAX_TT/N_TPD⌉ + 前瞻余量
CHALLENGE_SEED_MAX_ATTEMPTS = 64  # 筛选次数上限

CHALLENGE_TICK_MS = 750  # 快放段每交易 tick 的真实毫秒（一个交易日约 3 分钟）
CHALLENGE_CLOSE_LEAD_MS = 5000  # 作答截止早于恢复的提前量（抵消多实例时钟偏差）
CHALLENGE_MAX_REVISIONS = 20  # 每回合作答修改上限
CHALLENGE_MIN_ACCOUNT_AGE_HOURS = 72  # 合格门槛默认值（运行时以 Settings 为准）
CHALLENGE_PEER_MIN = 5  # 同伴分最少合格作答人数，不足退化为基线分

CHALLENGE_INITIAL_FUND_CENTS = 100_000_000  # 统一初始资金 100 万元
CHALLENGE_TRADE_UNIT = 100
CHALLENGE_BUY_FEE_RATE = Decimal("0.0003")
CHALLENGE_SELL_FEE_RATE = Decimal("0.0013")
CHALLENGE_T0_MODE = False
TRADE_POINTS_PER_100BP = 10  # 交易同伴差每 100bp 计 10 分
TRADE_SCORE_CAP = 100  # 交易分封顶 ±100

UTC_OFFSET_MINUTES = 480  # UTC+8（中国无夏令时，不用 zoneinfo）

# 积分奖励（06 §4.3 建议值，替代 03 §8.4 的现值；只在合格且答过 ≥1 回合或有成交时发放）
REWARD_PARTICIPATION = 50
REWARD_TOP_SHARE_MIN_ELIGIBLE = 10  # 前 10% 奖励的最少合格人数
REWARD_TOP_SHARE_PCT = 10  # 名次 ≤ ⌈eligible × 10%⌉
REWARD_TOP_SHARE_POINTS = 100
REWARD_PLACES_MIN_ELIGIBLE = 5  # 前三奖励的最少合格人数
REWARD_PLACE_POINTS = {1: 300, 2: 200, 3: 100}  # 竞赛名次（并列同奖）

# 承诺与 seed 派生的域分隔前缀（03 §1.4）
SEED_DOMAIN_PREFIX = "stocksim-challenge-seed|v1"
COMMITMENT_PREFIX = "stocksim-challenge|v1"
COMMITMENT_SCHEME = "sha256/stocksim-challenge|v1"
