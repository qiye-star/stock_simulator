# tests/unit（单元测试）— 给 agent 的说明

- 只测纯逻辑：`domain/`（规则、行情、撮合、自动交易、成就）与 `data/`（静态 JSON 完整性）。不起数据库、不起 FastAPI。
- 金定值（RNG）是行为契约：`domain/test_rng.py` 中的数值只能在规范变更时整体更新，禁止为通过测试而改断言。`domain/test_market_engine_golden.py` 的 sha256 是在加入事件漂移前用旧引擎采集的，`advance` 不传 drift（或 None/空）必须与之逐位一致，同样禁止修改。
- `domain/test_purity.py` 扫描 domain 源码，禁止 I/O、框架、随机与墙上时钟。
- 测试用 `Path(__file__)` 定位 `src/stocksim/data`，不依赖工作目录。
- 测试模块名必须全局唯一（pytest 默认导入模式）。

## 文件
- `domain/`：test_rng / test_money / test_clock / test_rules / test_market_engine / test_market_engine_golden / test_matching / test_auto_trade / test_achievements / test_purity
  - 事件行情：test_events_rng_layout / test_events_generate / test_events_propagation / test_events_path / test_events_plan / test_events_timing / test_events_reveal；`conftest.py` 提供 `event_ruleset`（20 tick/日）与 `event_ruleset_v2`（242 tick/日）夹具
  - 预测市场（04 §11.1）：test_pm_lmsr（价格和为 1、单调（±1 ppm）、补贴上界、往返/拆单/闭环不套利、b 选取金值表、20 组 `GOLDEN_EXPECTED` 金值、可复现）/ test_pm_contracts（v2 与 v1 的 §3.2 例子逐字段、窗口锚定、过滤、传闻、截断、回合过滤、spec 不依赖隐藏字段、真实规则集的行业 n）/ test_pm_limits（每条限额边界）。随机输入走 `rng.rand_below`，测试 tick 命名空间 `-(1<<36) - 序号`，不占 domain 段
- `data/`：test_stock_pool_files / test_event_data_files（产业链、暴露度、模板，含对转换脚本的校验与往返）

## 验证
- 标准：`cd backend && uv run pytest tests/unit -q`
- 若 `tests/conftest.py`（集成测试用）导入应用失败，可用 `uv run pytest tests/unit -q --noconftest` 单独运行。
