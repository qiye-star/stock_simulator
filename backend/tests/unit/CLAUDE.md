# tests/unit（单元测试）— 给 agent 的说明

- 只测纯逻辑：`domain/`（规则、行情、撮合、自动交易、成就）与 `data/`（静态 JSON 完整性）。不起数据库、不起 FastAPI。
- 金定值（RNG）是行为契约：`domain/test_rng.py` 中的数值只能在规范变更时整体更新，禁止为通过测试而改断言。
- `domain/test_purity.py` 扫描 domain 源码，禁止 I/O、框架、随机与墙上时钟。
- 测试用 `Path(__file__)` 定位 `src/stocksim/data`，不依赖工作目录。
- 测试模块名必须全局唯一（pytest 默认导入模式）。

## 文件
- `domain/`：test_rng / test_money / test_clock / test_rules / test_market_engine / test_matching / test_auto_trade / test_achievements / test_purity
- `data/`：test_stock_pool_files

## 验证
- 标准：`cd backend && uv run pytest tests/unit -q`
- 若 `tests/conftest.py`（集成测试用）导入应用失败，可用 `uv run pytest tests/unit -q --noconftest` 单独运行。
