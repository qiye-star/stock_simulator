"""确定性计数器式 RNG（splitmix64 变体），规范见 docs/CONTRACT.md。

z = (seed + (tick*1000003 + stock_idx*7919 + k) * 0x9E3779B97F4A7C15) mod 2^64
然后做 splitmix64 混合（均 mod 2^64）：
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
  z = (z ^ (z >> 27)) * 0x94D049BB133111EB
  z = z ^ (z >> 31)
rand01 返回 (z >> 11) / 2^53，取值 [0, 1)。

rand_below 是同一 64 位输出的精确整数版本（无浮点误差），行情引擎只用它。

(tick, stock_idx, k) 命名空间划分（线性索引 tick*1000003 + idx*7919 + k 互不碰撞，
由 tests/unit/domain/test_events_rng_layout.py 与 test_clock_v2_rng_layout.py 暴力枚举验证；
同一 tick 内 k 的跨度必须 < 1292）：
  v1 交易 tick  tick>=1, idx 0..384, k 0,1,2,100..119  v1 行情（0 涨跌 1 彩蛋 2 量 100+ 五档）
  v2 交易 tick  tick>=1, idx 0..384, k 0,2,100..119    v2 行情（0 特质噪声 2 量 100+ 五档；1 不用）
  v2 共同因子   tick>=1, idx 400,     k 0               全市场共同因子（V2_MARKET_FACTOR_IDX）
  v2 日档位     tick=-(1<<33)-day, idx 0..384, k 0..3  每股每日的波动档位与趋势（_day_regime）
  init          tick=-1, idx 0..384, k 0,1,2..241      初始行情与历史 K 线（v1/v2 共用）
  开局分钟       tick=-2, idx 0,      k 0               clock.random_start_minute（仅 v1 使用）
  事件·日       tick=-(1<<32)-day, idx 0..9 槽位 / 30 重大周期元数据 / 31 日元数据, k 见下
  事件·存档     tick=-(1<<32)+4096, idx 0..384 β 抖动(k0) / 1000+from_idx 边抖动(k=to_idx)
  预测·出题     tick=-(1<<34)-day, idx 0..1 槽位, k 0..7 第 j 个诱饵（predictions/questions.py）
事件·日的 k：0 kind，1 模板，2 sentiment，3 源，4 M，5 offset，6 D，7 H，8 R，9 ρ，10 I，
11 priced_in，12 lead，13 传闻真假，14 揭晓延迟，15 可信度，16 情报提示，20..23 源重抽，
100..131 文案槽位。
权威说明见 domain/events/constants.py。
"""

from __future__ import annotations

MASK64 = (1 << 64) - 1
GOLDEN_GAMMA = 0x9E3779B97F4A7C15
MIX1 = 0xBF58476D1CE4E5B9
MIX2 = 0x94D049BB133111EB
TICK_MULT = 1000003
STOCK_MULT = 7919


def _raw(seed: int, tick: int, stock_idx: int, k: int) -> int:
    z = (seed + (tick * TICK_MULT + stock_idx * STOCK_MULT + k) * GOLDEN_GAMMA) & MASK64
    z = ((z ^ (z >> 30)) * MIX1) & MASK64
    z = ((z ^ (z >> 27)) * MIX2) & MASK64
    z ^= z >> 31
    return z


def rand01(seed: int, tick: int, stock_idx: int, k: int) -> float:
    """返回 [0, 1) 浮点数。"""
    return (_raw(seed, tick, stock_idx, k) >> 11) / float(1 << 53)


def rand_below(seed: int, tick: int, stock_idx: int, k: int, n: int) -> int:
    """返回整数 [0, n)，精确（(z>>11)*n >> 53）。n 必须 > 0。"""
    if n <= 0:
        raise ValueError("n must be positive")
    return ((_raw(seed, tick, stock_idx, k) >> 11) * n) >> 53
