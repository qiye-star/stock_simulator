"""确定性计数器式 RNG（splitmix64 变体），规范见 docs/CONTRACT.md。

z = (seed + (tick*1000003 + stock_idx*7919 + k) * 0x9E3779B97F4A7C15) mod 2^64
然后做 splitmix64 混合（均 mod 2^64）：
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
  z = (z ^ (z >> 27)) * 0x94D049BB133111EB
  z = z ^ (z >> 31)
rand01 返回 (z >> 11) / 2^53，取值 [0, 1)。

rand_below 是同一 64 位输出的精确整数版本（无浮点误差），行情引擎只用它。
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
