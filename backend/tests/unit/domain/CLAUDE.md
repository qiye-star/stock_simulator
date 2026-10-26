# tests/unit/domain（领域层测试）— 给 agent 的说明

- 对应 `backend/src/stocksim/domain/`，每个源文件一个测试文件（test_<模块>.py）。
- 撮合规则的关键用例：限价修复（test_matching.py 的 limit_* 用例）、T+1（t1_* 用例）、手续费舍入（fee_*）。改撮合时必须同时更新这些用例并说明原因。
- 行情测试较慢的部分使用 `SUBSET` 小样本；全量 385 只股票的初始化只在必要处使用，避免测试变慢。
- 统计类测试（bull_bias、normal 对称性）使用固定种子范围，结果是确定的，不应出现随机失败。
- 事件行情测试 `test_events_*.py` 覆盖 `domain/events/`；`conftest.py` 的夹具从 `data/*.json` 构造规则集。`test_market_engine_golden.py` 金值禁止修改。
- 时钟 v2：`test_clock_v2*.py`、`test_market_engine_v2*.py`。v2 金值在对外发布后冻结，之后只能新增 `clock_rules=3`；v2 常量调整必须先跑 `scripts/clock_v2_sim_report.py --check`，再重采金值（且只在未发布前）。
- 运行：`cd backend && uv run pytest tests/unit/domain -q`（必要时加 `--noconftest`）。
- 预测卡（02）：`test_scoring.py`（RPS/NDCG/基线/同伴/校准的示例值与边界）、`test_prediction_questions.py`（档位 v1/v2 表、时钟换算、确定性、候选规则、公开 JSON 白名单、答案校验）、`test_prediction_titles.py`（称号边界与统计口径）、`test_prediction_rng_layout.py`（预测段与 A/T 段无碰撞）。
- 真实复盘纯函数：`test_replay.py`（阶段与位置、事件可见性真值表 3×4、缩放与夹紧、20% 板块、阶段报价、标志位、收益率）；`test_rules.py` / `test_matching.py` 增补可选板块涨跌幅用例（默认 10% 路径不变）。
