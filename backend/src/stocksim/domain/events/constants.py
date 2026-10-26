"""事件行情全部常量（01-事件行情.md §4.2 / §5 / §6.2）。调参只改这里。

约定：比例一律 ppm（1e6 = 100%），tick 指“交易 tick”（trading_tick，每个交易日 20 个），
区间写作 (lo, hi) 含两端，抽样用 ``lo + rand_below(..., hi - lo + 1)``。

== RNG 命名空间（与 rng.py / 行情引擎互不碰撞，见 tests/unit/domain/test_events_rng_layout.py）==
现有（不得占用）：
  交易 tick   tick>=1,  idx 0..384,  k 0,1,2,100..119
  init        tick=-1,  idx 0..384,  k 0,1,2..241
  开局分钟     tick=-2,  idx 0,       k 0
事件·日（``tick = EVENT_DAY_TICK_BASE - day``）：
  idx 0..9  = 当日槽位 slot（0-1 重大，2-9 小快讯）
  idx 30    = 重大周期元数据，只在 day = 12p 的 tick 上使用：
              k0 重大条数，k1 第 1 条所在日，k2 第 2 条所在日
  idx 31    = 日元数据：k0 保留不用（不要复用），k1 小快讯条数
  slot 内 k：0 kind，1 模板，2 sentiment(模板 sign=0 时)，3 源，4 M，5 o，6 D，7 H，8 R，9 ρ，10 I，
            11 priced_in，12 P，13 传闻真假，14 揭晓延迟，15 可信度，16 情报提示，
            20..23 源重抽，100..131 文案槽位（第 j 个占位符 k=100+j）
事件·存档参数（``tick = EVENT_SAVE_TICK``）：
  idx 0..384 = stock_idx，k0 = β 抖动；idx 1000+from_idx，k = to_idx = 边系数抖动
"""

from __future__ import annotations

EVENT_RULESET_VERSION = 1

# ---------------------------------------------------------------- RNG 布局
EVENT_DAY_TICK_BASE = -(1 << 32)
EVENT_SAVE_TICK = -(1 << 32) + 4096
PERIOD_META_IDX = 30
DAY_META_IDX = 31
SAVE_EDGE_IDX_BASE = 1000
MAX_SLOT = 9
PICK_K_BASE = 100
MAX_PICKS = 32  # 文案槽位 k=100..131

K_KIND = 0
K_TEMPLATE = 1
K_SENTIMENT = 2
K_SOURCE = 3
K_MAG = 4
K_OFFSET = 5
K_BUILD = 6
K_HOLD = 7
K_RECOVER = 8
K_RETAIN = 9
K_IMPULSE = 10
K_PRICED_IN = 11
K_LEAD = 12
K_RUMOR_TRUTH = 13
K_RUMOR_DELAY = 14
K_RUMOR_CRED = 15
K_RUMOR_HINT = 16
K_SOURCE_REDRAW = 20  # 20..23
SOURCE_REDRAWS = 4

# 以下凡标“参考 tick”的常量按 timing.scale_ticks 换算到规则集的 ticks_per_day
# ---------------------------------------------------------------- 频率（§4.3）
REFERENCE_TICKS_PER_DAY = 20  # tick 常量的定义基准，见 timing.py
MAJOR_PERIOD_REF_TICKS = 240  # 重大事件周期约一个时钟日（参考时钟下 12 个交易日）
MAJOR_COUNT_PCT = (0, 60, 40)  # P(n=0,1,2) 百分比
MINOR_COUNT_MIN = 2
MINOR_COUNT_SPAN = 4  # 2..5 条
MAJOR_SLOTS = (0, 1)
MINOR_SLOT_BASE = 2

KINDS = ("announcement", "news", "policy", "sudden", "rumor")
KIND_WEIGHTS_MAJOR = (
    ("news", 35),
    ("policy", 20),
    ("sudden", 15),
    ("rumor", 15),
    ("announcement", 15),
)
KIND_WEIGHTS_MINOR = (("announcement", 55), ("news", 25), ("rumor", 20))

# ---------------------------------------------------------------- 事件参数（§4.2）
# 调参记录（scripts/event_sim_report.py，20 seed × 300 日）：计划初值 MAJOR_MAG industry/stock
# (40k,70k)、MAJOR_IMPULSE (300k,450k) 下普通成分股触板率 17.7% 超过 15%，
# 故下调为 (32k,56k) / (200k,350k)。
MAJOR_MAG_PPM = {
    "industry": (32_000, 56_000),
    "stock": (32_000, 56_000),
    "market": (15_000, 30_000),
}
MINOR_MAG_PPM = (10_000, 25_000)
# v2 的源满幅缩放（01 §5.1 / §4.2 v2 表）：v2 的个股/行业日噪声约为 v1 的 0.42 倍，
# 因此 industry/stock 的 M 乘 0.45 以保持信噪比；market 不缩（指数层面的共同因子反而变大）。
# 按 clock_rules 取值，1 = 恒等。仿真调参只改这里（Q11）。
MAG_SCALE_PPM = {1: 1_000_000, 2: 450_000}
MAJOR_IMPULSE_PPM = (200_000, 350_000)
MINOR_IMPULSE_PPM = (400_000, 600_000)
MAJOR_BUILD_TICKS = (16, 40)
MINOR_BUILD_TICKS = (4, 12)
MAJOR_HOLD_TICKS = (0, 20)
MINOR_HOLD_TICKS = (0, 10)
MAJOR_RECOVER_TICKS = (40, 80)
MINOR_RECOVER_TICKS = (20, 60)
MAJOR_RETAIN_PPM = {
    "announcement": (600_000, 800_000),
    "policy": (600_000, 800_000),
    "news": (400_000, 700_000),
    "rumor": (400_000, 700_000),
    "sudden": (300_000, 600_000),
}
MINOR_RETAIN_PPM = (200_000, 600_000)
MAJOR_OFFSET = (0, 17)
MINOR_OFFSET = (0, 19)
# v2 发布偏移（01 §4.2 v2 表）：不随 scale 缩放，直接排除 11:30（偏移 120）与 15:00（偏移 241）
# 两个不接单的 tick；重大事件离收盘至少留 11 个游戏分钟给 B 作答与下单。闭区间，两段。
MAJOR_OFFSET_V2 = ((0, 119), (121, 230))
MINOR_OFFSET_V2 = ((0, 119), (121, 239))

# 预期差（priced_in）、传闻
PRICED_IN_PCT = 20
PRICED_IN_LEAD_TICKS = (20, 40)
PRICED_IN_PEAK_PPM = 600_000  # 铺垫期抢跑到的比例
PRICED_IN_START_PPM = 150_000
PRICED_IN_DROP_PPM = 300_000  # 正式发布时回落到的比例
PRICED_IN_RETAIN_PPM = 200_000
RUMOR_DENY_PCT = 30  # 辟谣率约三成：truth = rand(100) >= 30
RUMOR_DELAY_TICKS = (20, 60)
RUMOR_CRED_PPM = (400_000, 700_000)
RUMOR_HINT_ACCURACY_PCT = 80
DENY_FACTORS_PPM = ((0, 550_000), (1, 200_000), (3, -100_000))  # 揭晓后 (Δτ, c 的比例)
DENY_SETTLE_TICKS = 20  # τ_r + 20 归零

# 形状曲线的分段比例
BUILD_FIRST_HALF_PPM = 750_000  # 前半程完成 3/4
RECOVER_FIRST_THIRD_NUM_DEN = (5, 9)  # 前 1/3 完成 5/9

# ---------------------------------------------------------------- 上限（§5.1）
IMPULSE_CAP_PPM = 25_000  # 任一事件源节点在单 tick 的步长上限
DRIFT_CAP_PPM = 25_000  # 单只股票单 tick 所有事件漂移之和上限
# bull_bias 股票自带的 +3% 趋势在 v1 下很大，另设更小上限；v2 的 bull_bias 只是每 tick +120 ppm，
# 与普通股相同（01 §5.1，07 §4.3）。按 clock_rules 取值。
BULL_BIAS_DRIFT_CAP_PPM = {1: 19_000, 2: 25_000}
MAX_EVENT_SPAN_TICKS = 300
LOOKBACK_DAYS = 15  # 计划窗口：排期日落在 [d-15, d+2] 的事件
LOOKAHEAD_DAYS = 2
NEWS_LOOKBACK_DAYS = 3  # 快讯 tick 落在某日的事件，排期日在 [d-3, d+2]
NEWS_LOOKAHEAD_DAYS = 2

# ---------------------------------------------------------------- 传导（§5.2-§5.3）
TIER_COEF_PPM = {1: 250_000, 2: 450_000, 3: 700_000}
GATE_PPM = {
    "supply": {"demand": 300_000, "cost": 1_000_000, "sentiment": 500_000},
    "demand": {"demand": 1_000_000, "cost": 500_000, "sentiment": 700_000},
    "substitute": {"demand": 1_000_000, "cost": 1_000_000, "sentiment": 500_000},
    "same_theme": {"demand": 500_000, "cost": 300_000, "sentiment": 1_000_000},
}
CHANNELS = ("demand", "cost", "sentiment")
RELATIONS = ("supply", "demand", "substitute", "same_theme")  # 同时是边排序的关系代码
SAME_DAY_DELAY_TICKS = 3  # 滞后 0 的边
MAX_HOPS_MAJOR_INDUSTRY = 2
MAX_HOPS_MINOR_INDUSTRY = 1
MAX_HOPS_MAJOR_STOCK = 1  # 从股票所在行业节点再传 1 跳
MAX_HOPS_MINOR_STOCK = 0
MIN_SCALE_PPM = 100_000
NODE_CAP_PPM = 800_000
MAX_DELAY_TICKS = 100
STOCK_SPILL_MAJOR_PPM = 300_000
STOCK_SPILL_MINOR_PPM = 150_000

# ---------------------------------------------------------------- 存档级抖动（§5.2，Q10）
SAVE_JITTER_ENABLED = True  # Q10：关闭后所有存档系数完全一致
SAVE_JITTER_PPM = (900_000, 1_100_000)

# ---------------------------------------------------------------- 个股敏感度（§5.5）
DEFAULT_BETA_PPM = 1_000_000
LEADER_BETA_PPM = 1_200_000
DEFAULT_PICK_PCT = (5, 30)  # {pct} 取值
DEFAULT_PICK_AMOUNT = (1, 50)  # {amount} 亿
