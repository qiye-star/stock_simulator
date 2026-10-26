# data（静态股票池）— 给 agent 的说明

## 边界
- 只放静态 JSON，由 `scripts/convert_stockdata.py` 从 `legacy/stockData.js` 生成。不要手改后忘记同步脚本；需要改数据请改脚本的输入或脚本本身后重跑。
- 服务层读取这些文件（domain 不做 I/O）。

## 文件
- `stock_pool.json`：385 只股票，字段 `code`（6 位字符串）、`name`、`industry`、`profile`。
  - `profile`：`normal` 或 `bull_bias`（仅 999999 影视飓风，行情偏多头）。
  - 列表顺序即 `stock_idx`（RNG 维度），**不得随意重排**，否则行情不可复现。
- `industries.json`：82 个行业，字段 `name`、`stock_count`、`base_price_range_yuan`（[lo, hi] 元，来自 legacy generateBasePrice；未列出的行业用默认 [5, 100]）。

- 事件行情数据（01 §7，**由脚本生成，不要手改**；改源后重跑脚本并提交产物）：
  - `supply_chain.json`：82 个行业节点（顺序同 `industries.json`，`layer` 0–5 仅用于布局）+ 行业级边（`from`=上游列，`to`=下游列，`relation/sign/strength/lag_days/note`）。来源 `docs/10.26-plan/01a-产业链草稿.md`，脚本 `scripts/convert_supply_chain.py`。语义以 01a §1 为准：supply 沿 from→to 传，demand 沿 to→from 传，substitute/same_theme 双向。
  - `stock_exposure.json`：385 只全部列出，`leader` 与 `extra`（≤2 项、≤50 万 ppm、不含主行业），脚本 `scripts/build_stock_exposure.py`（覆盖文件 `scripts/stock_exposure_overrides.json`）。
  - `news_templates.json`：新闻文案模板与槽位，脚本 `scripts/news/build_templates.py`（源 `scripts/news/templates_src.json`）。
  - 三份顶层 `version` 必须等于 `domain/events/constants.py::EVENT_RULESET_VERSION`。发布后任何改动都要提升版本并冻结旧版（01 §6.6）；发布前（开发期）可自由修改。
  - 01a 草稿尚未人工校对，边的方向/符号/强度可能调整；调整后重跑脚本，并用 `scripts/event_sim_report.py` 复核指标。

## 常见任务
- 增删股票：改 legacy 源（只读，不建议）或脚本；重跑脚本，断言数量（当前 385）。
- 调整行业价格区间：改脚本中 LEGACY_RANGES_YUAN 并重跑。
- 修正股票名称：在 `scripts/convert_stockdata.py` 的 `NAME_OVERRIDES` 加一行并重跑（legacy 只读）。2026-10-26 起 000938 为“紫光股份”（决策 19）；改名后金值需重采，见 tests/unit/domain 金值文件注释。

## 验证
`cd backend && uv run pytest tests/unit/data -q`；生成：`python3 scripts/convert_stockdata.py`、`python3 scripts/convert_supply_chain.py`、`python3 scripts/build_stock_exposure.py`、`python3 scripts/news/build_templates.py`
