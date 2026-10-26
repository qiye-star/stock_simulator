# tests/integration

接口级测试，覆盖：

- `test_health.py`：`/healthz`、`/readyz`（含数据库不可达）
- `test_errors.py`：错误契约 `{"code","params"}`
- `test_auth.py`：注册、登录、登出、改密、会话哈希存储、过期会话
- `test_me.py`：读取与修改偏好、注销账号及级联删除
- `test_saves.py`：存档创建/列表/改名/删除/导出、归属隔离（他人存档 404）、存档上限、时钟暂停与跳过、股票池种子、成就目录
- `test_market.py`：全市场快照（涨跌停）、个股日 K 与五档、挂钟补推、暂停、跨日 K 线、自选标记
- `test_market_list_intraday.py`：行情列表 limit/cursor/q/sort/watchlisted、无参兼容、游标校验；个股 intraday 与逐 tick 真实价格对拍
- `test_concurrent_rollover.py`：并发请求跨交易日补推（线程并发 + 过期会话确定性冲突），断言无 500、K线/权益快照每日一行、与串行结果一致
- `test_orders.py`：市价/限价、T+1（卖出与当日回补）、资金/数量/休市校验、幂等键、成交分页、成就落库
- `test_portfolio.py`：持仓估值、可卖股数、卖出实现盈亏

运行：`cd backend && uv run pytest tests/integration -q`
- `test_auto_trade.py`：条件单 CRUD、启停/重置、事件分页、自动下单的触发/冷却/次数与金额上限、失败事件码
- `test_legacy_import.py`：旧版导出（XOR+Base64 与明文 JSON）导入、严格校验、未知股票、审计 sha256
- `test_debug.py`：`ENABLE_DEBUG_API` 开关（默认 403）、资金/时钟/成就/重置行情/清空
- `test_clock_v2.py`：时钟 v2 接口（创建、节奏档、补推、午休与收盘停留、换日、暂停、离线截断、跳过）
- `test_market_v2.py`：v2 分时逐步精确重放；墙钟补推与逐分钟推进逐位等价
- `test_day_summary.py`：收盘小结（当前日、过去日、涨跌家数、排序、v1、404）
- `test_clock_v2_debug_migration.py`：v2 调试接口与存量存档迁移为 v1（含 SQLite 外键级联回归）
- `test_ws.py`：WebSocket 鉴权（4401/4404）、首帧全量与增量、ping/subscribe、成交/成就/自动事件推送、事件 `news` 帧（事件存档推送、关闭存档不推）
- `test_events.py`：事件行情接口与行情耦合（开关、409、漂移逐位重放 v1/v2、分页、保密、暂停钩子、reset 钩子）

预测卡：`test_points.py`、`test_predictions.py`、`test_intel.py`（见 `CLAUDE.md`）。

每日挑战：`test_challenge_lifecycle.py`（生成与 HTTP 全流程）、`test_challenge_sync.py`（推进与镜像）、`test_challenge_settle.py` 与 `test_challenge_scoring_db.py`（结算与计分）、`test_challenge_secrecy.py`（保密）、`test_challenge_isolation.py`（隔离与静态检查）、`test_challenge_runner.py`（runner 与 CLI）、`test_challenge_d_contract.py`（给 D 的契约函数）、`test_challenge_migration.py`（迁移），夹具在本目录 `conftest.py`（见 `CLAUDE.md`）。

真实复盘：`test_replay_levels.py`、`test_replay_session.py`、`test_replay_trading.py`、`test_replay_predictions.py`、`test_replay_reveal.py`、`test_replay_supply_chain.py`，共用 `replay_support.py`（见 `CLAUDE.md`）。夹具关卡包为 `tests/fixtures/replay/pack_min.json`，全程不联网。
