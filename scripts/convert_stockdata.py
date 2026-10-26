"""把 legacy/stockData.js 转换为后端静态数据（stock_pool.json / industries.json）。

用法：python3 scripts/convert_stockdata.py
只读 legacy/stockData.js，写入 backend/src/stocksim/data/。幂等。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "legacy" / "stockData.js"
OUT_DIR = ROOT / "backend" / "src" / "stocksim" / "data"

EXPECTED_COUNT = 385
DEFAULT_RANGE_YUAN = [5, 100]
# 与 legacy/game.js generateBasePrice (1687-1701) 的行业价格区间一致
LEGACY_RANGES_YUAN = {
    "银行": [5, 15],
    "白酒": [50, 2000],
    "医药": [20, 200],
    "科技": [10, 100],
    "新能源": [30, 300],
    "券商": [8, 30],
    "保险": [20, 80],
}
BULL_BIAS_CODE = "999999"  # 影视飓风彩蛋（legacy/game.js 2087-2088）
# 名称覆盖：legacy 中 000938 误为“中芯国际”，实为紫光股份（决策 19，2026-10-26）。
# 只改名称，行情不依赖 name（已证明逐 tick 不变）；legacy 只读，不改源。
NAME_OVERRIDES = {"000938": "紫光股份"}

ENTRY_RE = re.compile(r"\{\s*code:\s*'([^']+)',\s*name:\s*'([^']+)',\s*industry:\s*'([^']+)'\s*\}")


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    entries = ENTRY_RE.findall(src)
    if len(entries) != EXPECTED_COUNT:
        raise SystemExit(f"expected {EXPECTED_COUNT} stocks, parsed {len(entries)}")
    codes = [code for code, _, _ in entries]
    if len(set(codes)) != len(codes):
        dup = sorted({c for c in codes if codes.count(c) > 1})
        raise SystemExit(f"duplicate codes: {dup}")

    stocks = []
    for code, name, industry in entries:
        profile = "bull_bias" if code == BULL_BIAS_CODE else "normal"
        name = NAME_OVERRIDES.get(code, name)
        stocks.append({"code": code, "name": name, "industry": industry, "profile": profile})

    counts = Counter(s["industry"] for s in stocks)
    industries = [
        {
            "name": name,
            "stock_count": counts[name],
            "base_price_range_yuan": LEGACY_RANGES_YUAN.get(name, DEFAULT_RANGE_YUAN),
        }
        for name in sorted(counts, key=lambda n: (-counts[n], n))
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "stock_pool.json").write_text(
        json.dumps(stocks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "industries.json").write_text(
        json.dumps(industries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"stocks={len(stocks)} industries={len(industries)} -> {OUT_DIR}")


if __name__ == "__main__":
    main()
