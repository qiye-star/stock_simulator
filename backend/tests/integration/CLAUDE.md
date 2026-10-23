# tests/integration/ — 接口集成测试（给 agent）

## 边界
- 只通过 HTTP（TestClient）与 ORM 查询验证行为，不 mock 数据库。
- 行情随机种子不可控：测试通过 `refresh_rate_ms=60000` 关闭挂钟补推，用 `app.state.session_factory` 设置 `clock_minute`、`last_tick_at`，或直接调用 `services.market.advance_ticks` 推进。

## 不变量
- 新接口必须有至少一个成功用例与一个失败用例（断言 `code`）。
- 断言错误体为 `{"code", "params"}`，不要断言 FastAPI 默认的 `detail`。
- 需要改库的场景用 `app.state.session_factory()` 直接操作。
- 每个文件一个资源；模块之间不互相 import，辅助函数各自定义。
- 他人存档访问必须断言 404 与 `SAVE_NOT_FOUND`。

## 文件地图
- `test_health.py` 存活/就绪。`test_errors.py` 错误契约。`test_auth.py` 认证。`test_me.py` 当前用户。
- `test_saves.py` 存档生命周期、归属、时钟、种子、成就目录。
- `test_market.py` 行情视图、补推、暂停、跨日、自选。
- `test_orders.py` 下单规则、T+1、幂等、分页、成就。
- `test_portfolio.py` 持仓与盈亏。

## 验证
`cd backend && uv run pytest tests/integration -q`（全量约 2 分钟，含每用例的 Alembic 迁移）
- `test_auto_trade.py` 条件单 CRUD、状态机、事件分页、run_auto_trade（触发/冷却/上限/失败码）。
- `test_legacy_import.py` 旧版导入（样例见 `../fixtures/`）、结构与一致性校验、审计。
- `test_debug.py` 调试开关与各动作。`test_ws.py` WebSocket 鉴权、首帧与增量、订阅/ping、推送事件。
