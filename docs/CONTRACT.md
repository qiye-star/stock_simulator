# 重构契约（所有并行 agent 必须遵守）

原版代码在 `legacy/`（只读，不要修改）。新项目是 monorepo：`backend/`（FastAPI+SQLAlchemy+uv）、`frontend/`（Vite+原生 ES 模块）、`docker-compose*.yml`。

## 通用规则
- 只在自己被分配的目录里写文件，不要碰别人的目录。
- 每个新建目录（`__pycache__`、`node_modules`、`alembic/versions` 除外）必须有 `CLAUDE.md`（≤60 行，给 agent：边界/不变量/文件地图/常见任务/验证命令）和 `README.md`（给人：用途/快速开始/目录表/接口）。中文撰写。
- 金额一律**整数分**（int），费率用 `Decimal`/字符串，API 里金额字段为整数分，字段名以 `_cents` 结尾。
- 时间 UTC。行号参考 `legacy/game.js`。
- 代码风格：Python 3.12，类型标注，ruff 风格；JS 用 ES 模块 + JSDoc。

## 后端目录（包名 `stocksim`，路径 `backend/src/stocksim/`）
`core/`(config.py errors.py security.py) · `db/`(base.py session.py types.py) · `models/` · `schemas/` · `domain/`(纯函数，零 I/O，禁止 import sqlalchemy/fastapi/datetime.now/random 全局) · `services/` · `api/routers/` · `data/stock_pool.json`

## 领域规则（从 legacy 移植，行号见 legacy/game.js）
- 涨跌停 ±10%，价格四舍五入到分（LimitManager 4-104）。
- 费用：买/卖费率各自可配，手续费先单独四舍五入到分。
- T+1：T+0 模式关闭时，当日买入的股数当日不可卖（从 trades 推导，不再用 dayTrades 台账）。
- 交易单位 tradeUnit 为 1 或 100。
- 行情引擎：确定性。RNG 为 splitmix64 计数器式：`rand01(seed, tick, stock_idx, k) -> float[0,1)`，实现在 `domain/rng.py`，规范：`z = (seed + (tick*1000003 + stock_idx*7919 + k) * 0x9E3779B97F4A7C15) mod 2^64`，再做标准 splitmix64 混合（`z=(z^(z>>30))*0xBF58476D1CE4E5B9; z=(z^(z>>27))*0x94D049BB133111EB; z^=z>>31`，均 mod 2^64），返回 `(z>>11)/2^53`。
- 单 tick 波动 ±2%（legacy 2099），影视飓风（profile=bull_bias）偏多头彩蛋。
- 限价单（**已按重构建议修复**）：买单限价≥市价时按**市价**成交，否则拒绝 `ORDER_LIMIT_NOT_REACHED`；卖单限价≤市价时按市价成交，否则拒绝；限价须在涨跌停区间内。
- 每个 tick 一个交易日的 N 倍：`TICKS_PER_TRADING_DAY` 默认 20。

## 错误契约
HTTP 错误体：`{"code":"TRADE_T1_SELL_BLOCKED","params":{...}}`。ErrorCode 枚举在 `core/errors.py`（后端）与 `frontend/src/i18n/errors.js`（前端）必须一致，且两端 `locales/zh-CN.js`、`en-US.js` 都要有 `error.<CODE>` 文案。完整列表：
AUTH_INVALID_CREDENTIALS, AUTH_USERNAME_TAKEN, AUTH_USERNAME_INVALID, AUTH_PASSWORD_WEAK, AUTH_REQUIRED, SAVE_NOT_FOUND, SAVE_LIMIT_REACHED, STOCK_NOT_FOUND, TRADE_INSUFFICIENT_FUNDS, TRADE_INSUFFICIENT_HOLDINGS, TRADE_T1_SELL_BLOCKED, TRADE_T1_BUY_BLOCKED, TRADE_INVALID_QUANTITY, TRADE_PRICE_OUT_OF_LIMIT, TRADE_PRICE_DEVIATION_EXCEEDED, TRADE_PRICE_DEVIATION_CONFIRM, TRADE_CIRCUIT_BREAKER_ACTIVE, ORDER_LIMIT_NOT_REACHED, MARKET_CLOSED, AUTO_CONFIG_DUPLICATE, AUTO_CONFIG_NOT_FOUND, AUTO_LIMIT_REACHED, AUTO_MAX_AMOUNT_EXCEEDED, DEBUG_DISABLED, LEGACY_IMPORT_INVALID, VALIDATION_ERROR, INTERNAL_ERROR。

- `INTERNAL_ERROR`（500，未捕获异常）与 `HTTP_<status>`（未知路由等传输层错误）不在业务枚举内，但前端 `errors.js` 必须能翻译 `INTERNAL_ERROR`。
- `AUTO_CONFIG_NOT_FOUND`：PUT/DELETE 的 `configs/{cid}` 不存在或不属于该存档（404）。
- `TRADE_PRICE_DEVIATION_CONFIRM`（422）：委托价偏离 10%-20%，前端带 `confirm_deviation: true` 重发。
- 自动交易事件的失败 `reason_code` 复用上述码（`AUTO_LIMIT_REACHED`、`AUTO_MAX_AMOUNT_EXCEEDED`、以及下单失败的交易码）。

## REST API（前缀 `/api/v1`，Cookie 会话 `session`，httpOnly）
- `GET /healthz` · `GET /readyz`
- `POST /auth/register|login|logout` · `PUT /auth/password` · `GET/PATCH /me` {theme,lang,refresh_rate_ms,tutorial_completed} · `DELETE /me`
- `GET /stocks` · `GET /achievements/catalog`
- `GET/POST /saves` · `GET/PATCH/DELETE /saves/{id}`（PATCH 仅改 name）· `GET /saves/{id}/export`（版本化 JSON，`format`/`format_version` 字段，非旧版文本）
- `GET /saves/{id}/market`（`{paused,tick,trading_day,clock_minute,session,skipped_ticks,stocks:[QuoteOut]}`，QuoteOut 含 `watchlisted`）· `GET /saves/{id}/market/{code}`（QuoteOut + `candles` + `order_book{bids,asks}`）
- `POST /saves/{id}/clock/pause|resume|skip`（返回 ClockOut：`paused,tick,trading_day,clock_minute,session,skipped_ticks`）
- `POST /saves/{id}/orders` {code, side:"buy|sell", quantity, price_type:"market|limit", limit_price_cents?, confirm_deviation?}（可选 `Idempotency-Key` 头；返回 `{trade, unlocked_achievement_ids, cash_cents, replayed}`）
- `GET /saves/{id}/trades?cursor=`（`{items:[TradeOut], next_cursor}`，TradeOut 字段为 `code` 而非 `stock_code`）· `GET /saves/{id}/portfolio`（`{tick,trading_day,cash_cents,initial_fund_cents,market_value_cents,equity_cents,net_pnl_cents,holdings:[{code,name,quantity,sellable_quantity,avg_price_cents,total_cost_cents,market_price_cents,market_value_cents,pnl_cents,pnl_bp}]}`）
- `PUT|DELETE /saves/{id}/watchlist/{code}`
- `GET/POST /saves/{id}/auto-trade/configs`（列表为 `{items}`）· `PUT|DELETE .../configs/{cid}` · `GET .../auto-trade/status` · `POST .../auto-trade/start|pause|resume|stop|reset`（均返回 status：`{enabled,paused,max_total_trades,total_trades,success_trades,failed_trades,total_pnl_cents}`）· `GET .../auto-trade/events?cursor=&limit=`（`{items,next_cursor}`）。配置字段：`code,direction,condition_type,condition_operator,condition_value_cents,condition_percent,quantity,price_type,limit_price_cents,stop_loss_percent,take_profit_percent,max_trades,max_amount_cents,enabled`；百分比为 float（2.5 = 2.5%）
- `GET /saves/{id}/achievements`
- `POST /import/legacy` {content}：旧版导出文本（base64+XOR 或明文 JSON）。接受单用户对象 `{username,saves}` 或整包用户映射 `{username: userObj}`（即 localStorage `stock_simulator_users` 解密后的内容，各用户存档全部导入）；存档挂到当前用户，忽略密码
- `POST /saves/{id}/debug/{fund|time|achievements|reset-market|clear}`（仅 `ENABLE_DEBUG_API=true`）
- WebSocket `/api/v1/ws/saves/{id}`：服务端推 `{"t":"tick","tick","advanced","clock":{"minute","trading_day","paused","trading"},"full","q":[[code,price_cents,change_bp,volume],...]}`；另有 `trade`/`achievement`/`auto_event`/`error` 等消息。

## 数据库
SQLAlchemy 2.x 同步，`DATABASE_URL` 切换（sqlite 默认 `sqlite:///./data/stocksim.db`，`postgresql+psycopg://`，`mysql+pymysql://...charset=utf8mb4`）。主键 `sa.Uuid`；JSON 用 `JSON().with_variant(JSONB,"postgresql")`；String 必须有长度；`MetaData(naming_convention=...)`；Alembic `render_as_batch=True`。
表：users, sessions, stocks, saves, save_stats, save_sectors, holdings, trades, watchlist_items, market_states, candles, auto_trade_configs, auto_trade_events, save_achievements, legacy_imports（字段见 backend/src/stocksim/models/CLAUDE.md，由 models agent 定稿；其他 agent 以代码为准）。

## 前端
`frontend/src/`：`api/ state/ i18n/ ui/ features/<name>/ styles/ main.js`。禁止直接 innerHTML 拼接用户数据，必须用 `ui/html.js` 的默认转义 tagged template。i18n 双语 key 必须对齐（复用 legacy/locales，新增错误码文案放 `i18n/errors.js`）。HTML 结构复用 legacy/index.html。
