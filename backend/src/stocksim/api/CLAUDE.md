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
- `routers/` 路由：`health.py`、`auth.py`、`me.py`，汇总见 `routers/__init__.py`。事件行情（01 §8.1）：`routers/events.py`（`/saves/{id}/news`、`/events`、`/events/{event_id}`）、`routers/supply_chain.py`（`/saves/{id}/supply-chain`）；`routers/market.py` 新增 `/{code}/event-marks`。

## 验证
`uv run pytest tests/integration -q`

- `routers/predictions.py`（`/saves/{id}/predictions`：列表、`settings`、详情、`answer`、`skip`；读接口先 `open_save` 再 `settle_due`）、`routers/intel.py`（`/saves/{id}/intel`：状态、`edges`、`rumor-hints`）、`routers/points.py`（`/points`：余额开户、`ledger`、`stats`（可选 save_id）、`titles`、`PUT title`）。
- `ws.py` 行情推送循环：`tick_once` 返回 `(messages, next_delay_ms)`；结算后 `_prediction_messages`（与 `StreamState.pred` 做差发 `prediction` 的 opened/answered/expired/settled/void）与 `_title_messages`（`title`）；v1 按 refresh_rate_ms，v2 醒在下一个到期点（`next_delay_ms`，夹在 [200, ms_per_minute]，暂停 2000 ms）。消息顺序 tick → phase → news → challenge → prediction → title → trade → achievement → auto_event。挑战存档（C10，03 §10.4）：`StreamState.is_challenge` 时不推 news/prediction/title（`snapshot` 把 events 置假），每轮经 `market.advance_to_now` 分发到 `challenges.sync.sync_entry_save`；`_challenge_messages` 在 (status, phase, round_index, resolved_qids) 变化或首帧时发 `challenge`（字段公开形态，时间 ISO Z）；`challenge_delay_ms`：快放段（burst/final）为挑战行 `tick_ms`（夹在 [200, 60000]），其余为 `CHALLENGE_HOLD_POLL_MS`，不走 v2 调度；tick 帧的 clock 由 `market.clock_view` 按 mode 分发到 `challenges/views.clock_overrides`（ms_per_minute/next_tick_at/fast_forward_at/next_event.at，03 §3.2）。`routers/ws.py` 只做 accept 与参数转发。
- `routers/day_summary.py`：`GET /saves/{id}/day-summary`（挂在 `/saves/{id}` 前缀，不在 market 路由下）。
- WebSocket 鉴权失败：先 accept，再发 `{"t":"error","code"}` 并以 4401（未登录）/4404（存档不存在）关闭。
- 调试路由依赖 `ENABLE_DEBUG_API`，关闭时 403 `DEBUG_DISABLED`，先于鉴权判断。
- 每日挑战（C9，WS 见 C10）：`routers/challenges.py`（`/challenges/*` 与 `/challenge-leaderboard`，单一 `router`、路径全写；`CHALLENGE_ENABLED=false` 时 404 `CHALLENGE_NOT_FOUND`）、`routers/debug_challenges.py`（`/debug/challenges/ensure|{id}/shift`，先判 `ENABLE_DEBUG_API`）。进入挑战路由先 `runner.maybe_run_due`，running 再 `sync.advance_master`；输出只经 `services/challenges/views.py`。

## 预测市场（模式 D，04 §9、§8）
- `routers/prediction_markets.py`：`/prediction-markets*`（列表、详情、quote、`POST …/trades` 必带 `Idempotency-Key`，201 新建 / 200 重放）、`history`、`trades`（匿名成交带）；`/me/prediction-positions`、`/me/prediction-settlements`；调试 `/debug/prediction-markets/{id}/void`、`/sync`（`ENABLE_DEBUG_API`，关闭 403 `DEBUG_DISABLED`）。`CHALLENGE_ENABLED=false` 时 404。时间统一经 `services.challenges.timeutil.now()`（模块属性，可 monkeypatch）。
- `pm_ws.py`：`PmHub`（每进程一个，`app.state.pm_hub`，lifespan 中按 `PM_BACKGROUND_ENABLED` 启动/停止）：每 `PM_POLL_MS` 轮询被关注挑战的市场快照做差分扇出（pm_tick / pm_list / pm_resolved），每 `PM_SWEEP_MS` 执行 `pm_lifecycle.sync_due`。`stream_prediction_markets` 为连接循环（鉴权失败 error AUTH_REQUIRED + 4401；订阅上限 20；未知市场 VALIDATION_ERROR）。`routers/pm_ws.py`：`WS /api/v1/ws/prediction-markets`。注意：Hub 的 asyncio.Queue 必须与 WS 连接在同一事件循环（测试中用同一个 TestClient）。
