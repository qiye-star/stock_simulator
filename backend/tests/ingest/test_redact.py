from __future__ import annotations

from stocksim.replay_ingest.redact import StockMask, find_residuals, mask_text, scrub_dates

MASKS = [
    StockMask("s1", "600030", "中信证券", "990001", "券商A", ("中信证券股份", "中信")),
    StockMask("s2", "300059", "东方财富", "990002", "券商B", ("东财",)),
]


def test_longest_term_first_and_code_replaced() -> None:
    text = "中信证券股份有限公司（600030）与东方财富、东财合作，中信入股。"
    assert mask_text(text, MASKS) == "券商A有限公司（990001）与券商B、券商B合作，券商A入股。"


def test_code_replacement_does_not_touch_longer_digit_runs() -> None:
    assert mask_text("编号6000301与600030", MASKS) == "编号6000301与990001"


def test_placeholder_replaces_every_name() -> None:
    assert mask_text("中信证券和东财", MASKS, placeholder="{name}") == "{name}和{name}"


def test_scrub_dates_variants() -> None:
    assert scrub_dates("2023年8月27日晚间") == "近日晚间"
    assert scrub_dates("2023-08-27公告") == "近日公告"
    assert scrub_dates("2023年8月份") == "近期份"
    assert scrub_dates("8月27日起") == "近日起"
    assert scrub_dates("2023年度报告") == "本年度报告"
    assert scrub_dates("2023年半年度报告") == "半年度报告"
    assert scrub_dates("无日期文本 100 万股") == "无日期文本 100 万股"


def test_masked_text_has_no_terms_or_codes() -> None:
    out = mask_text("中信证券、东方财富、东财、中信（600030/300059）2023年8月27日", MASKS)
    for m in MASKS:
        assert m.real_code not in out
        assert not any(t in out for t in m.all_terms())
    assert find_residuals(out, MASKS) == []


def test_residuals_report_year_digits_but_not_amounts() -> None:
    assert find_residuals("对比 2019Q3 水平", MASKS) == ["2019"]
    assert find_residuals("募资 2000 万元，持股 2023 股", MASKS) == []
    assert find_residuals("价格 2023.5 元", MASKS) == []
    # 漏网的真名与真代码
    assert find_residuals("东财 300059", MASKS) == ["东财", "300059"]
