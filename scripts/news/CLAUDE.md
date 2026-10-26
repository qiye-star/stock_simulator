# scripts/news（离线文案流水线）— 给 agent 的说明

把真实公告/快讯标题提炼成“模板 + 槽位”，生成游戏用的 `backend/src/stocksim/data/news_templates.json`。**运行时不联网、不调 LLM**，这里的脚本都是离线工具。

## 流程
1. `fetch_akshare_titles.py`（手动，需 akshare）：`uv run --with akshare python scripts/news/fetch_akshare_titles.py --days 60` → `corpus/*.jsonl`（已 `.gitignore`，不提交）。未在本仓库环境实测过，接口改名时按告警调整。
2. `extract_patterns.py`（纯标准库）：把股票名/行业/地区/数字替换成槽位，按句式聚类并按关键词猜 DuEE-fin subtype → `pattern_candidates.json`（已忽略）。
3. 人工（或一次性 LLM）从候选里挑句式，写进 `templates_src.json`（提交到仓库，**只保留句式，不保留原文标题**）。
4. `build_templates.py`（纯标准库）：校验并按 id 排序，写出 `data/news_templates.json`；`--check` 只校验并检查产物是否最新。

## 不变量
- 约束（01 §7.4）：rumor 必须有 confirm 与 deny；`can_price_in` 必须有 precursor；每个会被抽到的 (kind, tier) 至少 3 条；13 个公告 subtype 各至少 2 条且 sign 与默认一致；槽位只能用 `{stock}{code}{industry}{pct}{amount}` 与 `slot_values` 的键；scope=market 不能用行业/股票槽位；每个槽位的每个取值都必须能渲染。
- `{pct}`（5–30）与 `{amount}`（1–50 亿）独立抽取，与事件幅度无关，别写成暗示幅度的措辞。
- en-US 允许为 null，缺失时界面退回中文。
- `build_templates.py` 的 `DRAWN_COMBOS` 必须与 `domain/events/constants.py` 的 `KIND_WEIGHTS_*` 一致（`tests/unit/data/test_event_data_files.py` 有断言）。
- 改了 `templates_src.json` 必须重跑 `build_templates.py` 并提交产物；已发布后的改动需提升规则集版本（01 §6.6）。

## 验证
`python3 scripts/news/build_templates.py --check && cd backend && uv run pytest tests/unit/data -q`
