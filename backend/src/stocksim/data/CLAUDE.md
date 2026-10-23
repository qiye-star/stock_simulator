# data（静态股票池）— 给 agent 的说明

## 边界
- 只放静态 JSON，由 `scripts/convert_stockdata.py` 从 `legacy/stockData.js` 生成。不要手改后忘记同步脚本；需要改数据请改脚本的输入或脚本本身后重跑。
- 服务层读取这些文件（domain 不做 I/O）。

## 文件
- `stock_pool.json`：385 只股票，字段 `code`（6 位字符串）、`name`、`industry`、`profile`。
  - `profile`：`normal` 或 `bull_bias`（仅 999999 影视飓风，行情偏多头）。
  - 列表顺序即 `stock_idx`（RNG 维度），**不得随意重排**，否则行情不可复现。
- `industries.json`：82 个行业，字段 `name`、`stock_count`、`base_price_range_yuan`（[lo, hi] 元，来自 legacy generateBasePrice；未列出的行业用默认 [5, 100]）。

## 常见任务
- 增删股票：改 legacy 源（只读，不建议）或脚本；重跑脚本，断言数量（当前 385）。
- 调整行业价格区间：改脚本中 LEGACY_RANGES_YUAN 并重跑。

## 验证
`cd backend && uv run pytest tests/unit/data -q`；生成：`python3 scripts/convert_stockdata.py`
