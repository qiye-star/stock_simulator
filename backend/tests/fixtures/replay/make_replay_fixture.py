"""生成 replay_ingest 的**合成**测试夹具（不含真实行情与新闻原文）。只用标准库，确定性输出。

    python3 backend/tests/fixtures/replay/make_replay_fixture.py [--out DIR]

产物（默认写在本脚本所在目录）：
- ``spec_min.json``  关卡规格（3 只股票、15 回看 + 6 游戏 + 4 揭示日）
- ``client/``        FakeClient 的响应（AKShare 原生列名，覆盖全部 40 个交易日；无文件即空结果）
- ``raw/``           抓取层按规格应写出的原始数据（RawStore 布局；``cls/`` 由 E5 产生，仅供构建器）
- ``pack_min.json`` 不在这里生成，由 ``UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden`` 写入。

覆盖的边界：周末、3 天长假、后复权因子噪声、除权日、停牌日、开盘一字涨停、收盘封跌停、创业板 +15%、
巨潮 4 种时刻（仅日期 / 00:00:00 / 盘中 / 盘后）加非交易日与例行公告、无数据日、
新闻联播命中与不命中、
手写事件（含 hide_in_masked）、cls 快讯含 1 条重复。
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
FETCHED_AT = "2024-01-01T00:00:00Z"
AK_VERSION = "9.9.9-fixture"
TODAY = "2024-01-01"
HOLIDAYS = {date(2023, 6, 21), date(2023, 6, 22), date(2023, 6, 23)}
N_DAYS, I0, LOOKBACK, PLAY, REVEAL = 40, 20, 15, 6, 4
START, END = I0 - LOOKBACK, I0 + PLAY + REVEAL  # 窗口 [5, 30)

STOCKS = [  # code, 简称, 起始价（分）, hfq 起始因子, 行业
    ("600001", "测试甲", 2400, Fraction(34561, 10000), "券商"),
    ("300001", "测试乙", 1500, Fraction(21, 10), "券商"),
    ("000001", "测试丙", 800, Fraction(15, 10), "银行"),
]


def dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(obj), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(dump(r) for r in rows), encoding="utf-8")


def trading_days() -> list[str]:
    out: list[str] = []
    d = date(2023, 6, 1)
    while len(out) < N_DAYS:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def lcg(seed: int):
    x = seed
    while True:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        yield x >> 8


def mul_bp(cents: int, bp: int) -> int:
    return (cents * (10_000 + bp) + 5_000) // 10_000


def price_str(cents: int) -> str:
    return str(cents / 100)


def round_half_up(fr: Fraction) -> int:
    return (2 * fr.numerator + fr.denominator) // (2 * fr.denominator)


def gen_stock(code: str, start_cents: int, f0: Fraction) -> list[dict | None]:
    """每个交易日一行 {o,h,l,c,v_lot,F}（原始价，分）；停牌日为 None。"""
    rng = lcg(int(code))
    rows: list[dict | None] = []
    prev = start_cents
    factor = f0
    for idx in range(N_DAYS):
        day = idx - I0
        r, gap, hi, lo = (
            next(rng) % 601 - 300,
            next(rng) % 201 - 100,
            next(rng) % 151,
            next(rng) % 151,
        )
        vol = 100_000 + next(rng) % 900_000
        ref = prev
        if code == "600001" and day == 1:
            rows.append(None)  # 停牌：没有行
            continue
        if code == "600001" and day == 2:  # 停牌后首日除权：每股分红使参考价为前收的 90%
            ref = mul_bp(prev, -1000)
            factor *= Fraction(prev, ref)
        o, c = mul_bp(ref, gap), mul_bp(ref, r)
        h, lo_p = mul_bp(max(o, c), hi), max(1, mul_bp(min(o, c), -lo))
        if code == "600001" and day == 3:  # 开盘一字涨停
            o = h = lo_p = c = mul_bp(ref, 1000)
            vol = 2_000
        elif code == "600001" and day == 5:  # 收盘封跌停（开盘未封）
            o, c = mul_bp(ref, -300), mul_bp(ref, -1000)
            h, lo_p = o, c
        elif code == "300001" and day == 1:  # 创业板 +15%（20% 涨跌幅）
            o, c = mul_bp(ref, 500), mul_bp(ref, 1500)
            h, lo_p = c, mul_bp(ref, 400)
        rows.append({"o": o, "h": h, "l": lo_p, "c": c, "v_lot": vol, "F": factor})
        prev = c
    return rows


def gen_index() -> list[dict]:
    rng = lcg(300)
    out: list[dict] = []
    prev = 370_000
    for _ in range(N_DAYS):
        r, gap, hi, lo = (next(rng) % 151 - 75, next(rng) % 61 - 30, next(rng) % 41, next(rng) % 41)
        o, c = mul_bp(prev, gap), mul_bp(prev, r)
        out.append(
            {
                "o": o,
                "h": mul_bp(max(o, c), hi),
                "l": mul_bp(min(o, c), -lo),
                "c": c,
                "v": 90_000_000 + next(rng) % 30_000_000,
                "amt": float((150 + next(rng) % 80) * 1_000_000_000),
            }
        )
        prev = c
    return out


def next_saturday(iso: str) -> str:
    d = date.fromisoformat(iso)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d.isoformat()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE)
    out: Path = ap.parse_args().out
    for sub in ("raw", "client"):
        shutil.rmtree(out / sub, ignore_errors=True)
    cal = trading_days()
    d = cal  # 简写：d[idx] 为 ISO 日期

    # ---- K 线 ----
    paths = {code: gen_stock(code, cents, f0) for code, _n, cents, f0, _i in STOCKS}
    noise_rng = lcg(7)
    noise_bp = {code: [next(noise_rng) % 81 - 40 for _ in range(N_DAYS)] for code, *_ in STOCKS}
    for code, rows in paths.items():
        none_c, hfq_c, none_raw, hfq_raw = [], [], [], []
        for idx, row in enumerate(rows):
            if row is None:
                continue
            amt = float(row["v_lot"] * row["c"])
            common = {"日期": d[idx], "股票代码": code, "成交量": row["v_lot"], "成交额": amt}
            none_row = {
                **common,
                "开盘": row["o"] / 100,
                "收盘": row["c"] / 100,
                "最高": row["h"] / 100,
                "最低": row["l"] / 100,
            }
            # 模拟东财后复权因子的逐日噪声（实测相邻日 ±数十 bp）：
            # 600001 干净，其余两只带 ±40bp 噪声
            noise = noise_bp[code][idx] if code != "600001" else 0
            hfq = {
                k: round_half_up(row[k] * row["F"] * Fraction(10_000 + noise, 10_000))
                for k in "ohlc"
            }
            hfq_row = {
                **common,
                "开盘": hfq["o"] / 100,
                "收盘": hfq["c"] / 100,
                "最高": hfq["h"] / 100,
                "最低": hfq["l"] / 100,
            }
            none_c.append(none_row)
            hfq_c.append(hfq_row)
            if START - 1 <= idx < END:
                none_raw.append(
                    {
                        "d": d[idx],
                        "o": price_str(row["o"]),
                        "h": price_str(row["h"]),
                        "l": price_str(row["l"]),
                        "c": price_str(row["c"]),
                        "v_lot": row["v_lot"],
                        "amt": str(amt),
                    }
                )
                hfq_raw.append(
                    {
                        "d": d[idx],
                        "o": price_str(hfq["o"]),
                        "h": price_str(hfq["h"]),
                        "l": price_str(hfq["l"]),
                        "c": price_str(hfq["c"]),
                        "v_lot": row["v_lot"],
                        "amt": str(amt),
                    }
                )
        write_json(out / "client" / f"kline_none_{code}.json", none_c)
        write_json(out / "client" / f"kline_hfq_{code}.json", hfq_c)
        write_jsonl(out / "raw" / "kline" / "none" / f"{code}.jsonl", none_raw)
        write_jsonl(out / "raw" / "kline" / "hfq" / f"{code}.jsonl", hfq_raw)

    # ---- 指数（client 用东财英文列，raw 为落盘格式）----
    idx_rows = gen_index()
    write_json(
        out / "client" / "index_000300.json",
        [
            {
                "date": d[i],
                "open": r["o"] / 100,
                "close": r["c"] / 100,
                "high": r["h"] / 100,
                "low": r["l"] / 100,
                "volume": r["v"],
                "amount": r["amt"],
            }
            for i, r in enumerate(idx_rows)
        ],
    )
    write_jsonl(
        out / "raw" / "index" / "000300.jsonl",
        [
            {
                "d": d[i],
                "o": price_str(r["o"]),
                "h": price_str(r["h"]),
                "l": price_str(r["l"]),
                "c": price_str(r["c"]),
                "v": r["v"],
                "amt": str(r["amt"]),
            }
            for i, r in enumerate(idx_rows)
            if START - 1 <= i < END
        ],
    )

    # ---- 日历 ----
    write_json(out / "client" / "calendar.json", [{"trade_date": x} for x in cal])
    write_json(
        out / "raw" / "calendar" / "trade_dates.json",
        {
            "fn": "tool_trade_date_hist_sina",
            "args": {},
            "fetched_at": FETCHED_AT,
            "akshare_version": AK_VERSION,
            "rows": cal,
        },
    )

    # ---- 巨潮公告 ----
    sat = next_saturday(d[22])

    def link(code: str, n: int) -> str:
        return f"http://www.cninfo.com.cn/new/disclosure/detail?stockCode={code}&announcementId={n}"

    cninfo = {
        "600001": [
            ("测试甲关于签订重大销售合同的公告", d[18], 1),
            ("测试甲法律意见书", d[19], 2),
            ("测试甲关于股东减持股份计划的公告", f"{d[20]} 10:30:00", 3),
            ("测试甲关于生产线检修的公告", f"{d[21]} 16:20:00", 4),
            ("测试甲关于获得政府补助的公告", f"{d[22]} 00:00:00", 5),
            ("测试甲2023年半年度业绩预告", sat, 6),
        ],
        "300001": [("测试乙关于中标重大项目的公告", f"{d[21]} 08:45:00", 7)],
        "000001": [],
    }
    for code, name, *_ in STOCKS:
        rows_all = [
            {"代码": code, "简称": name, "公告标题": t, "公告时间": ts, "公告链接": link(code, n)}
            for t, ts, n in cninfo[code]
        ]
        write_json(out / "client" / f"cninfo_{code}.json", rows_all)
        for year, q, qs, qe in (
            (2023, 2, "20230401", "20230630"),
            (2023, 3, "20230701", "20230930"),
        ):
            lo, hi = f"{qs[:4]}-{qs[4:6]}-{qs[6:]}", f"{qe[:4]}-{qe[4:6]}-{qe[6:]}"
            sel = [r for r in rows_all if lo <= r["公告时间"][:10] <= hi]
            write_json(
                out / "raw" / "cninfo" / code / f"{year}Q{q}.json",
                {
                    "fn": "stock_zh_a_disclosure_report_cninfo",
                    "args": {"code": code, "start": qs, "end": qe},
                    "fetched_at": FETCHED_AT,
                    "akshare_version": AK_VERSION,
                    "rows": sel,
                },
            )

    # ---- 东财公司动态（窗口内每个交易日一个文件；多数为空，d[24] 模拟“当日无数据”）----
    gsrl_rows = {
        d[22]: [
            {
                "序号": 1,
                "代码": "600001",
                "简称": "测试甲",
                "事件类型": "对外担保",
                "具体事项": "测试甲为全资子公司提供担保 5000 万元，担保期限一年。",
                "交易日": d[22],
            },
            {
                "序号": 2,
                "代码": "000001",
                "简称": "测试丙",
                "事件类型": "股份质押",
                "具体事项": "测试丙股东将 100 万股质押给某银行。",
                "交易日": d[22],
            },
            {
                "序号": 3,
                "代码": "999888",
                "简称": "无关公司",
                "事件类型": "股东大会",
                "具体事项": "与关卡无关。",
                "交易日": d[22],
            },
        ]
    }
    for i in range(I0 - 10, END):
        rows = gsrl_rows.get(d[i], [])
        if rows:
            write_json(out / "client" / f"gsrl_{d[i].replace('-', '')}.json", rows)
        write_json(
            out / "raw" / "gsrl" / d[i][:4] / f"{d[i]}.json",
            {
                "fn": "stock_gsrl_gsdt_em",
                "args": {"date": d[i].replace("-", "")},
                "fetched_at": FETCHED_AT,
                "akshare_version": AK_VERSION,
                "rows": rows,
            },
        )

    # ---- 新闻联播（自然日；周日 + 一个交易日有内容）----
    sunday = (date.fromisoformat(d[19]) - timedelta(days=1)).isoformat()
    cctv_rows = {
        sunday: [
            {
                "title": "国务院常务会议研究部署活跃资本市场的措施",
                "content": (
                    "2023年7月2日，国务院常务会议召开，研究提振投资者信心、"
                    "活跃资本市场的一揽子措施（对比 2019Q3 水平）。"
                ),
            },
            {
                "title": "证监会发布投资者保护新规",
                "content": "证监会近日发布新规，强化中小投资者保护。",
            },
            {"title": "全国多地迎来高温天气", "content": "气象部门提醒公众注意防暑。"},
        ],
        d[21]: [{"title": "央行宣布降准", "content": "中国人民银行宣布下调金融机构存款准备金率。"}],
    }
    start_nat, end_nat = date.fromisoformat(d[I0 - 10]), date.fromisoformat(d[END - 1])
    cur = start_nat
    while cur <= end_nat:
        iso = cur.isoformat()
        rows = [{"date": iso.replace("-", ""), **r} for r in cctv_rows.get(iso, [])]
        if rows:
            write_json(out / "client" / f"cctv_{iso.replace('-', '')}.json", rows)
        write_json(
            out / "raw" / "cctv" / iso[:4] / f"{iso}.json",
            {
                "fn": "news_cctv",
                "args": {"date": iso.replace("-", "")},
                "fetched_at": FETCHED_AT,
                "akshare_version": AK_VERSION,
                "rows": rows,
            },
        )
        cur += timedelta(days=1)

    # ---- cls 快讯（E5 抓存的产物，仅 raw；含一条重复和一条空标题）----
    flash_a = {
        "标题": "",
        "内容": "财联社7月5日电，央行今日开展逆回购操作，利率保持不变。",
        "发布日期": d[21],
        "发布时间": "10:15:30",
    }
    flash_b = {
        "标题": "测试甲发布新品",
        "内容": "测试甲今日发布新一代产品，市场反应积极。",
        "发布日期": d[21],
        "发布时间": "16:05:00",
    }
    write_jsonl(out / "raw" / "cls" / d[21][:7] / f"{d[21]}.jsonl", [flash_a, flash_a, flash_b])

    # ---- 规格 ----
    manual_day = date.fromisoformat(d[24]) - timedelta(days=1)  # 周日，归下一交易日 pre_open
    spec = {
        "slug": "fixture-min",
        "title": "夹具关卡（合成数据）",
        "title_masked": "某个周末的监管政策",
        "teaser": "测试甲在停牌复牌后除权并连续涨跌停。",
        "teaser_masked": "券商A 的一次停牌复牌。",
        "tags": ["政策", "券商"],
        "difficulty": 2,
        "d0": d[I0],
        "lookback_days": LOOKBACK,
        "play_days": PLAY,
        "reveal_days": REVEAL,
        "benchmark": {"symbol": "000300", "name": "沪深300"},
        "masked_allowed": True,
        "stocks": [
            {
                "code": "600001",
                "name": "测试甲",
                "role": "focus",
                "industry": "券商",
                "redact_terms": ["测试甲股份", "测试甲"],
            },
            {
                "code": "300001",
                "name": "测试乙",
                "role": "peer",
                "industry": "券商",
                "redact_terms": ["测试乙"],
            },
            {"code": "000001", "role": "peer", "industry": "银行", "redact_terms": ["测试丙"]},
        ],
        "sources": {
            "cninfo": True,
            "gsrl": True,
            "cctv": {"keywords": ["国务院", "证监会", "央行"]},
            "cls": True,
            "em_news": False,
        },
        "manual_events": [
            {
                "id": "m1",
                "local_time": f"{manual_day.isoformat()} 18:00",
                "kind": "policy",
                "importance": 3,
                "codes": [],
                "industries": ["券商"],
                "title": "监管部门宣布测试甲所在行业的交易成本下调",
                "title_masked": "监管部门宣布行业交易成本下调",
                "body": "2023年7月9日晚，监管部门发布公告。（合成数据）",
            },
            {
                "id": "m2",
                "local_time": f"{d[22]} 09:00",
                "kind": "news",
                "importance": 1,
                "codes": ["600001"],
                "title": "测试甲董事长接受采访",
                "hide_in_masked": True,
            },
        ],
        "questions": [
            {
                "id": "q1",
                "kind": "direction_bucket",
                "code": "600001",
                "opens": {"day": 1, "phase": "pre_open"},
                "closes": {"day": 1, "phase": "pre_open"},
                "horizon_days": 5,
                "base": "prev_close",
                "edges_bp": "auto",
                "prompt": "从昨收到 5 个交易日后收盘，测试甲的涨跌幅？",
                "prompt_masked": "从昨收到 5 个交易日后收盘，{name} 的涨跌幅？",
            },
            {
                "id": "q2",
                "kind": "rank",
                "codes": ["600001", "300001", "000001"],
                "opens": {"day": 1, "phase": "pre_open"},
                "closes": {"day": 1, "phase": "pre_open"},
                "horizon_days": 5,
                "top_k": 3,
                "prompt": "测试甲、测试乙、测试丙未来 5 日涨幅排序",
            },
        ],
        "commentary": "合成数据，仅用于测试。",
    }
    (out / "spec_min.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
