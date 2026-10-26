"""生成 backend/src/stocksim/data/stock_exposure.json（个股龙头与跨行业暴露度）。

用法：
    python3 scripts/build_stock_exposure.py           # 生成（幂等）
    python3 scripts/build_stock_exposure.py --check   # 只校验约束并检查文件是否最新

默认规则（01 §7.3）：每个行业在股票池顺序中的第 1 只是龙头；股票数 >= 8 的行业前 2 只是龙头。
随后合并手工覆盖文件 scripts/stock_exposure_overrides.json（{code: {leader?, extra?}}）。
extra 为 [[行业, ppm], ...]，最多 2 项，行业不能等于主行业，合计 <= 500_000。纯标准库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "src" / "stocksim" / "data"
DEFAULT_OUT = DATA / "stock_exposure.json"
DEFAULT_OVERRIDES = Path(__file__).resolve().parent / "stock_exposure_overrides.json"

VERSION = 1
DEFAULT_BETA_PPM = 1_000_000
LEADER_BETA_PPM = 1_200_000
BIG_INDUSTRY_STOCKS = 8  # 股票数达到该值的行业取前 2 只作龙头
MAX_EXTRA_ITEMS = 2
MAX_EXTRA_TOTAL_PPM = 500_000


def default_leaders(pool: list[dict]) -> set[str]:
    counts: dict[str, int] = {}
    for s in pool:
        counts[s["industry"]] = counts.get(s["industry"], 0) + 1
    taken: dict[str, int] = {}
    leaders: set[str] = set()
    for s in pool:
        ind = s["industry"]
        quota = 2 if counts[ind] >= BIG_INDUSTRY_STOCKS else 1
        if taken.get(ind, 0) < quota:
            leaders.add(s["code"])
            taken[ind] = taken.get(ind, 0) + 1
    return leaders


def build(pool: list[dict], overrides: dict[str, dict]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    by_code = {s["code"]: s for s in pool}
    industries = {s["industry"] for s in pool}
    for code in overrides:
        if code not in by_code:
            errors.append(f"覆盖文件中的代码 {code} 不在股票池")
    leaders = default_leaders(pool)
    stocks: dict[str, dict] = {}
    for s in pool:
        code = s["code"]
        ov = overrides.get(code, {})
        extra = [[str(n), int(w)] for n, w in ov.get("extra", [])]
        if len(extra) > MAX_EXTRA_ITEMS:
            errors.append(f"{code}: extra 最多 {MAX_EXTRA_ITEMS} 项")
        if sum(w for _, w in extra) > MAX_EXTRA_TOTAL_PPM:
            errors.append(f"{code}: extra 合计超过 {MAX_EXTRA_TOTAL_PPM}")
        for name, weight in extra:
            if name not in industries:
                errors.append(f"{code}: extra 行业 {name!r} 不在 82 个行业内")
            if name == s["industry"]:
                errors.append(f"{code}: extra 行业不能等于主行业 {name!r}")
            if weight <= 0:
                errors.append(f"{code}: extra 权重必须为正")
        if len({n for n, _ in extra}) != len(extra):
            errors.append(f"{code}: extra 行业重复")
        is_leader = bool(ov["leader"]) if "leader" in ov else code in leaders
        stocks[code] = {"leader": is_leader, "extra": extra}
    data = {
        "version": VERSION,
        "default_beta_ppm": DEFAULT_BETA_PPM,
        "leader_beta_ppm": LEADER_BETA_PPM,
        "stocks": stocks,
    }
    return data, errors


def dumps(data: dict) -> str:
    lines = [
        "{",
        f'  "version": {data["version"]},',
        f'  "default_beta_ppm": {data["default_beta_ppm"]},',
        f'  "leader_beta_ppm": {data["leader_beta_ppm"]},',
        '  "stocks": {',
    ]
    items = list(data["stocks"].items())
    for i, (code, v) in enumerate(items):
        body = json.dumps(v, ensure_ascii=False)
        lines.append(f'    "{code}": {body}{"," if i < len(items) - 1 else ""}')
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    pool = json.loads((DATA / "stock_pool.json").read_text(encoding="utf-8"))
    overrides = (
        json.loads(args.overrides.read_text(encoding="utf-8")) if args.overrides.exists() else {}
    )
    data, errors = build(pool, overrides)
    if errors:
        for err in errors:
            print(f"ERROR {err}", file=sys.stderr)
        return 1
    rendered = dumps(data)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != rendered:
            print(
                f"ERROR {args.out} 不是最新，请运行 python3 scripts/build_stock_exposure.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK {len(data['stocks'])} stocks")
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    leaders = sum(1 for v in data["stocks"].values() if v["leader"])
    print(f"wrote {args.out} ({len(data['stocks'])} stocks, {leaders} leaders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
