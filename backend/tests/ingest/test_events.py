from __future__ import annotations

from fractions import Fraction

from stocksim.replay_ingest.events import _quarters, compute_impact, natural_days
from stocksim.replay_ingest.spec import Window

CAL = tuple(f"2023-01-{d:02d}" for d in range(1, 21))
WINDOW = Window(CAL, i0=6, lookback=5, play=6, reveal=4)  # 窗口 [1, 16)，共 15 个交易日


def _series(start: int, step: int) -> list[int]:
    return [start + step * i for i in range(15)]


def test_impact_is_excess_return_over_benchmark() -> None:
    stock = _series(1000, 10)  # 每日 +10 分
    bench = [10000] * 15
    ev = {"day_idx": 1, "slot": "pre_open", "stock_keys": ["s1"]}
    out = compute_impact(ev, WINDOW, {"s1": stock}, bench, [])
    pos = 1 + 5  # day_idx + lookback
    base = pos - 1  # 盘前事件：以前一日收盘为基准
    assert out["ar_1d_bp"] == round(10_000 * (stock[base + 1] - stock[base]) / stock[base])
    assert out["ar_5d_bp"] == round(10_000 * (stock[base + 5] - stock[base]) / stock[base])


def test_impact_post_close_uses_same_day_close_as_base() -> None:
    stock = [1000] * 6 + [1100] + [1100] * 8  # 窗口位置 6 涨 10%
    bench = [10000] * 15
    pre = compute_impact(
        {"day_idx": 1, "slot": "intraday", "stock_keys": ["s1"]}, WINDOW, {"s1": stock}, bench, []
    )
    post = compute_impact(
        {"day_idx": 1, "slot": "post_close", "stock_keys": ["s1"]}, WINDOW, {"s1": stock}, bench, []
    )
    assert pre["ar_1d_bp"] == 1000  # 事件日的涨幅算在盘中事件上
    assert post["ar_1d_bp"] == 0  # 盘后事件看的是次日


def test_impact_averages_keys_and_falls_back_to_focus_then_all() -> None:
    closes = {"s1": [1000] * 15, "s2": [1000] * 6 + [1200] * 9, "s3": [1000] * 15}
    bench = [10000] * 15
    ev = {"day_idx": 1, "slot": "pre_open", "stock_keys": []}
    only_focus = compute_impact(ev, WINDOW, closes, bench, ["s2"])
    assert only_focus["ar_1d_bp"] == 2000
    everyone = compute_impact(ev, WINDOW, closes, bench, [])
    assert everyone["ar_1d_bp"] == round(Fraction(2000, 3))  # 667


def test_impact_none_when_window_too_short() -> None:
    stock = _series(1000, 1)
    bench = [10000] * 15
    out = compute_impact(
        {"day_idx": 8, "slot": "pre_open", "stock_keys": ["s1"]}, WINDOW, {"s1": stock}, bench, []
    )
    assert out["ar_1d_bp"] is not None
    assert out["ar_5d_bp"] is None  # 基准日 + 5 超出窗口末尾
    early = compute_impact(
        {"day_idx": -5, "slot": "pre_open", "stock_keys": ["s1"]}, WINDOW, {"s1": stock}, bench, []
    )
    assert early == {"ar_1d_bp": None, "ar_5d_bp": None}  # 基准日在窗口之前


def test_natural_days_and_quarters() -> None:
    assert natural_days("2023-06-29", "2023-07-02") == [
        "2023-06-29",
        "2023-06-30",
        "2023-07-01",
        "2023-07-02",
    ]
    assert _quarters("2023-06-16", "2023-07-17") == [(2023, 2), (2023, 3)]
    assert _quarters("2022-11-01", "2023-02-01") == [(2022, 4), (2023, 1)]
    assert _quarters("2023-01-01", "2023-01-31") == [(2023, 1)]
