"""构建器：golden、复权锚定、除权连续、停牌补齐、标志位、事件归属、脱敏、校验失败。"""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from stocksim.replay_ingest import cli, rawstore
from stocksim.replay_ingest.adjust import yuan_to_cents
from stocksim.replay_ingest.build import build_pack, canonical_dumps
from stocksim.replay_ingest.errors import BuildError
from stocksim.replay_ingest.rawstore import RawStore
from stocksim.replay_ingest.spec import Spec, parse_spec

LB = 15  # 回看期天数；第 d 个游戏日的 bar 下标为 LB + d


def _spec_dict(fixture_dir: Path) -> dict[str, Any]:
    return json.loads((fixture_dir / "spec_min.json").read_text(encoding="utf-8"))


def _rewrite_kline(store: RawStore, adjust: str, code: str, fn) -> None:
    rel = rawstore.kline_path(adjust, code)
    store.write_jsonl(rel, fn(store.read_jsonl(rel)))


# ---------- golden ----------
def test_golden_byte_for_byte(spec_min: Spec, raw_store: RawStore, fixture_dir: Path) -> None:
    text = canonical_dumps(build_pack(spec_min, raw_store, version=1).pack)
    golden = fixture_dir / "pack_min.json"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.write_bytes(text.encode("utf-8"))
    assert text.encode("utf-8") == golden.read_bytes(), (
        "构建产物与 golden 不一致；确认变更合理后用 UPDATE_GOLDEN=1 更新"
    )


def test_build_is_deterministic_and_compact(spec_min: Spec, raw_store: RawStore) -> None:
    a = canonical_dumps(build_pack(spec_min, raw_store, version=1).pack)
    b = canonical_dumps(build_pack(spec_min, raw_store, version=1).pack)
    assert a == b
    assert a.endswith("}\n")
    assert ": " not in a.split("中")[0] and ", " not in a[:200]  # 紧凑分隔符
    keys = list(json.loads(a))
    assert keys == sorted(keys)  # 键排序
    assert "\n" not in a[:-1]


def test_fixture_sync_with_generator(tmp_path: Path, fixture_dir: Path) -> None:
    """夹具必须与生成脚本同步（改了脚本要重新生成并提交）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_fixture", fixture_dir / "make_replay_fixture.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import sys

    argv, sys.argv = sys.argv, ["make", "--out", str(tmp_path)]
    try:
        mod.main()
    finally:
        sys.argv = argv
    for sub in ("raw", "client"):
        for p in sorted((tmp_path / sub).rglob("*")):
            if p.is_file():
                rel = p.relative_to(tmp_path)
                assert p.read_bytes() == (fixture_dir / rel).read_bytes(), f"{rel} 与生成脚本不同步"
    assert (tmp_path / "spec_min.json").read_bytes() == (fixture_dir / "spec_min.json").read_bytes()


# ---------- 复权、除权、停牌、标志位 ----------
def test_pack_shape(pack_min: dict[str, Any]) -> None:
    p = pack_min
    assert (p["format"], p["format_version"], p["version"], p["kind"]) == (
        "stocksim-replay-pack",
        1,
        1,
        "curated",
    )
    assert len(p["calendar"]) == 25
    assert p["anchor_date"] == p["calendar"][LB - 1]
    assert all(len(rows) == 25 for rows in p["bars"].values())
    assert all(len(r) == 7 for rows in p["bars"].values() for r in rows)
    assert len(p["benchmark"]["closes_adj"]) == 25
    assert [s["key"] for s in p["stocks"]] == ["s1", "s2", "s3"]
    assert [s["alias_code"] for s in p["stocks"]] == ["990001", "990002", "990003"]
    assert [s["alias_name"] for s in p["stocks"]] == ["券商A", "券商B", "银行A"]
    assert p["stocks"][2]["real_name"] == "测试丙"  # 规格没写 name：回退到东财简称
    assert (
        p["provenance"]["built_at"] == "2024-01-01T00:00:00Z"
    )  # 取所读文件最大 fetched_at，不取墙钟
    assert p["provenance"]["akshare_version"] == "9.9.9-fixture"
    assert len(canonical_dumps(p).encode()) < 400 * 1024


def test_anchor_day_close_equals_raw_close(pack_min: dict[str, Any], fixture_dir: Path) -> None:
    store = RawStore(fixture_dir / "raw")
    for key, code in (("s1", "600001"), ("s2", "300001"), ("s3", "000001")):
        raw = {r["d"]: r for r in store.read_jsonl(rawstore.kline_path("none", code))}
        anchor = pack_min["anchor_date"]
        assert pack_min["bars"][key][LB - 1][3] == yuan_to_cents(raw[anchor]["c"])


def test_ex_rights_day_is_continuous_in_adjusted_space(
    pack_min: dict[str, Any], fixture_dir: Path
) -> None:
    raw = {
        r["d"]: r
        for r in RawStore(fixture_dir / "raw").read_jsonl(rawstore.kline_path("none", "600001"))
    }
    cal = pack_min["calendar"]
    ex_day, last_traded = cal[LB + 2], cal[LB + 0]  # 第 2 日除权，第 1 日停牌，前收取第 0 日
    raw_ratio = yuan_to_cents(raw[ex_day]["c"]) / yuan_to_cents(raw[last_traded]["c"])
    adj = pack_min["bars"]["s1"]
    adj_ratio = adj[LB + 2][3] / adj[LB + 0][3]
    assert raw_ratio < 0.95  # 原始价因分红下跌约 10%
    assert abs(adj_ratio - 1) < 0.06  # 复权后连续
    assert adj[LB + 2][6] & 32  # FLAG_EX_RIGHTS


def test_suspended_day_is_filled_with_prev_close(pack_min: dict[str, Any]) -> None:
    bars = pack_min["bars"]["s1"]
    c0 = bars[LB + 0][3]
    assert bars[LB + 1] == [c0, c0, c0, c0, 0, 1000, 1]


def test_limit_flags_and_percentages(pack_min: dict[str, Any]) -> None:
    s1, s2, s3 = (pack_min["bars"][k] for k in ("s1", "s2", "s3"))
    assert [s1[LB + d][6] for d in range(6)] == [0, 1, 32, 2 | 8, 0, 16]
    assert s1[LB + 3][:4] == [s1[LB + 3][3]] * 4  # 开盘一字涨停：o=h=l=c
    assert {r[5] for r in s1} == {1000}
    assert {r[5] for r in s2} == {2000}  # 创业板 2023 年为 20%
    assert {r[5] for r in s3} == {1000}
    assert s2[LB + 1][3] / s2[LB + 0][3] > 1.14  # +15% 的日子被接受且没有封板标志
    assert s2[LB + 1][6] == 0
    assert all(r[4] % 100 == 0 for r in s1)  # 成交量是股数（手 x 100）
    # hfq 因子带噪声的两只股票：没有误报除权，复权后的日收益 = 真实日收益
    assert all(not r[6] & 32 for r in s2 + s3)


def test_adjusted_returns_equal_raw_returns_when_hfq_is_noisy(
    pack_min: dict[str, Any], fixture_dir: Path
) -> None:
    store = RawStore(fixture_dir / "raw")
    for key, code in (("s2", "300001"), ("s3", "000001")):
        raw = {
            r["d"]: yuan_to_cents(r["c"])
            for r in store.read_jsonl(rawstore.kline_path("none", code))
        }
        cal, bars = pack_min["calendar"], pack_min["bars"][key]
        for i in range(1, len(cal)):
            raw_ret = raw[cal[i]] / raw[cal[i - 1]] - 1
            adj_ret = bars[i][3] / bars[i - 1][3] - 1
            assert abs(raw_ret - adj_ret) < 0.0006  # 仅剩价格取整到分的误差


def test_volume_is_lots_times_100_unadjusted(pack_min: dict[str, Any], fixture_dir: Path) -> None:
    raw = {
        r["d"]: r
        for r in RawStore(fixture_dir / "raw").read_jsonl(rawstore.kline_path("none", "600001"))
    }
    d = pack_min["calendar"][LB]
    assert pack_min["bars"]["s1"][LB][4] == raw[d]["v_lot"] * 100


def test_mask_scale_puts_day0_prev_close_in_10_to_50_yuan(pack_min: dict[str, Any]) -> None:
    for s in pack_min["stocks"]:
        anchor = pack_min["bars"][s["key"]][LB - 1][3]
        shown = round(anchor * s["mask_scale_ppm"] / 1_000_000)
        assert 1000 <= shown <= 5000


# ---------- 事件 ----------
def _by_title(pack: dict[str, Any], needle: str) -> list[dict[str, Any]]:
    return [e for e in pack["events"] if needle in e["title"]]


@pytest.mark.parametrize(
    ("needle", "day", "slot"),
    [
        ("重大销售合同", -2, "pre_open"),  # 巨潮只有日期：当日盘前
        ("减持股份计划", 0, "intraday"),  # 10:30
        ("生产线检修", 1, "post_close"),  # 16:20
        ("政府补助", 2, "pre_open"),  # 00:00:00 = 时刻未知
        ("业绩预告", 4, "pre_open"),  # 周六 -> 下一交易日盘前
        ("中标重大项目", 1, "pre_open"),  # 08:45
        ("国务院常务会议", -1, "pre_open"),  # 周日新闻联播 -> 下一交易日盘前
        ("央行宣布降准", 1, "post_close"),  # 交易日新闻联播 -> 盘后
        ("监管部门宣布", 4, "pre_open"),  # 周日 18:00 手写事件
        ("董事长接受采访", 2, "pre_open"),  # 09:00
        ("测试甲发布新品", 1, "post_close"),  # cls 16:05
        ("逆回购", 1, "intraday"),  # cls 10:15，空标题取内容前段
    ],
)
def test_event_slot_assignment(pack_min: dict[str, Any], needle: str, day: int, slot: str) -> None:
    (ev,) = [e for e in pack_min["events"] if needle in e["title"]]
    assert (ev["day_idx"], ev["slot"]) == (day, slot)


def test_event_filtering_and_dedup(pack_min: dict[str, Any]) -> None:
    titles = " ".join(e["title"] for e in pack_min["events"])
    assert "法律意见书" not in titles  # 例行公告被过滤
    assert "高温" not in titles  # 新闻联播未命中关键词
    assert "无关公司" not in titles  # 非关卡股票的公司动态
    assert len(_by_title(pack_min, "逆回购")) == 1  # cls 重复项只留一条
    assert len([e for e in pack_min["events"] if e["source"] == "gsrl"]) == 2


def test_event_ids_and_ordering(pack_min: dict[str, Any]) -> None:
    ev = pack_min["events"]
    assert [e["id"] for e in ev] == [f"e{i:04d}" for i in range(1, len(ev) + 1)]
    order = {"pre_open": 0, "intraday": 1, "post_close": 2}
    keys = [(e["day_idx"], order[e["slot"]]) for e in ev]
    assert keys == sorted(keys)


def test_event_fields(pack_min: dict[str, Any]) -> None:
    (contract,) = _by_title(pack_min, "重大销售合同")
    assert contract["source"] == "cninfo"
    assert (contract["kind"], contract["category"], contract["scope"]) == (
        "announcement",
        "contract",
        "stock",
    )
    assert contract["stock_keys"] == ["s1"]
    assert contract["industries"] == ["券商"]
    assert contract["published_at"] == "2023-06-29T16:00:00Z"  # 日期无时刻：按上海 00:00 换算
    assert contract["url"].startswith("http://www.cninfo.com.cn/")
    assert contract["sentiment"] is None
    (repair,) = _by_title(pack_min, "生产线检修")
    assert (repair["category"], repair["importance"]) == ("operation", 3)
    assert repair["local_time"] == "2023-07-05 16:20"
    (grant,) = _by_title(pack_min, "政府补助")
    assert (grant["category"], grant["importance"]) == ("other", 1)
    (policy,) = _by_title(pack_min, "监管部门宣布")
    assert (policy["scope"], policy["industries"], policy["importance"]) == (
        "industry",
        ["券商"],
        3,
    )
    assert policy["published_at"] == "2023-07-09T10:00:00Z"
    (cctv,) = _by_title(pack_min, "国务院常务会议")
    assert (cctv["kind"], cctv["scope"], cctv["source"]) == ("policy", "market", "cctv")
    assert cctv["local_time"] == "2023-07-02 19:00"
    pledge = [e for e in pack_min["events"] if e["category"] == "股份质押"]
    assert [e["stock_keys"] for e in pledge] == [["s3"]]  # 事件类型原样放进 category


def test_event_impact_present(pack_min: dict[str, Any]) -> None:
    for e in pack_min["events"]:
        assert set(e["impact"]) == {"ar_1d_bp", "ar_5d_bp"}
    (e,) = _by_title(pack_min, "重大销售合同")
    assert isinstance(e["impact"]["ar_1d_bp"], int)


# ---------- 脱敏 ----------
def test_masked_fields_contain_no_real_names_or_codes(
    pack_min: dict[str, Any], spec_min: Spec
) -> None:
    terms = {t for s in spec_min.stocks for t in s.redact_terms}
    terms |= {s["real_name"] for s in pack_min["stocks"]} | {
        s["real_code"] for s in pack_min["stocks"]
    }
    texts = [e[f] for e in pack_min["events"] for f in ("title_masked", "body_masked")] + [
        q["prompt_masked"] for q in pack_min["questions"]
    ]
    for text in texts:
        assert not [t for t in terms if t in text], text


def test_masked_dates_are_scrubbed_and_alias_used(pack_min: dict[str, Any]) -> None:
    (cctv,) = _by_title(pack_min, "国务院常务会议")
    assert "2023" not in cctv["title_masked"] + cctv["body_masked"].replace("2019", "")
    assert cctv["body_masked"].startswith("近日，国务院常务会议召开")
    (e,) = _by_title(pack_min, "业绩预告")
    assert e["title_masked"] == "券商A半年度业绩预告"
    (policy,) = _by_title(pack_min, "监管部门宣布")
    assert policy["title_masked"] == "监管部门宣布行业交易成本下调"  # 作者给的匿名标题
    assert (
        policy["body_masked"] == "近日晚，监管部门发布公告。（合成数据）"
    )  # 无匿名正文则由原文脱敏


def test_hide_in_masked_flag(pack_min: dict[str, Any]) -> None:
    hidden = [e for e in pack_min["events"] if e["hide_in_masked"]]
    assert [e["title"] for e in hidden] == ["测试甲董事长接受采访"]


def test_redaction_report_lists_residual_year_digits(pack_min: dict[str, Any]) -> None:
    (cctv,) = _by_title(pack_min, "国务院常务会议")
    assert pack_min["redaction_report"] == [
        {"event_id": cctv["id"], "field": "body_masked", "hit": "2019"}
    ]


def test_provenance_hashes_every_raw_file_read(pack_min: dict[str, Any], fixture_dir: Path) -> None:
    files = pack_min["provenance"]["raw_files"]
    assert list(files) == sorted(files)
    assert "calendar/trade_dates.json" in files
    assert "kline/hfq/600001.jsonl" in files
    assert "cls/2023-07/2023-07-05.jsonl" in files
    store = RawStore(fixture_dir / "raw")
    assert all(store.sha256(rel) == sha for rel, sha in files.items())


# ---------- 构建失败 ----------
def test_limit_violation_fails_build(spec_min: Spec, raw_store: RawStore) -> None:
    def bump(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in rows:
            if r["d"] == "2023-07-12":  # 000001（主板）当日 +30%
                prev = max(float(x["c"]) for x in rows if x["d"] == "2023-07-11")
                r.update(
                    o=str(prev),
                    l=str(prev),
                    c=str(round(prev * 1.3, 2)),
                    h=str(round(prev * 1.3, 2)),
                )
        return rows

    for adjust in ("none", "hfq"):
        _rewrite_kline(raw_store, adjust, "000001", bump)
    with pytest.raises(BuildError, match="涨跌幅超出"):
        build_pack(spec_min, raw_store, version=1)


def test_wrong_board_rule_fails_build(fixture_dir: Path, raw_store: RawStore) -> None:
    """把创业板股票当成主板：+15% 的日子在 10% 规则下必须被拒绝。"""
    d = _spec_dict(fixture_dir)
    d["stocks"][1]["code"] = "000002"  # 主板规则 10%
    d["questions"][1]["codes"] = ["600001", "000002", "000001"]
    for adjust in ("none", "hfq"):
        raw_store.write_jsonl(
            rawstore.kline_path(adjust, "000002"),
            raw_store.read_jsonl(rawstore.kline_path(adjust, "300001")),
        )
    with pytest.raises(BuildError, match="涨跌幅超出"):
        build_pack(parse_spec(d), raw_store, version=1)


def test_missing_calendar(spec_min: Spec, empty_store: RawStore) -> None:
    with pytest.raises(BuildError, match="日历"):
        build_pack(spec_min, empty_store, version=1)


def test_d0_not_a_trading_day(fixture_dir: Path, raw_store: RawStore) -> None:
    d = _spec_dict(fixture_dir)
    d["d0"] = "2023-07-08"  # 周六
    with pytest.raises(BuildError, match="不是交易日"):
        build_pack(parse_spec(d), raw_store, version=1)


def test_calendar_must_cover_reveal_period(fixture_dir: Path, raw_store: RawStore) -> None:
    d = _spec_dict(fixture_dir)
    d["reveal_days"] = 40
    with pytest.raises(BuildError, match="揭示期"):
        build_pack(parse_spec(d), raw_store, version=1)


def test_missing_kline_and_index(spec_min: Spec, raw_store: RawStore) -> None:
    (raw_store.root / "index" / "000300.jsonl").unlink()
    with pytest.raises(BuildError, match="基准指数"):
        build_pack(spec_min, raw_store, version=1)
    (raw_store.root / "kline" / "none" / "300001.jsonl").unlink()
    with pytest.raises(BuildError, match="日 K"):
        build_pack(spec_min, raw_store, version=1)


def test_index_gap_fails(spec_min: Spec, raw_store: RawStore) -> None:
    rel = rawstore.index_path("000300")
    rows = raw_store.read_jsonl(rel)
    raw_store.write_jsonl(rel, rows[:5] + rows[6:])
    with pytest.raises(BuildError, match="基准指数缺少"):
        build_pack(spec_min, raw_store, version=1)


def test_none_and_hfq_dates_must_match(spec_min: Spec, raw_store: RawStore) -> None:
    _rewrite_kline(raw_store, "hfq", "300001", lambda rows: rows[:-1])
    with pytest.raises(BuildError, match="不一致"):
        build_pack(spec_min, raw_store, version=1)


def test_no_history_before_window_rejects_new_listing(spec_min: Spec, raw_store: RawStore) -> None:
    for adjust in ("none", "hfq"):
        _rewrite_kline(
            raw_store, adjust, "300001", lambda rows: [r for r in rows if r["d"] > "2023-06-30"]
        )
    with pytest.raises(BuildError, match="上市前"):
        build_pack(spec_min, raw_store, version=1)


def test_stock_name_unknown_requires_spec_name(fixture_dir: Path, raw_store: RawStore) -> None:
    d = _spec_dict(fixture_dir)
    d["sources"].update(cninfo=False, gsrl=False)
    shutil.rmtree(raw_store.root / "cninfo")  # 回退用的简称来源也不存在
    shutil.rmtree(raw_store.root / "gsrl")
    with pytest.raises(BuildError, match="简称"):
        build_pack(parse_spec(d), raw_store, version=1)


def test_unsupported_source_and_bad_version(
    fixture_dir: Path, spec_min: Spec, raw_store: RawStore
) -> None:
    d = _spec_dict(fixture_dir)
    d["sources"]["em_news"] = True
    with pytest.raises(BuildError, match="em_news"):
        build_pack(parse_spec(d), raw_store, version=1)
    with pytest.raises(BuildError, match="version"):
        build_pack(spec_min, raw_store, version=0)


def test_manual_event_outside_window_fails(fixture_dir: Path, raw_store: RawStore) -> None:
    d = _spec_dict(fixture_dir)
    d["manual_events"][0]["local_time"] = "2023-07-25 10:00"
    with pytest.raises(BuildError, match="不在关卡窗口"):
        build_pack(parse_spec(d), raw_store, version=1)


def test_cninfo_rule_override_from_spec(fixture_dir: Path, raw_store: RawStore) -> None:
    d = _spec_dict(fixture_dir)
    d["sources"]["cninfo"] = {"drop": ["政府补助"]}  # 整体替换默认例行规则
    pack = build_pack(parse_spec(d), raw_store, version=1).pack
    titles = " ".join(e["title"] for e in pack["events"])
    assert "政府补助" not in titles
    assert "法律意见书" in titles  # 默认规则被替换，法律意见书不再过滤
    d["sources"]["cninfo"] = {"drop_extra": ["政府补助"]}  # 追加
    titles = " ".join(
        e["title"] for e in build_pack(parse_spec(d), raw_store, version=1).pack["events"]
    )
    assert "政府补助" not in titles
    assert "法律意见书" not in titles


def test_built_at_override(spec_min: Spec, raw_store: RawStore) -> None:
    pack = build_pack(spec_min, raw_store, version=3, built_at="2025-01-01T00:00:00Z").pack
    assert pack["provenance"]["built_at"] == "2025-01-01T00:00:00Z"
    assert pack["version"] == 3


def test_warnings_list_detected_ex_rights_days(spec_min: Spec, raw_store: RawStore) -> None:
    warnings = build_pack(spec_min, raw_store, version=1).warnings
    assert len(warnings) == 1  # 没有并列告警；噪声较大的 300001/000001 没有被误报为除权
    assert warnings[0].startswith("600001: 检测到除权/复权跳变 2023-07-06")


# ---------- CLI: build / verify ----------
def test_cli_build_refuses_to_overwrite_different_content(
    fixture_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "v1.json"
    base = [
        "--data-dir",
        str(fixture_dir / "raw"),
        "build",
        "--spec",
        str(fixture_dir / "spec_min.json"),
        "--out",
        str(out),
    ]
    assert cli.run([*base, "--version", "1"]) == 0
    assert out.read_bytes() == (fixture_dir / "pack_min.json").read_bytes()  # 与 golden 一致
    assert cli.run([*base, "--version", "1"]) == 0  # 内容相同：幂等
    assert (
        cli.run([*base, "--version", "1", "--built-at", "2030-01-01T00:00:00Z"]) == 1
    )  # 内容不同：拒绝
    assert "提升 --version" in capsys.readouterr().err
    assert cli.run([*base[:-1], str(tmp_path / "v2.json"), "--version", "2"]) == 0
    assert cli.run([*base, "--version", "2", "--overwrite"]) == 0


def test_cli_build_surfaces_errors(
    fixture_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.run(
        [
            "--data-dir",
            str(tmp_path / "empty"),
            "build",
            "--spec",
            str(fixture_dir / "spec_min.json"),
            "--out",
            str(tmp_path / "x.json"),
            "--version",
            "1",
        ]
    )
    assert code == 1
    assert "日历" in capsys.readouterr().err
    assert not (tmp_path / "x.json").exists()


def test_deep_copy_helper_not_mutating_session_pack(pack_min: dict[str, Any]) -> None:
    assert copy.deepcopy(pack_min) == pack_min
