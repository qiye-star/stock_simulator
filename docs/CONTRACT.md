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
- **时钟规则按存档分版本**（`saves.clock_rules`，只在创建时设置；07 计划）：
  - v1（`clock_rules=1`，存量存档与网页版默认新建）：每 20 个交易 tick 为一个交易日，单 tick ±2%，换日在 tick%20==0，撮合窗同 `is_trading_time`（11:30/15:00 含端点）。金值由 `test_market_engine_golden.py` 守护，逐位不变。
  - v2（`clock_rules=2`，手机端显式创建）：每 242 个交易 tick（9:30–11:30、13:00–15:00 的每一分钟）为一个交易日，**换日在次日 9:30**，15:00 收盘后行情仍显示当日涨跌；开局固定 9:30（tt=0）。单 tick 噪声 = 特质（档位 × σ≈924 ppm）+ 全市场共同因子 + 每股每日 1% 概率的趋势日（±[400,700] ppm/tick）+ bull_bias 漂移；标定见 `scripts/clock_v2_sim_report.py`（常量 `V2_*` 发布后冻结，只能新增 `clock_rules=3`）。撮合窗为半开区间 `[9:30,11:30) ∪ [13:00,15:00)`，11:30 与 15:00 两个 tick 只走价不接单（`MARKET_CLOSED`）。成交量为当日累计（单调）。
  - 节奏：v2 每游戏分钟 `ms_per_minute`（`users.clock_speed`：fast 2500 / normal 5000 默认 / slow 7500），11:30 停留 `CLOCK_LUNCH_DWELL_MS`（默认 5000）后跳到 12:59，15:00 停留 `CLOCK_CLOSE_DWELL_MS`（默认 15000）后跳到次日 9:29；自动快进在服务端 `advance_to_now` 完成（按锚点 `last_tick_at` 推演，结果确定）。v1 仍按 `refresh_rate_ms`。
  - 补推上限 `TICK_CATCHUP_MAX`（默认 300）：v1 按分钟 tick 计，v2 按交易 tick 计。
  - 错误码不新增：v2 停留与盘后下单 → `MARKET_CLOSED`。

## 错误契约
HTTP 错误体：`{"code":"TRADE_T1_SELL_BLOCKED","params":{...}}`。ErrorCode 枚举在 `core/errors.py`（后端）与 `frontend/src/i18n/errors.js`（前端）必须一致，且两端 `locales/zh-CN.js`、`en-US.js` 都要有 `error.<CODE>` 文案。完整列表：
AUTH_INVALID_CREDENTIALS, AUTH_USERNAME_TAKEN, AUTH_USERNAME_INVALID, AUTH_PASSWORD_WEAK, AUTH_REQUIRED, SAVE_NOT_FOUND, SAVE_LIMIT_REACHED, STOCK_NOT_FOUND, TRADE_INSUFFICIENT_FUNDS, TRADE_INSUFFICIENT_HOLDINGS, TRADE_T1_SELL_BLOCKED, TRADE_T1_BUY_BLOCKED, TRADE_INVALID_QUANTITY, TRADE_PRICE_OUT_OF_LIMIT, TRADE_PRICE_DEVIATION_EXCEEDED, TRADE_PRICE_DEVIATION_CONFIRM, TRADE_CIRCUIT_BREAKER_ACTIVE, ORDER_LIMIT_NOT_REACHED, MARKET_CLOSED, AUTO_CONFIG_DUPLICATE, AUTO_CONFIG_NOT_FOUND, AUTO_LIMIT_REACHED, AUTO_MAX_AMOUNT_EXCEEDED, DEBUG_DISABLED, LEGACY_IMPORT_INVALID, VALIDATION_ERROR, EVENTS_DISABLED, EVENT_NOT_FOUND, SUPPLY_EDGE_NOT_FOUND, PREDICTION_NOT_FOUND, PREDICTION_CLOSED, POINTS_INSUFFICIENT, INTEL_LIMIT_REACHED, INTEL_UNAVAILABLE, TITLE_NOT_UNLOCKED, CHALLENGE_NOT_FOUND, CHALLENGE_NOT_STARTED, CHALLENGE_ENTRY_CLOSED, CHALLENGE_ENDED, CHALLENGE_NOT_ENTERED, CHALLENGE_ROUND_NOT_FOUND, CHALLENGE_ROUND_CLOSED, CHALLENGE_ANSWER_LIMIT, CHALLENGE_NOT_SETTLED, CHALLENGE_UNSUPPORTED, REPLAY_LEVEL_NOT_FOUND, REPLAY_UNSUPPORTED, REPLAY_STOCK_SUSPENDED, REPLAY_LIMIT_LOCKED, REPLAY_PREDICTION_PENDING, REPLAY_QUESTION_CLOSED, REPLAY_SESSION_SETTLED, REPLAY_REVEAL_LOCKED, PM_NOT_FOUND, PM_NOT_OPEN, PM_LOCKED_AHEAD, PM_NOT_ELIGIBLE, PM_SLIPPAGE_EXCEEDED, PM_INSUFFICIENT_SHARES, PM_TRADE_TOO_SMALL, PM_POSITION_LIMIT, PM_DAILY_LIMIT, PM_RATE_LIMITED, PM_BUSY, INTERNAL_ERROR。

- `INTERNAL_ERROR`（500，未捕获异常）与 `HTTP_<status>`（未知路由等传输层错误）不在业务枚举内，但前端 `errors.js` 必须能翻译 `INTERNAL_ERROR`。
- `AUTO_CONFIG_NOT_FOUND`：PUT/DELETE 的 `configs/{cid}` 不存在或不属于该存档（404）。
- `TRADE_PRICE_DEVIATION_CONFIRM`（422）：委托价偏离 10%-20%，前端带 `confirm_deviation: true` 重发。
- 自动交易事件的失败 `reason_code` 复用上述码（`AUTO_LIMIT_REACHED`、`AUTO_MAX_AMOUNT_EXCEEDED`、以及下单失败的交易码）。
- 预测卡 / 积分 / 情报 / 称号（02 §1.4）：`PREDICTION_NOT_FOUND`（404，`{card_id}`）、`PREDICTION_CLOSED`（409，`{card_id, status}`，截止已过或已过期/作废）、`POINTS_INSUFFICIENT`（422，`{required, balance}`）、`INTEL_LIMIT_REACHED`（409，`{limit}`，每用户每 UTC 日 8 次）、`INTEL_UNAVAILABLE`（409，`{card, reason}`，`card ∈ edge|rumor`，`reason ∈ resolved|disabled|max_level`）、`TITLE_NOT_UNLOCKED`（409，`{title_id}`）。预测答案格式错误用 `VALIDATION_ERROR {field, reason}`，`field` 形如 `answers.dir.probs`、`answers.rank.order`。
- 事件模式（01 §9.2）：`EVENTS_DISABLED`（409，`{save_id}`，存档未开启事件模式）、`EVENT_NOT_FOUND`（404，`{event_id}`，事件不存在或尚未发布）、`SUPPLY_EDGE_NOT_FOUND`（404，`{edge_id}`，产业链关系不存在）。四处同步：`core/errors.py`、`frontend/src/i18n/errors.js` 与两份 locale、手机端 `store.js`/`store.real.js` 的 `ERROR_TEXT`（前端/手机端的同步由前端 agent 负责，本分支未改）。
- 每日挑战（03 §10.3，10 个 `CHALLENGE_*` 码，状态码与 `ERROR_STATUS` 一致）：`CHALLENGE_NOT_FOUND`（404，`{challenge_id}` / `{date}` / `{save_id}`）、`CHALLENGE_NOT_STARTED`（409，`{starts_at}`）、`CHALLENGE_ENTRY_CLOSED`（409，`{entry_closes_at}`）、`CHALLENGE_ENDED`（409，`{challenge_id}`）、`CHALLENGE_NOT_ENTERED`（409，`{challenge_id}`）、`CHALLENGE_ROUND_NOT_FOUND`（404，`{round_index}`）、`CHALLENGE_ROUND_CLOSED`（409，`{round_index, closes_at}`）、`CHALLENGE_ANSWER_LIMIT`（409，`{limit}`）、`CHALLENGE_NOT_SETTLED`（409，`{challenge_id}`）、`CHALLENGE_UNSUPPORTED`（409，`{feature}`，`feature ∈ clock|debug|delete|auto_trade`）。前端 `errors.js`、两份 locale 与手机端 `ERROR_TEXT` 的文案待前端同步。
- 真实复盘（05 §5.9，8 个 `REPLAY_*` 码，状态码与 `ERROR_STATUS` 一致）：`REPLAY_LEVEL_NOT_FOUND`（404，`{slug}`；关卡不存在、未发布或已退役）、`REPLAY_UNSUPPORTED`（409，`{feature}`，`feature ∈ clock|auto_trade|debug|day_summary|supply_chain`）、`REPLAY_STOCK_SUSPENDED`（409，`{code}`）、`REPLAY_LIMIT_LOCKED`（409，`{code, side}`，`side ∈ buy|sell`）、`REPLAY_PREDICTION_PENDING`（409，`{question_ids}`）、`REPLAY_QUESTION_CLOSED`（409，`{question_id, state}`，`state ∈ not_open|closed`）、`REPLAY_SESSION_SETTLED`（409，`{save_id}`）、`REPLAY_REVEAL_LOCKED`（409，`{save_id}`）。前端 `errors.js`、两份 locale 与手机端 `ERROR_TEXT` 的文案待前端同步。
- 预测市场（04 §9.3，11 个 `PM_*` 码，状态码与 `ERROR_STATUS` 一致）：`PM_NOT_FOUND`（404，`{market_id}`；含 scheduled 市场）、`PM_NOT_OPEN`（409，`{market_id, status}`，`status` 为交易视角的状态）、`PM_LOCKED_AHEAD`（403，`{challenge_id}`）、`PM_NOT_ELIGIBLE`（403，`{reason:"account_age"}`）、`PM_SLIPPAGE_EXCEEDED`（409，`{quoted_points, limit_points}`）、`PM_INSUFFICIENT_SHARES`（422，`{held, requested}`）、`PM_TRADE_TOO_SMALL`（422，`{points}`）、`PM_POSITION_LIMIT`（409，`{limit_points, used_points}`）、`PM_DAILY_LIMIT`（409，`{limit_points, used_points}`）、`PM_RATE_LIMITED`（429，`{retry_after_s}`）、`PM_BUSY`（409，`{}`）。积分不足复用 `POINTS_INSUFFICIENT`，挑战不存在复用 `CHALLENGE_NOT_FOUND`。前端 `errors.js`、两份 locale 与手机端 `ERROR_TEXT` 的文案待前端同步。

## REST API（前缀 `/api/v1`，Cookie 会话 `session`，httpOnly）
- `GET /healthz` · `GET /readyz`
- `POST /auth/register|login|logout` · `PUT /auth/password` · `GET/PATCH /me` {theme,lang,refresh_rate_ms,clock_speed∈{fast,normal,slow},tutorial_completed} · `DELETE /me`
- `GET /stocks` · `GET /achievements/catalog`
- `GET/POST /saves`（POST 可选 `clock_rules` ∈ {1,2}，默认 1；非法值 422；可选 `events_enabled` bool，默认 false，只在创建时设置，PATCH 忽略）· `GET/PATCH/DELETE /saves/{id}`（PATCH 仅改 name）· `GET /saves/{id}/export`（版本化 JSON，`format`/`format_version` 字段，非旧版文本；save 节含 `clock_rules:"v1"|"v2"`；**format_version=2**：save 节新增 `events_enabled`、`events_ruleset`，事件存档的 `market_seed` 输出 `null`（01 §9.3））。`SaveOut.clock_rules` 为 `"v1"|"v2"`（只读）。
- `GET /saves/{id}/market`（`{paused,tick,trading_day,clock_minute,session,skipped_ticks,stocks:[QuoteOut]}` + ClockOut 扩展字段，QuoteOut 含 `watchlisted`）· `GET /saves/{id}/market/{code}`（QuoteOut + `candles` + `order_book{bids,asks}` + `suspended`：复盘存档当前阶段停牌，普通存档恒 false）
  - `GET /saves/{id}/market` 响应另含 `total`（过滤后总数）与 `next_cursor`（末页/不分页为 null）。查询参数均可选，**一个都不带时返回全部 385 只、股票池顺序（向后兼容）**：`limit`（1-500）、`cursor`（不透明串，取自上一页 `next_cursor`）、`q`（代码或名称子串，不区分大小写，≤32 字符）、`sort`（`code|price|change|volume`）、`order`（`asc|desc`；默认 code 升序，其余降序）、`watchlisted`（true/false，按自选过滤）。只要给了 limit/cursor/sort/order 之一，就按 `(排序主键, 代码升序)` 全序返回；分页是键集游标：游标记录上一页末尾的排序值与代码，下一页取严格排在其后的行。游标绑定 sort/order，不一致或格式非法 → 422 `VALIDATION_ERROR` `params={"field":"cursor"}`；limit/sort/order/q 越界 → 422 `VALIDATION_ERROR`（`params.errors`）。注意：行情随 tick 变化，按 `price|change|volume` 排序时翻页期间排序值可能变动（可能漏/重少量行，不会报错）；按 `code` 排序则完全稳定。
  - `GET /saves/{id}/market/{code}/intraday` → `{code,trading_day,date,clock_minute,tick,prev_close_cents,open_cents,points:[{minute,tick,price_cents,volume}],exact}`：当前交易日（v1 每 20 个、v2 每 242 个交易 tick 为一日）从开盘到当前时钟的逐 tick 价格。`minute` 为该 tick 完成后的当日分钟数，`tick` 为全局序号（可与 WS `tick` 消息对齐），`volume` 取自引擎 `daily_volume`（与市场列表 `volume` 同口径）：v1 为快照、不保证单调；v2 为当日累计、单调不减。由确定性引擎从当日开盘价重放，不依赖额外存储，因此跳过的分钟、刷新页面后都与真实推进逐点一致；午休/收盘后无点，换日后 `points` 重新累积，当日尚无 tick 时为空数组。`exact=false` 表示时钟被调试改写、无法重放，此时 `points` 退化为仅当前点。未知代码 → 404 `STOCK_NOT_FOUND`，他人存档 → 404 `SAVE_NOT_FOUND`。
- `POST /saves/{id}/clock/pause|resume|skip`（返回 ClockOut）。**ClockOut** = `paused,tick,trading_day,clock_minute,session,skipped_ticks` + 新增 `clock_rules:"v1"|"v2"`、`phase:"pre_open"|"morning"|"lunch"|"afternoon"|"closed"`、`trading:bool`（此刻能否下单，与暂停无关）、`next_event:{kind:"open"|"lunch"|"reopen"|"close",minute,at}`（`at` 为 UTC ISO 8601 毫秒+Z，暂停为 null）、`ms_per_minute:int|null`、`next_tick_at`（暂停或停留中为 null）、`fast_forward_at`（仅 v2、未暂停、停在 11:30/15:00 时有值）、`server_time`（前端用于校正时钟偏差）。
  - v2 跳过（`clock/skip`）：570→689→690→779→780→899→900→569→570，每次至少推进 1 分钟，连按 8 次走完一个交易日；v1 保持原有跳过表。
- `GET /saves/{id}/day-summary?trading_day=`（收盘小结，缺省为当前交易日；范围 `[max(0,当前日−30), 当前日]`，越界 422 `VALIDATION_ERROR {"field":"trading_day"}`；他人存档 404）→ `{trading_day,date,clock_rules,status:"trading"|"closed",equity_cents,prev_equity_cents,day_pnl_cents,day_pnl_bp,cash_cents,market_value_cents,trades:{count,buy_count,sell_count,buy_amount_cents,sell_amount_cents,fee_cents,realized_pnl_cents},market:{total,up,down,flat,limit_up,limit_down,avg_change_bp},top_gainers,top_losers,holdings|null,next_open_at}`。当前日用实时行情与 portfolio 口径（`holdings` 仅当前日有）；过去的日用 `candles` 与 `equity_snapshots`，缺快照的权益字段为 null，第 0 日的前一日权益取初始资金。`top_gainers/top_losers` 各至多 5 只（涨/跌方向）。
- **预测卡 / 情报卡 / 积分 REST**（02 §10.1；全部需登录；存档级接口经 `open_save`，他人存档 404 `SAVE_NOT_FOUND`，存档未开事件 409 `EVENTS_DISABLED`；读接口先 `settle_due`）：
  - `GET /saves/{id}/predictions?status=open|answered|settled|expired|void|all（默认 all）&limit=1-50（默认20）&cursor=` → `{items:[PredictionCardOut], next_cursor}`，按 (`opened_trading_tick` 降序, id 降序)；游标非法 422 `VALIDATION_ERROR {field:"cursor"}`。
  - `GET /saves/{id}/predictions/settings` → `{mode:"pause"|"off", forced}`；`PUT ...settings` `{mode}`，策略强制时 422 `VALIDATION_ERROR {field:"mode", reason:"forced"}`。
  - `GET /saves/{id}/predictions/{card_id}` → PredictionCardOut（404 `PREDICTION_NOT_FOUND`）。
  - `POST /saves/{id}/predictions/{card_id}/answer` `{answers:{dir?:{probs:[5 个 int，合计 100]}, rank?:{order:[3 个候选]}, rumor?:{probs:[2 个 int]}}, resume:true}` → `{card, clock}`。卡上每道题都必须作答（缺题 `answers.<qid>` reason `missing`，多题 `unexpected`）；截止后 409 `PREDICTION_CLOSED`。`resume=true` 且存档暂停且无其它未截止的 open 卡时恢复行情。
  - `POST /saves/{id}/predictions/{card_id}/skip` `{resume:true}`（可省略 body）→ `{card, clock}`：仅 open 卡可不答（→ expired，不发积分）；其它状态 409 `PREDICTION_CLOSED`。
  - PredictionCardOut：`{id, save_id, event_id, event:EventOut|null, status, opened_trading_tick, opened_trading_day, deadline_trading_tick, window_days, questions:[BucketQ|RankQ|BinaryQ 公开 JSON], answers:[{qid,probs,order,pick,claimed_pct}], results:[{qid,resolved,void,outcome_bucket,change_bp,true_top,relevance,candidate_change_bp,truth,score,uniform_score,baseline,points,hit}], points, points_capped, answered_at, settled_at, created_at}`。题目公开形态：dir `{qid:"dir",kind:"bucket",target_kind,target,target_name,edges_bp,from_day,to_day}`，rank `{qid:"rank",kind:"rank",k:3,exclude,candidates,at_day}`，rumor `{qid:"rumor",kind:"binary"}`。结果只在该题结算后给出。
  - `GET /saves/{id}/intel` → `{edges:[EdgeRevealOut], rumor_hints:[RumorHintOut], prices:{edge_l1:100,edge_l2:200,rumor_hint:80}, daily_limit:8, used_today, balance}`；首次访问开户并发 welcome。
  - `POST /saves/{id}/intel/edges` `{edge_id ≤40, level:1|2}` → `{charged, balance, edge, hint:null}`。已拥有 ≥ level 返回 `charged=0`；L2 已是 L2 → 409 `INTEL_UNAVAILABLE {card:"edge",reason:"max_level"}`；未知边 404 `SUPPLY_EDGE_NOT_FOUND`（不扣费）；余额不足 422；日限额 409 `INTEL_LIMIT_REACHED`。L2 补差价：已有 L1 时扣 100。
  - `POST /saves/{id}/intel/rumor-hints` `{event_id: ^e\d{1,9}-\d{1,2}$}` → `{charged, balance, edge:null, hint}`。每存档每事件 1 次（再次请求 charged=0）；非传闻 422 `VALIDATION_ERROR {field:"event_id", reason:"not_rumor"}`；已揭晓 409 `INTEL_UNAVAILABLE {card:"rumor",reason:"resolved"}`（无记录时）；不存在 404 `EVENT_NOT_FOUND`。
  - `GET /points` → `{balance, lifetime_earned, lifetime_spent, equipped_title, today_prediction_points, daily_cap:1000}`（首次访问开户并发 welcome 200）。
  - `GET /points/ledger?limit=1-100（默认30）&cursor=&reason=`（可多值）→ `{items:[{seq,delta,balance_after,reason,ref,save_id,meta,created_at}], next_cursor}`，按 seq 降序。
  - `GET /points/stats?save_id=` → `{cards_answered, cards_settled, cards_expired, total_points, by_kind:{bucket,rank,binary}:{answered,scored,avg_score,avg_baseline}, calibration:[10 档 {lo_pct,hi_pct,n,hits,avg_claimed_pct,hit_rate_pct}], calibration_error_bp, recent:[最近 30 张已结算]}`。传 save_id 时他人存档 404。
  - `GET /points/titles` → `{items:[{id,level,unlocked_at|null}], equipped}`；`PUT /points/title` `{title_id: str|null}` → PointsOut；未知 id 422 `VALIDATION_ERROR {field:"title_id"}`；未解锁 409 `TITLE_NOT_UNLOCKED`。
- **事件模式 REST**（01 §8.1；全部需登录，他人存档 404 `SAVE_NOT_FOUND`；关闭事件的存档返回 409 `EVENTS_DISABLED`）：
  - `GET /saves/{id}/news?limit=1-100（默认30）&cursor=&major=&code=^\d{6}$&industry=&watchlisted=` → `{items:[NewsOut], next_cursor}`。排序 `(trading_tick 降序, news_id 升序)`；游标为 base64url 的 JSON `[trading_tick, news_id]`。非法游标或行业/代码未知 → 422 `VALIDATION_ERROR {field}`。
  - `GET /saves/{id}/events?limit=1-100（默认20）&cursor=&major=&code=&industry=&phase=expected|active|settled` → `{items:[EventOut], next_cursor}`，排序 `(first_seen_trading_tick 降序, event_id 升序)`。
  - `GET /saves/{id}/events/{event_id}` → EventDetailOut（EventOut + `news`（已发布，时间升序）+ `propagation`（只含已到达节点，hop 0 最先））。未发布或不存在 → 404 `EVENT_NOT_FOUND`。
  - `GET /saves/{id}/market/{code}/event-marks?days=1-120（默认60）` → `{code, items:[EventMarkOut]}`，`role ∈ source|propagated|market`。未知代码 404 `STOCK_NOT_FOUND`。
  - `GET /saves/{id}/supply-chain` → SupplyChainOut：`{ruleset, nodes:[{id,layer,stock_count,leaders}], edges:[{id,from_industry,to_industry,relation,sign,strength,lag_days,revealed_level}]}`。**关闭事件的存档同样返回**；**复盘存档不提供**（决策 16）：返回 409 `REPLAY_UNSUPPORTED {feature:"supply_chain"}`，因为 `leaders` 含真实龙头代码，会破坏匿名；`strength`/`lag_days` 只对已揭示的边给出（level 1 揭示强度、level 2 加揭示滞后），其余为 null。揭示状态由 B 注册的 provider 提供（`services/event_hooks.register_reveal_provider`），默认全部隐藏。
  - 公开形态字段见 `backend/src/stocksim/schemas/events.py`；永不外发：`magnitude_ppm`、`knots`、`expectation`、`channel`、未揭晓的 `rumor.truth`、未到达的 `impacts`、按存档抖动的系数（01 §1.8）。
  - 服务层（不经 HTTP，供 B/C/D 调用）：`services/events.py` 的 `reveal_edge`、`rumor_hint`、`industry_change_bp`、`events_for_days`、`event_out`、`ruleset`；`services/event_hooks.py` 的 `register_publish_hook` / `register_reset_hook` / `register_reveal_provider` / `clear_hooks`（仅测试用）。
- `POST /saves/{id}/orders` {code, side:"buy|sell", quantity, price_type:"market|limit", limit_price_cents?, confirm_deviation?}（可选 `Idempotency-Key` 头；返回 `{trade, unlocked_achievement_ids, cash_cents, replayed}`）
- `GET /saves/{id}/trades?cursor=`（`{items:[TradeOut], next_cursor}`，TradeOut 字段为 `code` 而非 `stock_code`）· `GET /saves/{id}/portfolio`（`{tick,trading_day,cash_cents,initial_fund_cents,market_value_cents,equity_cents,net_pnl_cents,prev_equity_cents,day_pnl_cents,day_pnl_bp,holdings:[{code,name,quantity,sellable_quantity,avg_price_cents,total_cost_cents,market_price_cents,market_value_cents,pnl_cents,pnl_bp}]}`）
- **当日盈亏**（portfolio 字段）：`prev_equity_cents` = 昨日收盘权益（现金与持仓按各股 `prev_close` 估值，把当日成交倒推回去：现金 − 当日成交 cash_delta，持仓 − 当日买卖净股数）；`day_pnl_cents = equity_cents − prev_equity_cents`（含当日手续费）；`day_pnl_bp = round_half_up(day_pnl_cents*10000/prev_equity_cents)`，`prev_equity_cents<=0` 时为 0。新存档第 0 日 `prev_equity_cents = initial_fund_cents`。调试加资金（`debug/fund`）会计入当日盈亏。
- `GET /saves/{id}/equity-curve?range=7d|30d|all`（默认 30d，非法值 422）→ `{range, items:[{trading_day,equity_cents,cash_cents,market_value_cents,kind}]}`，按 trading_day 升序。`kind`：`initial` 初始资金起点（`trading_day=-1`，equity=initial_fund，必在完整序列首位）、`close` 已收盘交易日快照（持久化于 `equity_snapshots`，交易日切换时按 (save_id,trading_day) 幂等覆盖；批量跳过跨多日时每日各写一行，按各日收盘价估值）、`live` 当前交易日实时点（不落库，trading_day=当前日）。`range` 取完整序列（initial+close…+live）的**最后 N 个点**（7d=7、30d=30），`all` 返回全部；因此总含 live 点且至少 2 点。仅返回 trading_day 小于当前交易日的快照（调试重置行情后遗留的未来快照被忽略）。他人存档 404 `SAVE_NOT_FOUND`。
- `PUT|DELETE /saves/{id}/watchlist/{code}`
- `GET/POST /saves/{id}/auto-trade/configs`（列表为 `{items}`）· `PUT|DELETE .../configs/{cid}` · `GET .../auto-trade/status` · `POST .../auto-trade/start|pause|resume|stop|reset`（均返回 status：`{enabled,paused,max_total_trades,total_trades,success_trades,failed_trades,total_pnl_cents}`）· `GET .../auto-trade/events?cursor=&limit=`（`{items,next_cursor}`）。配置字段：`code,direction,condition_type,condition_operator,condition_value_cents,condition_percent,quantity,price_type,limit_price_cents,stop_loss_percent,take_profit_percent,max_trades,max_amount_cents,enabled`；百分比为 float（2.5 = 2.5%）
- `GET /saves/{id}/achievements`
- `POST /import/legacy` {content}：旧版导出文本（base64+XOR 或明文 JSON）。接受单用户对象 `{username,saves}` 或整包用户映射 `{username: userObj}`（即 localStorage `stock_simulator_users` 解密后的内容，各用户存档全部导入）；存档挂到当前用户，忽略密码
- `POST /saves/{id}/debug/{fund|time|achievements|reset-market|clear}`（仅 `ENABLE_DEBUG_API=true`）。v2 存档：`time` 只向前推进（`changed` 为推进的分钟数，经由正常推进路径），`reset-market` 同时把时钟回到 570。
- WebSocket `prediction`（事件存档才推送，02 §10.3）：`{"t":"prediction","op":"opened|answered|expired|settled|void","card_id","event_id","status","points":int|null,"balance":int|null}`；`points/balance` 仅 `op=settled` 时非空。`title`：`{"t":"title","ids":[…]}` 为新解锁称号。消息顺序 tick → phase → news → prediction → title → trade → achievement → auto_event。跨过触发 tick 的那一轮 tick 帧 `clock.paused=true`。
- WebSocket `news`（事件存档才推送，01 §8.2）：`{"t":"news","trading_tick","items":[NewsOut],"truncated"}`；每帧最多 20 条，超出只留最新 20 条并置 `truncated:true`（客户端重拉 `/news`）。消息顺序 tick → phase → news → trade → achievement → auto_event。
- WebSocket `/api/v1/ws/saves/{id}`：服务端推 `{"t":"tick","tick","advanced","clock":{"minute","trading_day","paused","trading","clock_rules","phase","next_event","ms_per_minute","next_tick_at","fast_forward_at","server_time"},"full","q":[[code,price_cents,change_bp,volume],...]}`（clock 与 ClockOut 同源，`clock_minute` 在帧内叫 `minute`）。`{"t":"phase","from","to","trading_day","clock_minute"}` 在相位变化时于 tick 之后发送一次（首帧只记录不发送）。另有 `trade`/`achievement`/`auto_event`/`error` 等消息。推送节奏：v1 每 `refresh_rate_ms`；v2 醒在下一个到期点（下一分钟或停留结束，+50 ms，夹在 [200, ms_per_minute]），暂停时每 2000 ms。

## 每日挑战（03 分册，模式 C）

每天一场挑战：全服共用一份无主 master 行情（`saves.mode='challenge_market'`，`user_id` 为空，永不经用户接口访问）；每位报名者一份玩家存档（`mode='challenge'`，行情经 `market_source_id` 读 master，只镜像 master 的时间，永不超前）。时钟固定 v2（`clock_rules=2`，开局 570）。时间线与承诺细节见 `docs/10.26-plan/03-每日挑战.md` §1，架构见 `docs/architecture.md` 的“每日挑战时间线”。

**REST**（前缀 `/api/v1`，全部需登录；`CHALLENGE_ENABLED=false` 时挑战接口一律 404 `CHALLENGE_NOT_FOUND`）：
- `GET /challenges/today` → ChallengeOut；当日无挑战 404 `CHALLENGE_NOT_FOUND {date}`。
- `GET /challenges?limit=1-50（默认20）&cursor=` → `{items:[ChallengeOut], next_cursor}`，按日期降序；cursor 为 `YYYY-MM-DD`，非法 422 `VALIDATION_ERROR {field:"cursor"}`。
- `GET /challenges/{id}` → ChallengeOut。
- `POST /challenges/{id}/entry` → 新建 201 / 已报名 200（同一条），ChallengeEntryOut。`entry_closes_at` 前可报名，迟到者按当时行情开局。
- `GET /challenges/{id}/rounds` → `{items:[ChallengeRoundCardOut]}`，只含已停顿（已打开）的回合。
- `PUT /challenges/{id}/rounds/{round_index}/answer`，body `{answers}`（与 02 的 `PredictionAnswersIn` 同形，无 `resume`）→ ChallengeRoundCardOut。窗口内可改，上限 `CHALLENGE_MAX_REVISIONS`=20 次，以最后一次为准。`round_index` 1–10。
- `GET /challenges/{id}/leaderboard?board=total|forecast|trade&limit=1-100（默认50）&cursor=` → LeaderboardOut（`scope="day"`），结算后可见。
- `GET /challenge-leaderboard?scope=week|all&week=&sort=sum|avg&limit=&cursor=` → LeaderboardOut（周/总榜，只含已结算挑战的合格报名，缺席计 0）。
- `GET /challenges/{id}/reveal` → RevealOut，结算或作废后可见。
- `GET /challenges/{id}/review` → ReviewOut（本人，结算后）。

**schemas**（`schemas/challenges.py`；金额整数分，时间 ISO 8601 UTC）：
- ChallengeOut：`id, challenge_date, status(scheduled|running|settled|void), phase(before|burst|hold|final|ended), round_index, rounds_total, schedule_mode(daily|compact), starts_at, entry_closes_at, settle_expected_at, next_change_at, server_time, tick_ms, clock_rules("v2"), events_ruleset, seed_commitment, commitment_scheme("sha256/stocksim-challenge|v1"), participant_count, public_trading_tick, rounds:[ChallengeRoundOut], my_entry`。**不含** `end_tt`、`ends_at`、seed、盐、`commitment_input`。
- ChallengeRoundOut：`round_index, state(pending|burst|open|closed|resolved), resume_at, closes_at, hold_at, event_id`；`hold_at` 与 `event_id` 到停顿时刻前为 null。
- ChallengeEntryOut：`entry_id, challenge_id, save_id|null, eligible, joined_at, answered_rounds, result`；EntryResultOut 为 `final_equity_cents, return_bp, forecast_score, trade_score, total_score, rank, eligible_count, points_awarded`。
- ChallengeRoundCardOut：`round_index, state, event, closes_at, questions, my_answers, my_revision, results`（逐题判定后出现，每题含 `peer`、`used`）、`my_round_score`、`crowd`（仅截止后，只统计合格报名）。
- LeaderboardOut：`scope(day|week|all), key, board, eligible_count, items, me, next_cursor`；LeaderboardItemOut 含 `equipped_title`、`return_bp` 与 `answered_rounds`（日榜）、`days_played`（周/总榜）、`is_me`。
- RevealOut：`challenge_id, challenge_date, status(settled|void), market_seed`（十进制字符串）、`seed_salt, seed_commitment, commitment_input, events_ruleset, clock_rules, format_version, start_minute, tick_ms, end_tt`（void 为 null）、`rounds:[{round_index, event_id, hold_tt, resolve_tts, resume_at, hold_at, closes_at}]`、`review_available`。
  - 本地校验：`sha256(commitment_input) == seed_commitment`；`commitment_input = "stocksim-challenge|v1|{date}|ruleset={n}|clock=2|seed={seed}|salt={salt}"`。seed 为 `HMAC-SHA256(派生密钥, "stocksim-challenge-seed|v1|{date}|{attempt}")` 前 8 字节大端、右移 1 位；派生密钥为 `CHALLENGE_SEED_KEY`（空则由 `SECRET_KEY` 派生）。
- ReviewOut：`challenge, entry, rounds, save_available`（master 或玩家存档被清理后 `save_available=false`）。

**WebSocket**（挑战存档的 `/api/v1/ws/saves/{id}`，03 §10.4）：
- 首帧，以及 `status/phase/round_index` 变化或有题目判定时发 `{"t":"challenge","challenge_id","status","phase","round_index","next_change_at","public_trading_tick","resolved_qids"}`；客户端收到后重拉 `/challenges/{id}` 与 `/rounds`。消息顺序 tick → phase → news → challenge → prediction → title → trade → achievement → auto_event。
- `next_change_at`（ChallengeOut 与 WS 同口径）：赛前为 `starts_at`；停顿中为下一回合恢复时刻；**快放段（burst）与最终段（final）为 null**（下一次变化 `hold_at` 与 `ends_at` 保密，到达后 `hold_at` 才出现）；结束为 null。
- 推送节奏：快放段每 `CHALLENGE_TICK_MS`（夹在 [200, 60000] ms）一轮；赛前、停顿、结束每 `CHALLENGE_HOLD_POLL_MS` 一轮。挑战存档的 ClockOut：`ms_per_minute` 仅快放段为 tick_ms、其余 null；`next_tick_at` 仅快放段有值；`fast_forward_at` 恒为 null；`next_event.at` 仅赛前为 `starts_at`。

**挑战存档与 `saves`**：
- `saves.mode` 取值：`normal`（普通）、`replay`（真实复盘，见 05 分册）、`challenge`（玩家挑战存档，`market_source_id` 指向 master，不计入 10 个存档上限，不出现在 `GET /saves`）、`challenge_market`（master，`user_id` 为空，无主）。全集以 `models/save.py` 与 06 §3.4 为准。
- 挑战存档拒绝的操作返回 409 `CHALLENGE_UNSUPPORTED {feature}`：`clock`（pause/resume/skip）、`debug`、`delete`、`auto_trade`；传闻提示返回 409 `INTEL_UNAVAILABLE {reason:"disabled"}`。挑战存档可正常下单；快放段经过 11:30 / 15:00 的那一个 tick 不接单（`MARKET_CLOSED`）；挑战结束后下单为 409 `CHALLENGE_ENDED`。
- 导出：挑战玩家存档的 `market_seed` 恒为 `null`，导出附加 `challenge: {challenge_id, challenge_date}` 块（仅 `mode=challenge` 且已报名）。seed 只经 `/challenges/{id}/reveal` 在结算或作废后公开；master 不可导出。

**调试入口**（仅 `ENABLE_DEBUG_API=true`，否则 403 `DEBUG_DISABLED`）：
- `POST /debug/challenges/ensure`，body `{date?:"YYYY-MM-DD"}` → ChallengeOut（按当前 `CHALLENGE_SCHEDULE` 生成或返回）。
- `POST /debug/challenges/{id}/shift`，body `{seconds: 1..86400}` → ChallengeOut：全部时刻整体前移，再执行 `run_due`；已结算或作废 409 `CHALLENGE_ENDED`。e2e 用它快进到结算。

**CLI**（`stocksim-challenge`，`pyproject.toml` 的 `[project.scripts]`）：`run-due`、`loop --interval 15`、`show [--date]`（结算前只显示承诺）、`void --date --reason`。

**配置**（`core/config.py`；`.env.example` 与 `docker-compose*.yml` 的 backend、`challenge-runner` 共用）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHALLENGE_ENABLED` | `true` | 关闭时挑战接口 404，`run_due` 空转 |
| `CHALLENGE_SEED_KEY` | 空 | seed 派生密钥（UTF-8）；空则由 `SECRET_KEY` 派生，生产必须设置 |
| `CHALLENGE_SCHEDULE` | `daily` | `compact` 仅开发与 e2e，要求 `ENABLE_DEBUG_API=true` |
| `CHALLENGE_SLOTS` | `07:00,12:00,17:00,20:30,23:00` | 北京时间，个数 = 回合数 + 1，严格递增 |
| `CHALLENGE_TICK_MS` | `750` | 快放段每交易 tick 的真实毫秒数，范围 1–826 |
| `CHALLENGE_HOLD_POLL_MS` | `5000` | 停顿段与赛前赛后的 WS 推送间隔 |
| `CHALLENGE_COMPACT_SLOT_SECONDS` / `CHALLENGE_COMPACT_TICK_MS` | `30` / `10` | 仅 compact |
| `CHALLENGE_MIN_ACCOUNT_AGE_HOURS` | `72` | 合格门槛：账号创建早于开局 N 小时；e2e 设 0 |
| `CHALLENGE_PLAYER_RETENTION_DAYS` / `CHALLENGE_MARKET_RETENTION_DAYS` | `14` / `30` | 清理保留期 |
| `CHALLENGE_RUN_DUE_MIN_INTERVAL_S` | `10` | 懒触发节流（每进程） |

## 真实复盘（05 分册，模式 E）

玩家选一个真实历史关卡，在看不到未来的前提下逐阶段推进（盘前 / 开盘 / 收盘 / 盘后）；行情来自离线构建的关卡包，不走合成引擎。存档是 `saves.mode='replay'`、`clock_rules=1`、`events_enabled=false`、`market_seed=0`，不写 `market_states` / `candles`。

**REST**（前缀 `/api/v1`，全部需登录；`save_id` 为他人存档或非复盘存档一律 `SAVE_NOT_FOUND`）：
- `GET /replay/levels?tag=&difficulty=&limit=&cursor=` → `{items:[ReplayLevelOut], next_cursor}`；只列 published，游标为 `"{sort_order}|{slug}"`。`ReplayLevelOut`：`slug, version, title, teaser, title_real, tags, difficulty, kind, play_days, stock_count, masked_allowed, my_best`；匿名关卡 `title`/`teaser` 取 `*_masked`，`title_real` 仅 `masked_allowed=false` 时给出；`my_best` 为 `{sessions, settled, best_points, best_excess_bp}` 或 null。
- `GET /replay/levels/{slug}` → ReplayLevelOut。
- `POST /replay/sessions` body `{level_slug, masked=true, name?≤20}` → 201 ReplaySessionOut。`masked=true` 但关卡 `masked_allowed=false` → 422 `VALIDATION_ERROR {field:"masked"}`；上限 `MAX_REPLAY_SESSIONS_PER_USER`（默认 10，含已结算）→ 409 `SAVE_LIMIT_REACHED {limit, mode:"replay"}`，与普通存档上限分开计。
- `GET /replay/sessions` → `{items:[ReplaySessionOut]}`（按创建时间倒序）；`GET /replay/sessions/{save_id}` → ReplaySessionOut。
- `POST /replay/sessions/{save_id}/advance` body `{to:"next_phase"|"next_day"="next_phase", expected_tick, skip_pending=false}` → AdvanceOut `{session, stale, stopped_reason, new_feed_items, scored_question_ids}`。`expected_tick` 与 `save.tick` 不符时 `stale=true` 且不推进。`stopped_reason ∈ phase|question_open|question_due|settled|null`：`next_day` 遇到题目开放停在 `question_open`，盘前有未答题停在 `question_due`（不推进）。越过截止且有未答题 → 409 `REPLAY_PREDICTION_PENDING {question_ids}`；`skip_pending=true` 时这些题记 0 分跳过。最后一日盘后再推进即结算。
- `POST /replay/sessions/{save_id}/finish` → ReplaySessionOut（提前结算，未答题记 0 分）。
- `GET /replay/sessions/{save_id}/feed?cursor=&limit=` → `{items:[ReplayFeedItemOut], next_cursor}`，只含当前可见事件，新的在前；游标为事件序号。`ReplayFeedItemOut` 与 A 的 `NewsOut` 同名字段（`news_id` 为 `"replay:{事件 id}"`，`stage="publish"`，`sentiment=null`，`subtype=null`），另有 `slot, time_label, date_label, targets, importance, body, source, url`（匿名下 `url=null`）。
- `GET /replay/sessions/{save_id}/questions` → `{items:[ReplayQuestionOut]}`，只含已开放的题（`status ∈ open|answered|closed|skipped|scored`）；答案不下发，计分后才有 `result`。
- `PUT /replay/sessions/{save_id}/questions/{question_id}/answer` body `{probs?:[int]（合计 100）, order?:[code]（长度 top_k，本会话可见代码，不重复）}` → ReplayQuestionOut。未开放 → 409 `REPLAY_QUESTION_CLOSED {state:"not_open"}`；已截止 → `{state:"closed"}`；截止前可反复覆盖。
- `GET /replay/sessions/{save_id}/benchmark` → `{name, points:[{trading_day, date, close}]}`，只到当前已收盘日。
- `GET /replay/sessions/{save_id}/reveal` → RevealOut；未结算 → 409 `REPLAY_REVEAL_LOCKED`。含真实代码与名称、真实日期的完整 K 线（回看 + 游戏 + 揭示）、事件真实标题与 `impact`（`ar_1d_bp`、`ar_5d_bp`）、题目对错与 `result`、资产曲线、`hold_all_return_bp`（关卡股票等权买入持有，锚点为 T0 收盘至游戏末日收盘）、`benchmark_return_bp`、`commentary`。
- 复用：`GET /saves/{id}/market`、`/market/{code}`、`/market/{code}/intraday`、`POST /saves/{id}/orders`、`/portfolio`、`/trades`、`/equity-curve`、`/watchlist/{code}`、`GET /saves/{id}/export`、`DELETE /saves/{id}`（形状不变，经 `services/market.py` 的复盘分发）。

**存档与普通接口**：
- `GET /saves` 与 `POST /saves` 的计数只看 `LISTED_MODES`，复盘存档不出现、不计入 `MAX_SAVES_PER_USER`。
- 复盘存档的 ClockOut：`paused=true`，`clock_rules="v1"`，`ms_per_minute`、`next_tick_at`、`fast_forward_at`、`next_event.at` 均为 null；阶段按 v1 由分钟推出（540 盘前 / 570 开盘 / 900 收盘 / 960 盘后）。
- 复盘存档拒绝：`/clock/pause|resume|skip` → 409 `REPLAY_UNSUPPORTED {feature:"clock"}`；`/supply-chain` → `{feature:"supply_chain"}`（决策 16）；`/auto-trade/configs` 的建改、`start`、`resume` → `{feature:"auto_trade"}`；调试接口 → `{feature:"debug"}`；`/day-summary` → `{feature:"day_summary"}`；WebSocket `/ws/saves/{id}` 先推 `{t:"error", code:"REPLAY_UNSUPPORTED"}`（WS 错误消息不带 params）再以关闭码 4409 关闭。
- 下单：盘前、盘后返回 `MARKET_CLOSED`；开盘与收盘阶段按当前阶段价成交（开盘价 / 收盘价）；`REPLAY_STOCK_SUSPENDED`（停牌）；`REPLAY_LIMIT_LOCKED`（开盘或收盘封板时买入、封跌停时卖出）；`REPLAY_SESSION_SETTLED`（已结算）。涨跌幅按板块（主板 10%，创业板/科创板 20%，北交所 30%）。
- 导出：`market_seed` 为 `"0"`，只含别名代码的成交与持仓，不含关卡包。
- 股票名称与代码：会话内全部为别名（匿名）或真实（实名），匿名模式下日期为假日历（从 2001-01-01 起连续工作日）。

**积分**：每题计分只调用 `domain/scoring.py`（`rps_score`、`ndcg_at_k_score`、`bucket_of`），积分只走 `services/points.py::credit`，`reason="replay_prediction"`，幂等键 `replay:{user_hex}:{level_hex}:{qid}`（按关卡而非版本）。只有该用户对该关卡的首个会话入账，积分 = 分数 ×1.0（匿名）或 ×0.5 四舍五入（实名）；交易盈亏不发积分。

**配置**：`REPLAY_PACKS_DIR`（空 = `backend/replay/packs`）、`REPLAY_IMPORT_ON_STARTUP`（默认 true，lifespan 在种子之后导入，失败只记日志）、`MAX_REPLAY_SESSIONS_PER_USER`（默认 10）。离线抓取配置 `REPLAY_DATA_DIR` / `REPLAY_RATE_*` 只给 `replay_ingest` CLI 使用，不进 `Settings`。

**手动导入**：`python -m stocksim.services.replay.cli import <文件或目录>`（同一导入逻辑：sha256 相同跳过，同一版本内容不同拒绝）。

## 预测市场（04 分册，模式 D）

只在每日挑战的 4 个回合事件上开市（每个回合事件 1 个分档合约，传闻再加 1 个真假合约，每场最多 8 个）。做市为 LMSR（`domain/prediction_market/`，Decimal 定价，整数积分与份额）。补贴 S 按预计人数取 1000/2000/4000 积分，由资金池承担最大亏损（上界为 S）。用户积分经 B 的账本（reason `market_buy/market_sell/market_payout/market_refund`），补贴记在市场行。状态以挑战公共时间线为准（scheduled → open → closed → resolved，任意非终态 → voided）。

**REST**（前缀 `/api/v1`，全部需登录；`CHALLENGE_ENABLED=false` 时一律 404 `CHALLENGE_NOT_FOUND`）：
- `GET /prediction-markets?challenge_id=&status=all|open|closed|resolved|voided&limit=1..50&cursor=` → `PmMarketPageOut {items: PmMarketOut[], next_cursor, public: PmPublicClockOut}`。`challenge_id` 缺省为当前挑战；永不含 scheduled。排序 `(open_tt 降序, id 升序)`，游标 base64url `[open_tt, id]`。
- `GET /prediction-markets/{id}` → `PmMarketDetailOut`（另含 `q_shares`、`window_change_bp`、`my`、`limits`、`balance_points`）。
- `GET /prediction-markets/{id}/quote?side=buy|sell&outcome=0..7&shares=1..200|budget_points=` → `PmQuoteOut`（只读报价，不扣款）。
- `POST /prediction-markets/{id}/trades`，**必须**带头 `Idempotency-Key`（≤64，缺失 422）；body `PmTradeIn {side, outcome, shares?, budget_points?, max_cost_points?, min_proceeds_points?}`（extra=forbid；买入二选一 shares/budget，卖出只能 shares 且可给 min_proceeds）→ 201 `PmTradeResultOut {trade, market, my, balance_points, replayed:false}`；同键同市场重放 200 `replayed:true`；同键不同市场 422 `VALIDATION_ERROR {field:"Idempotency-Key"}`。滑点：买入 `max_cost_points`（预算买入默认等于预算）、卖出 `min_proceeds_points`，越限 409 `PM_SLIPPAGE_EXCEEDED`。
- `GET /prediction-markets/{id}/history?max_points=10..500` → `PmHistoryOut {market_id, items:[{seq, public_tt, at, prices_ppm}]}`，首点为开盘先验（seq=0），末点必含。
- `GET /prediction-markets/{id}/trades?cursor=` → `PmTapePageOut`：匿名成交带，按 seq 降序，每页 50 条，不含 user。
- `GET /me/prediction-positions?status=active|settled&cursor=` → `PmPositionPageOut {items: {market, my}[], next_cursor}`（active = open/closed，settled = resolved/voided）。
- `GET /me/prediction-settlements?cursor=` → `PmSettlementPageOut`，按 created_at 降序。
- 调试（`ENABLE_DEBUG_API`，关闭时 403 `DEBUG_DISABLED`）：`POST /debug/prediction-markets/{id}/void {reason?≤32}` → `PmMarketDetailOut`（作废原因 `manual`）；`POST /debug/prediction-markets/sync` → `{changed}`（立即执行一轮 sweeper）。

**数值常量**（`domain/prediction_market/constants.py`）：分档每份兑付 100 积分；单笔份额 1..200；补贴 `SUBSIDY_TIERS = ((0,1000),(30,2000),(150,4000))`；单市场净投入上限 `max(200, S//4)`；单场挑战累计买入额度 3000；频率每用户 60 s 内 12 笔（跨市场）；每场挑战市场数上限 8。传闻先验 `(deny 0.3, confirm 0.7)`；分档先验为 `BUCKET_PRIOR_PPM`（v2 统计）。

**保密**：响应不含 `event_fingerprint`、01 §1.8 的隐藏字段与 scheduled 市场；open 状态的传闻合约不含 `close_tt/resolve_tt/closes_at/resolves_at`。
**作废与退款**（04 §3.5）：挑战撤销 `challenge_revoked`、事件指纹不符 `event_mismatch`、结算数据缺失 `data_unavailable`、规则集变化 `ruleset_changed`、人工 `manual`。退款为每人 `max(0, 净投入)`。

## 数据库
事件模式（01 §9.1）：`saves.events_enabled` bool NOT NULL server_default `0`（只在创建时设置）、`saves.events_ruleset` int NOT NULL server_default `0` CHECK `>= 0`（关闭为 0，开启为 `EVENT_RULESET_VERSION`=1）。迁移 `a26942b8c903`（down_revision `361472202775`）。预测卡 / 积分 / 情报 / 称号（02 §9）迁移 `8ed22ae1e201`（down_revision `a26942b8c903`，单一 head，无 batch 操作）新增 8 张表：`point_accounts`、`point_ledger`（UQ user_id+idempotency_key、user_id+seq；CHECK balance_after≥0）、`prediction_settings`、`prediction_cards`（UQ save_id+event_id）、`prediction_answers`（UQ card_id+qid）、`intel_edge_reveals`（UQ user_id+edge_id）、`intel_rumor_hints`（UQ save_id+event_id）、`user_titles`（UQ user_id+title_id）。事件本身不落库。每日挑战（03 §6）迁移 `f5aae30ea648`（down_revision `8ed22ae1e201`）：`saves` 重建，`user_id` 可空（CHECK `user_id IS NOT NULL OR mode='challenge_market'`），新增 `mode` 取值 `challenge` / `challenge_market` 与 `market_source_id`（CHECK 仅 `mode='challenge'` 可设）；新增 4 张表：`challenges`（`challenge_date` 唯一，`clock_rules=2` CHECK，`version` 乐观锁）、`challenge_rounds`（`(challenge_id, round_index)` 与 `(challenge_id, event_id)` 唯一）、`challenge_entries`（`(challenge_id, user_id)` 与 `save_id` 唯一）、`challenge_answers`（`(round_id, entry_id)` 唯一，`revision ≥ 1`）。
SQLAlchemy 2.x 同步，`DATABASE_URL` 切换（sqlite 默认 `sqlite:///./data/stocksim.db`，`postgresql+psycopg://`，`mysql+pymysql://...charset=utf8mb4`）。主键 `sa.Uuid`；JSON 用 `JSON().with_variant(JSONB,"postgresql")`；String 必须有长度；`MetaData(naming_convention=...)`；Alembic `render_as_batch=True`。
表：users, sessions, stocks, saves, save_stats, save_sectors, holdings, trades, watchlist_items, market_states, candles, auto_trade_configs, auto_trade_events, save_achievements, legacy_imports, equity_snapshots，以及预测卡 B 的 point_accounts, point_ledger, prediction_settings, prediction_cards, prediction_answers, intel_edge_reveals, intel_rumor_hints, user_titles（字段见 backend/src/stocksim/models/CLAUDE.md；以代码为准），以及每日挑战 C 的 `challenges`、`challenge_rounds`、`challenge_entries`、`challenge_answers`，以及预测市场 D 的 `prediction_markets`、`prediction_market_outcomes`、`prediction_positions`、`prediction_trades`、`prediction_settlements`（迁移 `pm01d4000001`，04 §6），以及真实复盘 E 的 `replay_levels`、`replay_level_versions`、`replay_sessions`、`replay_predictions`（迁移 `rp01e2000001`，down_revision `pm01d4000001`，05 §5.2；`replay_levels.current_version_id` 与 `replay_level_versions.level_id` 互引，前者在建表后用 batch 补外键）。

## 前端
`frontend/src/`：`api/ state/ i18n/ ui/ features/<name>/ styles/ main.js`。禁止直接 innerHTML 拼接用户数据，必须用 `ui/html.js` 的默认转义 tagged template。i18n 双语 key 必须对齐（复用 legacy/locales，新增错误码文案放 `i18n/errors.js`）。HTML 结构复用 legacy/index.html。
