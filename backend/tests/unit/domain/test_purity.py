"""领域层纯度守卫：禁止 I/O、框架、全局随机与墙上时钟（见 domain/CLAUDE.md）。"""

import ast
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[3] / "src" / "stocksim" / "domain"
FORBIDDEN_MODULES = {
    "sqlalchemy",
    "fastapi",
    "starlette",
    "pydantic",
    "random",
    "time",
    "os",
    "sys",
    "pathlib",
    "io",
    "json",
    "socket",
    "subprocess",
    "logging",
    "sqlite3",
    "httpx",
    "requests",
    "uuid",
    "secrets",
}
FORBIDDEN_ATTRS = {"now", "today", "utcnow", "utcfromtimestamp", "time", "random", "uuid4"}
FORBIDDEN_CALLS = {"open", "print", "input"}


def _modules():
    return sorted(DOMAIN.rglob("*.py"))


def test_domain_has_python_files():
    assert len(_modules()) >= 15


def test_no_forbidden_imports():
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in FORBIDDEN_MODULES, f"{path.name} imports {name}"


def test_no_clock_random_or_io_calls():
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_ATTRS, f"{path.name}: .{node.attr}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_CALLS, f"{path.name}: {node.func.id}()"
