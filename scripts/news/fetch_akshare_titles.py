"""手动运行：从 AKShare 抓取近期公告/快讯/政策标题，存到 scripts/news/corpus/*.jsonl（不提交）。

用法：
    uv run --with akshare python scripts/news/fetch_akshare_titles.py --days 60

只抓标题，不抓正文。每个来源独立 try/except，某个接口失败（改名、限流、网络）只打印警告并继续。
输出行：{"source": "...", "date": "YYYY-MM-DD", "title": "..."}。
注意：快讯 stock_info_global_cls 与个股新闻 stock_news_em 只能拿到最近的少量条目，
要积累语料需要定时运行。本脚本不是运行时依赖；游戏运行时不联网、不调用 LLM。
未在无网络环境中实测过，列名按 AKShare 文档以候选列表兜底。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
TITLE_COLUMNS = ("公告标题", "标题", "title", "新闻标题", "具体事项", "事件类型")
DATE_COLUMNS = ("公告时间", "发布日期", "发布时间", "date", "交易日")


def _rows(df, source: str, fallback_date: str):
    title_col = next((c for c in TITLE_COLUMNS if c in df.columns), None)
    if title_col is None:
        print(f"WARN {source}: 找不到标题列，列名 {list(df.columns)}", file=sys.stderr)
        return
    date_col = next((c for c in DATE_COLUMNS if c in df.columns), None)
    for _, row in df.iterrows():
        title = str(row[title_col]).strip()
        if title and title != "nan":
            date = str(row[date_col])[:10] if date_col else fallback_date
            yield {"source": source, "date": date, "title": title}


def _write(path: Path, rows) -> int:
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    try:
        import akshare as ak
    except ImportError:
        print(
            "需要 akshare：uv run --with akshare python scripts/news/fetch_akshare_titles.py",
            file=sys.stderr,
        )
        return 1

    CORPUS.mkdir(exist_ok=True)
    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)
    fmt = "%Y%m%d"

    def attempt(name: str, fn) -> None:
        try:
            print(f"{name}: {fn()} 条")
        except Exception as exc:
            print(f"WARN {name} 失败：{exc}", file=sys.stderr)

    attempt(
        "cninfo 公告",
        lambda: _write(
            CORPUS / "disclosure.jsonl",
            _rows(
                ak.stock_zh_a_disclosure_report_cninfo(
                    symbol="",
                    market="沪深京",
                    start_date=start.strftime(fmt),
                    end_date=end.strftime(fmt),
                ),
                "cninfo",
                end.isoformat(),
            ),
        ),
    )
    for offset in range(args.days):
        day = end - dt.timedelta(days=offset)
        attempt(
            f"公司动态 {day}",
            lambda day=day: _write(
                CORPUS / "gsdt.jsonl",
                _rows(ak.stock_gsrl_gsdt_em(date=day.strftime(fmt)), "gsdt", day.isoformat()),
            ),
        )
        attempt(
            f"新闻联播 {day}",
            lambda day=day: _write(
                CORPUS / "cctv.jsonl",
                _rows(ak.news_cctv(date=day.strftime(fmt)), "cctv", day.isoformat()),
            ),
        )
    attempt(
        "财联社快讯",
        lambda: _write(
            CORPUS / "cls.jsonl", _rows(ak.stock_info_global_cls(), "cls", end.isoformat())
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
