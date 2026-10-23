# tests/unit/domain（领域层测试）— 给 agent 的说明

- 对应 `backend/src/stocksim/domain/`，每个源文件一个测试文件（test_<模块>.py）。
- 撮合规则的关键用例：限价修复（test_matching.py 的 limit_* 用例）、T+1（t1_* 用例）、手续费舍入（fee_*）。改撮合时必须同时更新这些用例并说明原因。
- 行情测试较慢的部分使用 `SUBSET` 小样本；全量 385 只股票的初始化只在必要处使用，避免测试变慢。
- 统计类测试（bull_bias、normal 对称性）使用固定种子范围，结果是确定的，不应出现随机失败。
- 运行：`cd backend && uv run pytest tests/unit/domain -q`（必要时加 `--noconftest`）。
