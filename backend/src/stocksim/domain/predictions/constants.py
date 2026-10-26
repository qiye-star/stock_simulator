"""预测卡全部可调常量（02 §4、§5.7、§7；06 §4.3 建议值）。调参只改这里。

RNG 段（§4.4，与 domain/rng.py 文档字符串同步；test_prediction_rng_layout.py 枚举验证）：
  预测·出题  tick = PREDICTION_TICK_BASE − 事件排期日，idx = slot（0/1），k = 第 j 个诱饵（0..7）
"""

from __future__ import annotations

PREDICTION_RULES_VERSION = 1
DIRECTION_WINDOW_DAYS = 3  # 两个时钟版本相同（按交易日计）
DIRECTION_BUCKETS = 5
RUMOR_BUCKETS = 2

# 方向题真值的噪声模型（σ 公式见 domain/predictions/questions.py::bucket_edges_bp）
# v1：单股单日 σ ≈ 516 bp（A §5.1），无共同因子；v2（07 §4.3 预估，C4 定稿后回写）
NOISE_IDIO_DAY_BP = {1: 516, 2: 217}  # 个股特质部分（含趋势日），随 √n 平均
NOISE_MKT_DAY_BP = {1: 0, 2: 75}  # 全市场共同因子，不随 n 平均
EDGE_FLOOR_BP = {"industry": (100, 300), "stock": (200, 600), "market": (100, 250)}  # v1
EDGE_FLOOR_BP_BY_CLOCK = {
    1: EDGE_FLOOR_BP,
    2: {"industry": (50, 150), "stock": (100, 300), "market": (50, 150)},
}

# 排序题（NDCG@3）
RANK_K = 3
RANK_CANDIDATES = 8
RANK_TRUE_MAX = 5
RANK_MIN_IMPACT_PPM = 100_000  # 窗口末冲击 ≥ 源满幅 10% 才算“受影响”
RANK_DECOY_WEIGHT = (3, 1)  # (结构邻居, 其它行业) 的抽样权重

# 把握（pct）：档位 + 把握 → 分布
CONF_MAX_PCT = 100
CONF_STEP_PCT = 5
CONF_MIN_PCT = {5: 20, 2: 50}
CONF_DEFAULT_PCT = {5: 50, 2: 70}

# RNG 命名空间（§4.4）
PREDICTION_TICK_BASE = -(1 << 34)

# ---------------------------------------------------------------- 积分经济（02 §5.7、§7；06 §4.3）
WELCOME_POINTS = 200  # 开户赠送（Q2）
PREDICTION_DAILY_POINTS_CAP = (
    1000  # 每用户每 UTC 自然日，reason=prediction 的入账合计（06 §4.3 建议）
)
INTEL_PRICE_EDGE_L1 = 100
INTEL_PRICE_EDGE_L2 = 200  # 已有 L1 时补差价 INTEL_PRICE_EDGE_L2 − INTEL_PRICE_EDGE_L1
INTEL_PRICE_RUMOR_HINT = 80
INTEL_DAILY_LIMIT = 8  # 每用户每 UTC 自然日情报卡购买次数

# 称号（02 §8）：校准样本门槛与误差上限
TITLE_CALIBRATION_MIN_SAMPLES = 40
TITLE_CALIBRATION_MAX_ERROR_BP = 800
TITLE_ANALYST_MIN_CARDS = 50
TITLE_ANALYST_MIN_AVG_BASELINE = 30
TITLE_STREAK_WINDOW = 10
