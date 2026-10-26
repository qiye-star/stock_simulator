"""把抓取的标题语料提炼成“模板 + 槽位”的句式候选（纯标准库）。

用法：
    python3 scripts/news/extract_patterns.py [--corpus DIR] [--out FILE] [--min-count N]
    默认语料 scripts/news/corpus，默认输出 scripts/news/pattern_candidates.json

步骤：读取 corpus/*.jsonl -> 把股票名/行业名/地区/数字替换成槽位 -> 按句式聚类计数 ->
用关键词把句式归到 DuEE-fin 的 subtype -> 按频次输出候选，供人工（或一次性 LLM）筛选后写入
templates_src.json。候选不含原文标题，只保留句式与出现次数。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "backend" / "src" / "stocksim" / "data"

REGIONS = (
    "华东",
    "华南",
    "华北",
    "华中",
    "西南",
    "西北",
    "东北",
    "广东",
    "江苏",
    "浙江",
    "山东",
    "四川",
    "上海",
    "北京",
)
AGENCIES = (
    "国家发改委",
    "发改委",
    "工信部",
    "财政部",
    "国务院",
    "商务部",
    "央行",
    "证监会",
    "住建部",
    "国家能源局",
)
# 关键词 -> subtype（按顺序匹配，先匹配者优先）
SUBTYPE_KEYWORDS = (
    ("解除质押", "pledge_release"),
    ("质押", "pledge"),
    ("回购", "buyback"),
    ("减持", "holder_reduce"),
    ("增持", "holder_increase"),
    ("预亏", "loss"),
    ("亏损", "loss"),
    ("收购", "acquisition"),
    ("定增", "financing"),
    ("可转债", "financing"),
    ("募资", "financing"),
    ("破产", "bankruptcy"),
    ("重整", "bankruptcy"),
    ("上市", "listing"),
    ("辞职", "exec_change"),
    ("聘任", "exec_change"),
    ("问询", "summoned"),
    ("约谈", "summoned"),
    ("中标", "bid_win"),
    ("合同", "bid_win"),
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:亿元|亿)")


def load_vocab() -> tuple[list[str], list[str]]:
    pool = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
    industries = json.loads((DATA / "industries.json").read_text(encoding="utf-8"))
    names = sorted({s["name"] for s in pool}, key=len, reverse=True)
    inds = sorted({i["name"] for i in industries}, key=len, reverse=True)
    return names, inds


def to_pattern(title: str, stock_names: list[str], industries: list[str]) -> str:
    text = title.strip()
    for name in stock_names:
        text = text.replace(name, "{stock}")
    for ind in industries:
        text = text.replace(ind, "{industry}")
    for region in REGIONS:
        text = text.replace(region, "{region}")
    for agency in AGENCIES:
        text = text.replace(agency, "{agency}")
    text = AMOUNT_RE.sub("{amount}亿元", text)
    text = PCT_RE.sub("{pct}%", text)
    text = NUMBER_RE.sub("{n}", text)
    return text


def guess_subtype(pattern: str) -> str | None:
    for keyword, subtype in SUBTYPE_KEYWORDS:
        if keyword in pattern:
            return subtype
    return None


def extract(
    titles: list[str], stock_names: list[str], industries: list[str], min_count: int = 1
) -> list[dict]:
    counter = Counter(to_pattern(t, stock_names, industries) for t in titles if t.strip())
    out = [
        {"pattern": p, "count": n, "subtype_guess": guess_subtype(p)}
        for p, n in counter.most_common()
        if n >= min_count and len(p) >= 6
    ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus")
    parser.add_argument("--out", type=Path, default=HERE / "pattern_candidates.json")
    parser.add_argument("--min-count", type=int, default=1)
    args = parser.parse_args()

    titles: list[str] = []
    for path in sorted(args.corpus.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                titles.append(json.loads(line)["title"])
    names, inds = load_vocab()
    candidates = extract(titles, names, inds, args.min_count)
    args.out.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{len(titles)} titles -> {len(candidates)} patterns -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
