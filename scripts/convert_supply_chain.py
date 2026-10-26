"""把 docs/10.26-plan/01a-产业链草稿.md 的边表转换为 backend/src/stocksim/data/supply_chain.json。

用法：
    python3 scripts/convert_supply_chain.py          # 解析 -> 校验 -> 写 JSON（幂等）
    python3 scripts/convert_supply_chain.py --check  # 只校验源表，并检查 JSON 是否最新（不写文件）
    python3 scripts/convert_supply_chain.py --to-md  # 把现有 JSON 反向输出为 markdown 表（stdout）

人工校对 01a 后直接重跑即可。只做格式转换，不重新解释任何字段（语义见 01a §1 与 01 §5.2）。
纯标准库。校验失败时按“行号: 原因”逐条列出并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "docs" / "10.26-plan" / "01a-产业链草稿.md"
DEFAULT_OUT = ROOT / "backend" / "src" / "stocksim" / "data" / "supply_chain.json"
INDUSTRIES = ROOT / "backend" / "src" / "stocksim" / "data" / "industries.json"

VERSION = 1
HEADER = ("上游", "下游", "关系类型", "正负", "强度", "滞后", "说明")
MAX_LAYER = 5

RELATION_ALIASES = {
    "supply": "supply",
    "供应": "supply",
    "供货": "supply",
    "demand": "demand",
    "需求": "demand",
    "需求拉动": "demand",
    "substitute": "substitute",
    "替代": "substitute",
    "same_theme": "same_theme",
    "同题材": "same_theme",
    "题材": "same_theme",
}
SIGN_ALIASES = {
    "+": 1,
    "正": 1,
    "+1": 1,
    "利好": 1,
    "-": -1,
    "−": -1,  # Unicode 减号
    "负": -1,
    "-1": -1,
    "利空": -1,
}
REQUIRED_SIGN = {"substitute": -1, "same_theme": 1}  # 01 §7.1


class ValidationFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def load_industries(path: Path = INDUSTRIES) -> list[str]:
    return [item["name"] for item in json.loads(path.read_text(encoding="utf-8"))]


def _cell(text: str) -> str:
    return text.strip().replace("`", "").strip()


def parse_markdown(text: str) -> list[tuple[int, list[str]]]:
    """返回 [(行号, 7 个单元格)]。只认表头严格等于 HEADER 的表，允许多张。"""
    rows: list[tuple[int, list[str]]] = []
    in_table = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [_cell(c) for c in stripped.strip("|").split("|")]
        if not in_table:
            if tuple(cells) == HEADER:
                in_table = True
            continue
        if all(set(c) <= set("-: ") for c in cells):  # 分隔行
            continue
        rows.append((lineno, cells))
    return rows


def normalize(
    rows: list[tuple[int, list[str]]], industries: list[str]
) -> tuple[list[dict], list[str], list[str]]:
    """返回 (edges, errors, warnings)。edges 已按 (from 下标, to 下标) 排序。"""
    index = {name: i for i, name in enumerate(industries)}
    errors: list[str] = []
    warnings: list[str] = []
    edges: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    seen_pair: dict[frozenset[str], int] = {}
    for lineno, cells in rows:
        if len(cells) != len(HEADER):
            errors.append(
                f"{lineno}: 列数应为 {len(HEADER)}，实际 {len(cells)}（说明里是否含 '|'？）"
            )
            continue
        src, dst, rel_raw, sign_raw, strength_raw, lag_raw, note = cells
        ok = True
        for name in (src, dst):
            if name not in index:
                errors.append(f"{lineno}: 行业 {name!r} 不在 industries.json 的 82 个标签内")
                ok = False
        if src == dst:
            errors.append(f"{lineno}: 自环 {src}")
            ok = False
        relation = RELATION_ALIASES.get(rel_raw)
        if relation is None:
            errors.append(f"{lineno}: 未知关系类型 {rel_raw!r}")
            ok = False
        sign = SIGN_ALIASES.get(sign_raw)
        if sign is None:
            errors.append(f"{lineno}: 未知正负 {sign_raw!r}")
            ok = False
        strength = int(strength_raw) if strength_raw.isdecimal() else -1
        if strength not in (1, 2, 3):
            errors.append(f"{lineno}: 强度应为 1-3，实际 {strength_raw!r}")
            ok = False
        lag_text = lag_raw.removesuffix("日").removesuffix("天").strip()
        lag = int(lag_text) if lag_text.isdecimal() else -1
        if not 0 <= lag <= 5:
            errors.append(f"{lineno}: 滞后应为 0-5，实际 {lag_raw!r}")
            ok = False
        if relation in REQUIRED_SIGN and sign is not None and sign != REQUIRED_SIGN[relation]:
            errors.append(f"{lineno}: {relation} 的正负必须是 {REQUIRED_SIGN[relation]:+d}")
            ok = False
        if not ok:
            continue
        key = (src, dst)
        if key in seen:
            errors.append(f"{lineno}: ({src}, {dst}) 与第 {seen[key]} 行重复")
            continue
        pair = frozenset(key)
        if pair in seen_pair:
            errors.append(
                f"{lineno}: ({src}, {dst}) 与第 {seen_pair[pair]} 行是同一对行业的反向重复"
                "（每对行业只保留一个主导机制）"
            )
            continue
        seen[key] = lineno
        seen_pair[pair] = lineno
        edges.append(
            {
                "id": f"{src}>{dst}",
                "from": src,
                "to": dst,
                "relation": relation,
                "sign": sign,
                "strength": strength,
                "lag_days": lag,
                "note": note,
            }
        )
    edges.sort(key=lambda e: (index[e["from"]], index[e["to"]]))
    used = {e["from"] for e in edges} | {e["to"] for e in edges}
    for name in industries:
        if name not in used:
            warnings.append(f"行业 {name!r} 没有出现在任何边上（传导时会成为孤岛）")
    return edges, errors, warnings


def compute_layers(industries: list[str], edges: list[dict]) -> dict[str, int]:
    """沿 supply/demand 边（均按 from=上游 -> to=下游）取最长路径深度，上限 MAX_LAYER。

    在 industries.json 顺序下做 DFS，遇到回边（指向栈上节点的边）忽略；结果只用于前端分栏布局。
    """
    index = {name: i for i, name in enumerate(industries)}
    out: dict[str, list[str]] = {name: [] for name in industries}
    for e in edges:
        if e["relation"] in ("supply", "demand"):
            out[e["from"]].append(e["to"])
    for name in out:
        out[name].sort(key=index.__getitem__)

    state: dict[str, int] = {}  # 1 = 在栈上, 2 = 完成
    dag_out: dict[str, list[str]] = {name: [] for name in industries}
    for root in industries:
        if root in state:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        state[root] = 1
        while stack:
            node, pos = stack.pop()
            if pos < len(out[node]):
                stack.append((node, pos + 1))
                nxt = out[node][pos]
                if state.get(nxt) == 1:
                    continue  # 回边，忽略
                dag_out[node].append(nxt)
                if nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, 0))
            else:
                state[node] = 2

    indeg = {name: 0 for name in industries}
    for u in industries:
        for v in dag_out[u]:
            indeg[v] += 1
    queue = [n for n in industries if indeg[n] == 0]
    depth = {n: 0 for n in industries}
    while queue:
        u = queue.pop(0)
        for v in dag_out[u]:
            depth[v] = max(depth[v], depth[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return {n: min(depth[n], MAX_LAYER) for n in industries}


def build_json(industries: list[str], edges: list[dict]) -> dict:
    layers = compute_layers(industries, edges)
    return {
        "version": VERSION,
        "nodes": [{"id": name, "layer": layers[name]} for name in industries],
        "edges": edges,
    }


def dumps(data: dict) -> str:
    """每个 node / edge 一行，便于 diff 与人工审阅。"""
    lines = ["{", f'  "version": {data["version"]},', '  "nodes": [']
    nodes = [json.dumps(n, ensure_ascii=False) for n in data["nodes"]]
    lines += [f"    {n}{',' if i < len(nodes) - 1 else ''}" for i, n in enumerate(nodes)]
    lines += ["  ],", '  "edges": [']
    edges = [json.dumps(e, ensure_ascii=False) for e in data["edges"]]
    lines += [f"    {e}{',' if i < len(edges) - 1 else ''}" for i, e in enumerate(edges)]
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def render_md(data: dict) -> str:
    out = ["| " + " | ".join(HEADER) + " |", "| " + " | ".join("---" for _ in HEADER) + " |"]
    for e in data["edges"]:
        sign = "+" if e["sign"] == 1 else "-"
        cells = [e["from"], e["to"], e["relation"], sign, str(e["strength"]), str(e["lag_days"])]
        out.append("| " + " | ".join([*cells, e["note"]]) + " |")
    return "\n".join(out) + "\n"


def convert_text(text: str, industries: list[str]) -> tuple[dict, list[str]]:
    """md 文本 -> (JSON 对象, 警告)。校验失败抛 ValidationFailed。"""
    rows = parse_markdown(text)
    if not rows:
        raise ValidationFailed(
            ["未找到表头为 '| 上游 | 下游 | 关系类型 | 正负 | 强度 | 滞后 | 说明 |' 的表"]
        )
    edges, errors, warnings = normalize(rows, industries)
    if errors:
        raise ValidationFailed(errors)
    return build_json(industries, edges), warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument(
        "--to-md", action="store_true", help="把 --out 的 JSON 反向输出为 markdown 表"
    )
    args = parser.parse_args(argv)

    if args.to_md:
        sys.stdout.write(render_md(json.loads(args.out.read_text(encoding="utf-8"))))
        return 0

    industries = load_industries()
    try:
        data, warnings = convert_text(args.src.read_text(encoding="utf-8"), industries)
    except ValidationFailed as exc:
        for err in exc.errors:
            print(f"ERROR {args.src.name}:{err}", file=sys.stderr)
        return 1
    for warn in warnings:
        print(f"WARN {warn}", file=sys.stderr)
    rendered = dumps(data)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != rendered:
            print(
                f"ERROR {args.out} 与源表不一致，请运行 python3 scripts/convert_supply_chain.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK {len(data['nodes'])} nodes, {len(data['edges'])} edges")
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out} ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
