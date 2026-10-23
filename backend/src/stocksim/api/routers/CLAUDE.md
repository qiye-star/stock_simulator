# api/routers/ — 路由（给 agent）

## 边界
- 每个文件一个资源。路由函数只组装参数并调用 services，返回 schemas 模型（或 services 返回的字典）。
- 存档级接口必须先 `saves.open_save`（归属校验 + 推进行情），不要直接查 Save。

## 不变量
- `router` 变量名统一；`prefix` 写在各自文件（如 `/auth`、`/me`），`/api/v1` 由 main 添加。
- 无前缀的文件（achievements、orders）在装饰器里写完整路径。
- 路由由 `__init__.py` 自动发现（包内任何暴露 `router` 的模块），无需手动登记。
- 状态码：创建 201，删除/无内容 204；下单幂等回放返回 200 且 `replayed=true`。业务错误由 AppError 决定。
- `health.py` 不需要登录；其余接口需要 Cookie 会话。

## 文件地图
- `health.py` 存活/就绪探针。
- `auth.py` 注册、登录、登出、改密。`me.py` 偏好与注销。
- `stocks.py` `GET /stocks`。`achievements.py` 目录与存档已解锁列表。
- `saves.py` 存档 CRUD 与导出。`market.py` 全市场与个股详情。`clock.py` 暂停/继续/跳过。
- `orders.py` 下单（Idempotency-Key）与成交流水（cursor 分页）。`portfolio.py` 资产持仓与 `equity-curve` 资产曲线。`watchlist.py` 自选增删。
- `__init__.py` 自动汇总为 `api_router`。

## 验证
`cd backend && uv run pytest tests/integration -q`

- `auto_trade.py` 条件单 CRUD、`start|pause|resume|stop|reset`、`status`、`events`（keyset cursor）。
- `legacy.py` `POST /import/legacy`。`debug.py` `/saves/{id}/debug/*`（依赖守门）。`ws.py` `WS /ws/saves/{id}`（无前缀，完整路径）。
