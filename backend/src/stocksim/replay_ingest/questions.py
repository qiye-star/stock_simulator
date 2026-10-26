"""预测题：档位边界、答案计算、排序题相关度（05 §3.2）。只用标准库。

所有序列都与窗口日期对齐，第 ``d`` 个游戏日的收盘在 ``closes[lookback + d]``。
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from fractions import Fraction
from itertools import pairwise
from typing import Any

from .adjust import round_half_up
from .errors import BuildError
from .redact import StockMask, find_residuals, mask_text
from .spec import Spec, Window

EDGE_STEP_BP = 50
RELEVANCE = (3, 2, 1)  # 真实前三的相关度


def bucket_of(value_bp: int, edges_bp: Sequence[int]) -> int:
    """档位左闭右开：``(-inf, e0) [e0, e1) ... [e_last, +inf)``，返回 0..len(edges)。"""
    return bisect_right(list(edges_bp), value_bp)


def return_bp(base: int, end: int) -> int:
    """``round_half_up((end - base) * 10000 / base)``，base 必须为正。"""
    if base <= 0:
        raise BuildError(f"基准价必须为正: {base}")
    return round_half_up(Fraction((end - base) * 10_000, base))


def _round_step(x: float) -> int:
    return math.floor(x / EDGE_STEP_BP + 0.5) * EDGE_STEP_BP


def auto_edges(lookback_closes: Sequence[int], horizon_days: int) -> list[int]:
    """``edges_bp: "auto"``：σ 为回看期日收益率（bp）的样本标准差，``s = σ·√h``，
    边界 ``[-1.0s, -0.3s, +0.3s, +1.0s]`` 各取整到 50bp，且绝对值至少 50bp。
    为保证严格升序，外侧边界至少比内侧大 50bp。
    """
    if len(lookback_closes) < 3:
        raise BuildError("回看期太短，无法计算 auto 档位边界")
    rets = [Fraction((b - a) * 10_000, a) for a, b in pairwise(lookback_closes)]
    sigma = float(statistics.stdev(rets))
    s = sigma * math.sqrt(horizon_days)
    inner = max(EDGE_STEP_BP, _round_step(0.3 * s))
    outer = max(inner + EDGE_STEP_BP, _round_step(1.0 * s))
    return [-outer, -inner, inner, outer]


def rank_relevance(
    returns_bp: Mapping[str, int], top_k: int
) -> tuple[dict[str, int], list[tuple[str, ...]]]:
    """真实前 k 名的相关度 3/2/1。并列时按 stock_key 升序打破；返回 (相关度, 并列组列表)。"""
    order = sorted(returns_bp, key=lambda k: (-returns_bp[k], k))
    relevance = {k: RELEVANCE[i] for i, k in enumerate(order[:top_k])}
    ties: list[tuple[str, ...]] = []
    for value in sorted({returns_bp[k] for k in order[: top_k + 1]}, reverse=True):
        group = tuple(k for k in order if returns_bp[k] == value)
        if len(group) > 1 and any(order.index(k) < top_k for k in group):
            ties.append(group)
    return relevance, ties


def build_questions(
    spec: Spec,
    window: Window,
    closes: Mapping[str, Sequence[int]],
    key_of: Mapping[str, str],
    masks: Sequence[StockMask],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    """返回 (题目列表, 脱敏残留报告, 警告)。``closes``: stock_key -> 与窗口对齐的复权收盘（分）。"""
    out: list[dict[str, Any]] = []
    report: list[dict[str, str]] = []
    warnings: list[str] = []
    lookback = window.lookback

    def close_at(key: str, day: int) -> int:
        return closes[key][lookback + day]

    for q in spec.questions:
        opens, closes_pos = q["opens"], q["closes"]
        resolve_day = opens["day"] + q["horizon_days"] - 1
        base_day = opens["day"] - 1
        item: dict[str, Any] = {
            "id": q["id"],
            "kind": q["kind"],
            "opens": opens,
            "closes": closes_pos,
            "resolves": {"day": resolve_day, "phase": "close"},
            "prompt": q["prompt"],
        }
        if q["kind"] == "direction_bucket":
            key = key_of[q["code"]]
            edges = (
                auto_edges(closes[key][:lookback], q["horizon_days"])
                if q["edges_bp"] == "auto"
                else list(q["edges_bp"])
            )
            ret = return_bp(close_at(key, base_day), close_at(key, resolve_day))
            item.update(
                stock_key=key,
                base="prev_close",
                edges_bp=edges,
                answer={"bucket": bucket_of(ret, edges), "return_bp": ret},
            )
            placeholder = "{name}"
        else:
            keys = [key_of[c] for c in q["codes"]]
            rets = {k: return_bp(close_at(k, base_day), close_at(k, resolve_day)) for k in keys}
            relevance, ties = rank_relevance(rets, q["top_k"])
            for group in ties:
                warnings.append(f"题 {q['id']}: 涨幅并列 {list(group)}，按 stock_key 升序打破")
            item.update(
                stock_keys=keys,
                top_k=q["top_k"],
                answer={"returns_bp": dict(sorted(rets.items())), "relevance": relevance},
            )
            placeholder = None
        masked = q["prompt_masked"] or mask_text(q["prompt"], masks, placeholder=placeholder)
        masked = mask_text(masked, masks, placeholder=placeholder)
        item["prompt_masked"] = masked
        for hit in find_residuals(masked.replace("{name}", ""), masks):
            report.append({"event_id": q["id"], "field": "prompt_masked", "hit": hit})
        out.append(item)
    return out, report, warnings
