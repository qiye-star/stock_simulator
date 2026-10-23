# api/ — HTTP 适配层（给 agent）

## 边界
- 只做请求解析、依赖注入、调用 services、设置 Cookie 与状态码。不写业务规则，不直接写 SQL。

## 不变量
- 依赖：`DbSession`（来自 `db.session.get_db`）、`SettingsDep`、`SessionTokenDep`、`CurrentUser`。
- 未登录统一 `AUTH_REQUIRED`（401）。会话 Cookie：`session`，httpOnly，SameSite=lax，Secure 由配置决定，Max-Age=SESSION_TTL_HOURS。
- 204 接口通过注入 `Response` 删除 Cookie 并返回 None。
- 路由挂载在 `routers/__init__.py` 的 `api_router`，由 `main.create_app` 加前缀 `/api/v1`。

## 文件地图
- `deps.py` 依赖定义。
- `routers/` 路由：`health.py`、`auth.py`、`me.py`，汇总见 `routers/__init__.py`。

## 验证
`uv run pytest tests/integration -q`

- `ws.py` 行情推送循环（refresh_rate_ms 周期：advance_to_now → run_auto_trade → 与快照做差）；`routers/ws.py` 只做 accept 与参数转发。
- WebSocket 鉴权失败：先 accept，再发 `{"t":"error","code"}` 并以 4401（未登录）/4404（存档不存在）关闭。
- 调试路由依赖 `ENABLE_DEBUG_API`，关闭时 403 `DEBUG_DISABLED`，先于鉴权判断。
