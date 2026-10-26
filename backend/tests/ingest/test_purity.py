"""隔离性：只有 client.py 导入 akshare；构建器不联网、不导入 akshare 与 stocksim 其它子包。"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "src" / "stocksim" / "replay_ingest"
MODULES = sorted(p for p in PKG.glob("*.py"))
THIRD_PARTY = {
    "akshare",
    "pandas",
    "numpy",
    "requests",
    "curl_cffi",
    "transformers",
    "torch",
    "bs4",
}
RUNTIME_PACKAGES = {"models", "services", "api", "db", "core", "schemas", "domain", "data"}


def _imports(path: Path) -> set[str]:
    """返回模块里所有导入的顶层模块名；相对导入记为 ``.<名>``。"""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add("." + (node.module or "").split(".")[0])
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_only_client_imports_third_party(path: Path) -> None:
    found = _imports(path) & THIRD_PARTY
    if path.name == "client.py":
        assert found <= {"akshare"}, f"client.py 只允许延迟导入 akshare，实际 {found}"
    else:
        assert not found, f"{path.name} 不得导入 {found}"


def test_akshare_import_is_lazy_in_client() -> None:
    tree = ast.parse((PKG / "client.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    assert not any(
        getattr(n, "module", None) == "akshare"
        or any(a.name == "akshare" for a in getattr(n, "names", []))
        for n in top_level
    ), "akshare 必须在 AkshareClient.__init__ 里延迟导入"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_dependency_on_runtime_packages(path: Path) -> None:
    imports = _imports(path)
    assert "stocksim" not in imports or path.name == "__main__.py"
    assert not {i for i in imports if i.startswith(".") and i[1:] in RUNTIME_PACKAGES}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            assert not node.module.startswith("stocksim."), f"{path.name} 不得导入 {node.module}"
        if isinstance(node, ast.ImportFrom) and node.level >= 2:
            raise AssertionError(f"{path.name} 不得向上越出 replay_ingest 包: {node.module}")


def test_importing_builder_does_not_load_akshare_or_runtime_code() -> None:
    code = (
        "import sys\n"
        "import stocksim.replay_ingest.build, stocksim.replay_ingest.verify, "
        "stocksim.replay_ingest.fetch, stocksim.replay_ingest.cli\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "{'akshare','pandas','numpy','requests','curl_cffi','sqlalchemy','fastapi'}]\n"
        "bad += [m for m in sys.modules if m.startswith('stocksim.') and "
        "not m.startswith('stocksim.replay_ingest')]\n"
        "assert not bad, bad\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
