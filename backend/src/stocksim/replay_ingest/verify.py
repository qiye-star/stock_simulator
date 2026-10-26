"""关卡包校验与脱敏报告。只用标准库，不联网。

``verify_pack`` 只依赖包本身：结构、窗口对齐、OHLC 与涨跌幅、事件与题目答案复算、匿名泄露扫描，
并统计“归到 pre_open 的重要巨潮公告”的跳空与前一日异动（05 Q10 的人工抽查依据）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import PACK_FORMAT, PACK_FORMAT_VERSION
from .build import PACK_SIZE_WARN_BYTES, canonical_dumps
from .limits import FLAG_SUSPENDED
from .questions import bucket_of, rank_relevance, return_bp
from .slots import SLOT_ORDER

LIMIT_TOLERANCE_BP = 10
PHASES = ("pre_open", "open", "close", "post_close")
_EID = re.compile(r"^e\d{4,}$")
_GAP_BP = 200  # 开盘跳空超过它，认为公告反应出现在开盘
_PRIOR_MOVE_BP = 300  # 前一日开收盘波动超过它，认为公告前已有异动
SAMPLE_LIMIT = 20


@dataclass
class VerifyReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def verify_pack(pack: dict[str, Any]) -> VerifyReport:
    r = VerifyReport()
    err = r.errors.append

    if pack.get("format") != PACK_FORMAT or pack.get("format_version") != PACK_FORMAT_VERSION:
        err(f"format/format_version 不是 {PACK_FORMAT}/{PACK_FORMAT_VERSION}")
        return r
    try:
        cal: list[str] = pack["calendar"]
        lookback, play, reveal = pack["lookback_days"], pack["play_days"], pack["reveal_days"]
        stocks = pack["stocks"]
        bars: dict[str, list[list[int]]] = pack["bars"]
        events = pack["events"]
        questions = pack["questions"]
        bench = pack["benchmark"]["closes_adj"]
    except KeyError as exc:
        err(f"缺少字段 {exc}")
        return r

    n = lookback + play + reveal
    if len(cal) != n or cal != sorted(set(cal)):
        err(f"calendar 长度应为 {n} 且升序无重复（实际 {len(cal)}）")
        return r
    if pack.get("anchor_date") != cal[lookback - 1]:
        err("anchor_date 不等于 calendar[lookback_days-1]")
    if len(bench) != n or any(not isinstance(x, int) or x <= 0 for x in bench):
        err("benchmark.closes_adj 长度或取值不对")

    keys = [s["key"] for s in stocks]
    if len(set(keys)) != len(keys) or set(keys) != set(bars):
        err("stocks 与 bars 的 key 不一致")
        return r
    if len({s["alias_code"] for s in stocks}) != len(stocks):
        err("alias_code 重复")

    # --- K 线 ---
    for key, rows in bars.items():
        if len(rows) != n:
            err(f"{key}: bars 长度 {len(rows)} != {n}")
            continue
        scale = next(s["mask_scale_ppm"] for s in stocks if s["key"] == key)
        anchor = rows[lookback - 1][3]
        scaled = (anchor * scale + 500_000) // 1_000_000
        if not 990 <= scaled <= 5010:
            err(f"{key}: 第 0 日前收缩放后 {scaled / 100:.2f} 元，不在 10–50 元")
        prev_c: int | None = None
        for i, row in enumerate(rows):
            if len(row) != 7 or any(not isinstance(x, int) or isinstance(x, bool) for x in row):
                err(f"{key}[{cal[i]}]: 每行应为 7 个整数")
                break
            o, h, lo, c, vol, lim, flags = row
            if min(o, h, lo, c) <= 0 or not (lo <= min(o, c) and max(o, c) <= h) or vol < 0:
                err(f"{key}[{cal[i]}]: OHLC/量不合法 {row}")
            if flags & FLAG_SUSPENDED and (vol != 0 or not o == h == lo == c):
                err(f"{key}[{cal[i]}]: 停牌日应为 o=h=l=c 且量 0")
            if prev_c is not None and abs(c - prev_c) * 10_000 > prev_c * (
                lim + LIMIT_TOLERANCE_BP
            ):
                err(f"{key}[{cal[i]}]: 涨跌幅超出 {lim}bp")
            prev_c = c
        if sum(1 for row in rows[lookback:] if row[6] & FLAG_SUSPENDED) * 2 > play + reveal:
            r.warnings.append(f"{key}: 游戏期与揭示期停牌超过一半")

    # --- 事件 ---
    ids = [e["id"] for e in events]
    if ids != sorted(ids) or len(set(ids)) != len(ids) or not all(_EID.match(i) for i in ids):
        err("事件 id 必须形如 e0001、升序且不重复")
    last_order: tuple[int, int] | None = None
    real_names = [s["real_name"] for s in stocks]
    real_codes = [s["real_code"] for s in stocks]
    for e in events:
        if e["slot"] not in SLOT_ORDER or not -lookback <= e["day_idx"] <= play + reveal - 1:
            err(f"{e['id']}: day_idx/slot 不合法")
            continue
        order = (e["day_idx"], SLOT_ORDER[e["slot"]])
        if last_order is not None and order < last_order:
            err(f"{e['id']}: 事件未按 (day_idx, slot) 排序")
        last_order = order
        if not set(e["stock_keys"]) <= set(keys):
            err(f"{e['id']}: stock_keys 含未知 key")
        if not 1 <= e["importance"] <= 3:
            err(f"{e['id']}: importance 越界")
        if not e["hide_in_masked"]:
            if not e["title_masked"]:
                err(f"{e['id']}: 缺少 title_masked")
            for fld in ("title_masked", "body_masked"):
                text = e[fld]
                leaks = [t for t in (*real_names, *real_codes) if t and t in text]
                if leaks:
                    err(f"{e['id']}.{fld}: 脱敏后仍含真名/真代码 {leaks}")
    for q in questions:
        for fld in ("prompt_masked",):
            leaks = [t for t in (*real_names, *real_codes) if t and t in q[fld]]
            if leaks:
                err(f"{q['id']}.{fld}: 脱敏后仍含真名/真代码 {leaks}")

    # --- 题目答案复算 ---
    def close_at(key: str, day: int) -> int:
        return bars[key][lookback + day][3]

    for q in questions:
        try:
            base_day = q["opens"]["day"] - 1
            res_day = q["resolves"]["day"]
            if q["kind"] == "direction_bucket":
                ret = return_bp(
                    close_at(q["stock_key"], base_day), close_at(q["stock_key"], res_day)
                )
                want = {"bucket": bucket_of(ret, q["edges_bp"]), "return_bp": ret}
                if q["answer"] != want:
                    err(f"{q['id']}: 答案与 K 线复算不一致 {q['answer']} != {want}")
            else:
                rets = {
                    k: return_bp(close_at(k, base_day), close_at(k, res_day))
                    for k in q["stock_keys"]
                }
                rel, ties = rank_relevance(rets, q["top_k"])
                if q["answer"] != {"returns_bp": dict(sorted(rets.items())), "relevance": rel}:
                    err(f"{q['id']}: 答案与 K 线复算不一致")
                for group in ties:
                    r.warnings.append(f"{q['id']}: 涨幅并列 {list(group)}，按 stock_key 升序打破")
        except (KeyError, IndexError, ValueError) as exc:
            err(f"{q.get('id')}: 题目字段不合法 {exc!r}")

    # --- 脱敏残留与体积 ---
    for item in pack.get("redaction_report", []):
        r.warnings.append(
            f"脱敏残留待人工确认：{item['event_id']}.{item['field']} 含 {item['hit']!r}"
        )
    size = len(canonical_dumps(pack).encode("utf-8"))
    r.info.append(f"体积 {size} 字节，事件 {len(events)} 条，题目 {len(questions)} 道")
    if size > PACK_SIZE_WARN_BYTES:
        r.warnings.append(f"包体积超过 {PACK_SIZE_WARN_BYTES} 字节")

    # --- 05 Q10：pre_open 重要巨潮公告的归属抽查 ---
    sample: list[str] = []
    gap_hit = prior_hit = total = 0
    for e in events:
        if e["source"] != "cninfo" or e["importance"] < 2 or e["slot"] != "pre_open":
            continue
        if not e["stock_keys"] or e["stock_keys"][0] not in bars or e["day_idx"] < 1 - lookback:
            continue
        rows = bars[e["stock_keys"][0]]
        j = lookback + e["day_idx"]
        gap = return_bp(rows[j - 1][3], rows[j][0])
        prior = return_bp(rows[j - 1][0], rows[j - 1][3])
        total += 1
        gap_hit += abs(gap) >= _GAP_BP
        prior_hit += abs(prior) >= _PRIOR_MOVE_BP
        if len(sample) < SAMPLE_LIMIT:
            sample.append(
                f"{e['id']} day={e['day_idx']} gap={gap}bp prev_day_open_to_close={prior}bp"
            )
    if total:
        r.info.append(
            f"pre_open 重要巨潮公告 {total} 条：开盘跳空 >= {_GAP_BP}bp 的 {gap_hit} 条，"
            f"前一日开收盘波动 >= {_PRIOR_MOVE_BP}bp 的 {prior_hit} 条（后者疑似归属偏早，请抽查）"
        )
        r.info.extend(f"  抽查 {s}" for s in sample)
    return r
