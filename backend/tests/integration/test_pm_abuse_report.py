"""风控报表脚本（scripts/pm_abuse_report.py，04 §12 第 12 步）。

样本检出 + 真实 schema 上的读库 SQL。
"""

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "pm_abuse_report.py"


def _module():
    spec = importlib.util.spec_from_file_location("pm_abuse_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclass 需要模块已注册
    spec.loader.exec_module(mod)
    return mod


def test_sample_cheats_are_detected_and_clean_accounts_are_not():
    mod = _module()
    trades, users, expected = mod.sample()
    rows = mod.detect(trades, users)
    hit = {r["username"]: set(r["flags"].split("|")) for r in rows}
    for name, flags in expected.items():
        assert flags <= hit.get(name, set()), (name, hit.get(name))
    assert not [name for name in hit if name.startswith("clean")]


def test_each_rule_fires_on_its_own_sample():
    mod = _module()
    trades, users, _ = mod.sample()
    # 只保留 cheat 的成交：只应命中往返
    only_cheat = [t for t in trades if t.user_id == "cheat"]
    assert {r["flags"] for r in mod.detect(only_cheat, users)} == {"往返"}
    # 只保留 insider：只应命中胜率异常
    only_insider = [t for t in trades if t.user_id == "insider"]
    assert {r["flags"] for r in mod.detect(only_insider, users)} == {"胜率异常"}


def test_run_sample_exit_code_zero():
    assert _module().run_sample() == 0


def test_load_sql_matches_migrated_schema(migrated: str):
    """在 alembic 迁移后的真实 schema 上执行读库 SQL（空库，结果为空即可）。"""
    mod = _module()
    trades, users = mod.load(migrated)
    assert trades == [] and users == {}
    trades, users = mod.load(migrated, challenge_id="00000000-0000-0000-0000-000000000000")
    assert trades == [] and users == {}
