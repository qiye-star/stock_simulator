# 架构说明

本文描述重构版（v2）的分层与数据流。契约（API、错误码、领域规则）见 [CONTRACT.md](CONTRACT.md)，关键取舍见 [adr/](adr/README.md)。

## 1. 总览

```
浏览器 ──HTTP/WS──► frontend (nginx 或 vite dev)
                       │  /api/*  /api/v1/ws/*
                       ▼
                    backend (FastAPI, 单 worker)
                       │  SQLAlchemy 2 (同步)
                       ▼
          sqlite | postgres | mysql
```

- `backend/`：FastAPI + SQLAlchemy 2 + Alembic，使用 uv 管理依赖，包名 `stocksim`，源码在 `backend/src/stocksim/`。
- `frontend/`：Vite + 原生 ES 模块，无框架。源码在 `frontend/src/`。
- 部署：`docker-compose.yml` 编排 `migrate -> backend -> frontend`，数据库通过 profile 可选 postgres / mysql。

## 2. 后端分层

依赖方向只能从上往下：

```
api/routers   HTTP/WS 入口：参数校验（schemas）、鉴权、调用 services、映射错误码
   │
services      用例编排：开事务、读写 models、调用 domain 纯函数、产生副作用（DB、WS 推送）
   │
domain        纯函数领域逻辑：撮合、涨跌停、费用、T+1、确定性行情引擎。零 I/O
```

辅助包：

| 包 | 职责 |
| --- | --- |
| `core/` | 配置（`config.py`）、错误码（`errors.py`）、密码与会话（`security.py`） |
| `db/` | `Base`、会话工厂、自定义列类型（`types.py`，如 JSON 的方言变体） |
| `models/` | SQLAlchemy 表定义，任何改动必须配 Alembic 迁移 |
| `schemas/` | Pydantic 请求/响应模型，金额字段统一为整数分，名称以 `_cents` 结尾 |
| `data/` | 股票池等静态数据（`stock_pool.json`） |

约束：

- `domain/` 禁止 import `sqlalchemy`、`fastapi`，禁止调用 `datetime.now()`、全局 `random`。时间与随机数由调用方注入，因此可以用固定输入做单元测试。
- 金额一律整数分；费率使用 `Decimal` 或字符串，避免浮点误差。
- 错误以 `ErrorCode` 返回，HTTP 体为 `{"code": "...", "params": {...}}`，前端据此本地化。

## 3. 确定性行情引擎

行情不依赖真实行情接口，也不依赖进程内的随机状态，而是由 `(seed, tick, stock_idx, k)` 唯一决定：

- `domain/rng.py` 实现计数器式 splitmix64：`rand01(seed, tick, stock_idx, k) -> float[0,1)`。同样的输入永远得到同样的输出。
- 时钟规则按存档分版本（`saves.clock_rules`）。v1：每个交易日 20 个 tick，单 tick 波动 ±2%，换日在 tick%20==0。v2：每个交易日 242 个交易 tick（每个交易分钟一个），换日在次日 9:30，单 tick 噪声由特质项、全市场共同因子与日趋势组成，标定见 `scripts/clock_v2_sim_report.py`。两版均为涨跌停 ±10%，价格四舍五入到分。
- 存档记录当前 tick 与种子；行情状态可以从任意 tick 重放，结果与是否实时观察无关。

### 补帧（catch-up ticks）

用户关闭页面、服务重启或暂停时间后，服务端根据存档记录的最后 tick 与当前时间计算应当推进的 tick 数，并按确定性规则逐个补算。v1 按刷新间隔逐分钟推进；v2 按锚点（`last_tick_at`）与停留时长推演：11:30 停留后跳到 12:59，15:00 收盘停留后跳到次日 9:29（纯函数 `domain/clock.plan_catchup_v2`，与手动“跳过”共用推进路径）。

1. 读取 `market_states` 中的最后 tick；
2. 依据时钟（运行中的时间 / 暂停 / 跳过）算出目标 tick；
3. 对区间内每个 tick 调用 domain 引擎，结果写入 `candles` 并更新五档与涨跌停价；
4. 补算过程中触发的自动交易规则按 tick 顺序执行，保证结果可复现。

因为补帧是纯函数推导，同一存档在任何设备、任何时刻重放得到的 K 线都一致，这也是自动化测试与"对拍 legacy"的基础。

### 事件漂移（事件行情，`docs/10.26-plan/01-事件行情.md`）
事件模式的存档（`saves.events_enabled`）在行情推进时叠加一项确定性的个股漂移：`domain/events/` 由 `(market_seed, events_ruleset, clock_rules, 排期日)` 纯函数生成事件与当日漂移计划（`{stock_idx: ppm}`，按交易 tick 索引），`market_engine.advance(..., drift=)` 把漂移叠加到每 tick 的随机涨跌幅上，熔断与涨跌停钳制照旧。事件不落库、不进 `market_states.payload`，任何时候都能由 seed 重建；关闭事件的存档 `drift=None`，结果与未引入事件时逐位一致。发布时刻命中 `services/event_hooks` 的发布钩子时可暂停存档（B 的预测卡使用）。

## 4. 数据流

### 4.1 下单

```
POST /saves/{id}/orders
  -> api/routers/orders.py     校验 schema、取当前用户
  -> services/trading.py       加载存档 + 持仓 + 当日 trades（推导 T+1）
  -> domain/trading.py         纯函数：校验数量、涨跌停、限价、资金、费用
  -> services（写库）          trades / holdings / save_stats 同一事务提交
  -> ws 推送 {"t":"trade",...}
```

限价单规则（契约）：买单限价 ≥ 市价则按市价成交，否则拒绝 `ORDER_LIMIT_NOT_REACHED`；卖单反之。

### 4.2 行情与实时推送

```
浏览器 WS /api/v1/ws/saves/{id}
  <- {"t":"tick", ...}     服务端在 tick 产生后推送（进程内广播）
浏览器 GET /saves/{id}/market/{code}   日 K + 五档 + 涨跌停价（按需拉取）
```

WebSocket 连接由 nginx 长期保持（读超时 1 小时），应用层不做心跳以外的会话状态。

### 4.3 自动交易

`auto_trade_configs` 保存规则，`auto_trade_events` 记录触发历史。规则在补帧与实时 tick 中以同一套 domain 函数求值，保证"离线期间触发的规则"与"在线期间触发的规则"结果一致。

## 5. 前端结构

```
frontend/src/
  api/        fetch 封装与 REST/WS 客户端
  state/      单一状态仓库，订阅式更新
  i18n/       双语文案；错误码文案在 i18n/errors.js
  ui/         基础组件与 ui/html.js（默认转义的 tagged template）
  features/   按功能切分：trading、market、saves、achievements、auto-trade ...
  styles/     样式（沿用 legacy/styles.css 的结构）
  main.js     入口
```

约束：禁止直接 `innerHTML` 拼接用户数据，一律通过 `ui/html.js` 渲染，默认转义。

## 6. 部署拓扑

| 容器 | 镜像 | 说明 |
| --- | --- | --- |
| `migrate` | `stocksim-backend` | 运行 `alembic upgrade head` 后退出 |
| `backend` | `stocksim-backend` | `uvicorn --workers 1`，healthcheck `/api/v1/healthz` |
| `challenge-runner` | `stocksim-backend` | `stocksim-challenge loop --interval 15`，与 backend 共用环境变量；推荐生产开启（见 deployment.md §6a） |
| `frontend` | `stocksim-frontend` | nginx-unprivileged，监听 8080，反代 `/api/` 与 WS |
| `postgres` / `mysql` | 官方镜像 | 仅在对应 profile 下启动 |

详见 [deployment.md](deployment.md)。

## 7. 为什么是单 worker

行情引擎的时钟推进、WebSocket 的订阅表都在进程内。多 worker 会导致同一存档在不同进程中被重复推进、推送不到订阅者。在引入外部消息总线之前，只能水平扩展为"多实例 + 按存档粘性路由"，目前不做。

## 预测市场与全服推送（04 分册，模式 D）

**开市对象**：只在每日挑战的回合事件上开市（`services/challenges/registry.round_event_ids`），每场 4–8 个市场。市场按挑战公共时间线（`public_trading_tick`）开市、关市、结算，状态以公共 tt 为准，`services/pm_lifecycle.py` 连跳到应达状态。

**做市**：LMSR（`domain/prediction_market/lmsr.py`），`decimal` 在固定上下文中计算，份额与积分全为整数，买入向上取整、卖出向下取整。补贴 S 由预计人数定（1000/2000/4000），资金池的最大亏损以 S 为界；池余额为负不可能（结算前有断言日志）。

**一致性**：下单在一个事务内完成：先 `sync_market`（推进状态），再 `FOR UPDATE` 锁市场行（SQLite 忽略，靠 `version` 乐观锁与 `Idempotency-Key` 唯一键兜底），积分经 `services/points.py` 的 `debit/credit`（reason `market_*`）记账。守恒式：账本 `market_*` 流水合计 + 池余额 = 发行补贴 − 退回补贴，任何时刻成立。

**推送**：全服通道 `WS /api/v1/ws/prediction-markets`。每个进程一个 `PmHub`（`api/pm_ws.py`），每 `PM_POLL_MS`（默认 1000 ms）轮询数据库中被关注挑战的市场快照做差分，向订阅者扇出 `pm_tick` / `pm_list` / `pm_resolved`；每 `PM_SWEEP_MS`（默认 10 s）执行 sweeper（`pm_lifecycle.sync_due`），与有无连接无关，保证无人访问时也能结算。客户端断线后退回 REST 轮询。

**多实例**：状态全部在数据库，每个实例的 Hub 各自轮询，不需要粘性会话，也不需要消息总线。sweeper 在每个实例上都执行，靠行锁、版本号与幂等键保证只生效一次。代价是 `实例数 × 被关注挑战数` 次/秒的小查询，配合 `(challenge_id, status)` 索引可以忽略。推荐生产使用 PostgreSQL（SQLite 多进程写入会频繁 busy，`PM_BUSY` 概率随并发上升）。`PM_BACKGROUND_ENABLED=false` 可关闭某个实例上的 Hub 与 sweeper（如只用于 API 的副本）。

## 每日挑战时间线（03 分册，模式 C）

- **全服一条时间线**：每天一场挑战共用同一份无主 master 行情（v2 时钟，开局 9:30 即 tt=0，每个交易日 242 个交易 tick）。回合停顿点 `hold_k` 与恢复时刻 `resume_k` 在开局时排程固定，真实时间到达前任何人都看不到未来行情。
- **tt 映射**（`domain/challenge/timeline.py`，纯函数、不读时钟）：`now < resume_1` 时 tt=0；快放段内每 `tick_ms` 前进一格；停顿段 tt 固定在 `hold_k`；终局后为 `end_tt`。作答窗口为 `[hold_at_k, resume_{k+1} − 5 s)`，5 s 抵消多实例的时钟偏差。
- **推进**：`services/challenges/sync.advance_master` 把 master 推到 `tt(now)`，在每个 `hold_k` 与题目判定 tick 精确停下（同一事务，先出题后判定）。一次懒推进跨越多个检查点，与逐秒推进结果相同。
- **玩家存档**：`mode='challenge'` 只保存资金、持仓与成交；行情经 `market_source_id` 读 master，`sync_entry_save` 只镜像 master 的 tick、分钟、交易日与暂停状态，永不超前。
- **触发**：挑战路由与玩家同步先经 `runner.maybe_run_due`（进程内 10 s 节流）；`stocksim-challenge loop` 每 15 s 执行 `run_due` 的六步（生成、开始、推进、关闭钩子、结算、清理），每步独立短事务并全部幂等，多实例并存安全。

## 预测卡与积分账本（02 分册，模式 B）

- **挂载点**：预测卡只通过 A 的事件扩展点接入（`services/event_hooks.py`）。`main.create_app` 调用 `predictions.register_hooks()`（发布钩子 `on_publish` 与 reset 钩子 `on_reset`）与 `intel.register_hooks()`（揭示 provider）。`market._run_ticks` 的推进循环在重大事件第一条快讯 tick 调用发布钩子，返回 True 即暂停存档并截停本批，行情与预测逻辑不互相渗透。
- **分层**：计分与出题是 `domain/`（`scoring.py`、`predictions/`）的纯函数；积分账本 `services/points.py` 是唯一的记账入口，`credit/debit` 不 commit，由 `services/tx.py::run_in_transaction` 包住（乐观锁与唯一约束冲突时回滚重做）。卡片、作答、结算、情报与称号在 `services/predictions.py`、`services/intel.py`、`services/titles.py`。
- **时间**：截止与结算按交易 tick 计，交易日换算一律经 `domain.clock.timebase(save.clock_rules)`，v1 与 v2 存档都适用。
- **结算**：`settle_due` 幂等，由读接口与 WebSocket 每轮调用；全部题结算后 answered → settled 入账，幂等键 `prediction:{card_id}`，每用户每 UTC 日上限 `PREDICTION_DAILY_POINTS_CAP`（超出部分不发，`points_capped`）。
- **保密**：题目公开 JSON 只含白名单字段，结果逐题在结算后给出（`docs/CONTRACT.md` 的预测卡段）。
- **数据**：迁移 `8ed22ae1e201` 新增 8 张表（`point_accounts`、`point_ledger`、`prediction_settings`、`prediction_cards`、`prediction_answers`、`intel_edge_reveals`、`intel_rumor_hints`、`user_titles`）。
- **扩展**：C（每日挑战）与 E（真实复盘）只通过 `register_card_policy`、`points.credit`、`scoring` 与 `structure_for` / `change_bp_for` / `answers_for_event` 接入，不改预测卡内部。

## 复盘数据流（05 分册，模式 E）

- **离线**：`backend/src/stocksim/replay_ingest/`（只在 ingest 依赖组内抓取，运行时不导入）抓 AKShare 原始数据落盘（`REPLAY_DATA_DIR`），`build` 确定性地生成关卡包 JSON（`backend/replay/packs/<slug>/v<N>.json`，进 git），`verify` 校验脱敏与复权。
- **导入**：`services/replay/pack.py` 用 pydantic（`extra="forbid"`）与跨字段校验解析包；`services/replay/levels.py` 按 (slug, version) 幂等写入 `replay_level_versions`（sha256 相同跳过，不同则拒绝），启动时 lifespan 扫描 `REPLAY_PACKS_DIR` 导入。
- **行情分发**：复盘存档在 `services/market.py` 的函数开头分发（`load_market`、`stock_market`、`intraday`；推进与时钟操作一律拒绝或返回 0），下游的 `trading`、`portfolio`、`market_overview` 不改签名。`services/replay/state.py` 把 (关卡包, 存档位置) 映射为与 `decode_state` 同形的状态（匿名时代码取别名、价格按 `mask_scale_ppm` 缩放，`domain/replay.py` 的纯函数完成缩放、夹紧与阶段报价）。
- **推进**：`services/replay/sessions.py` 以 `save.tick = day*4 + 阶段序号` 为时间轴；推进、计分、快照与结算在同一事务内（`services/tx.py::run_in_transaction`）。离开收盘阶段写当日权益快照（`equity_snapshots`）。
- **下单守卫**：`market.trade_guard(state, code, side)` 在 `trading._place_once` 中于撮合之前执行（已结算 / 停牌 / 封板），普通存档恒为 None。
- **事件流**：`services/replay/feed.py::to_feed_item` 是唯一的 A 快讯适配点，`event_visible`（domain）按 (日, 阶段) 过滤；揭示页 `reveal.py` 给出真名、真日期与事件影响。
- **预测与积分**：`services/replay/predictions.py` 计分调用 `domain/scoring.py`，积分只走 `services/points.py::credit`（幂等键按用户与关卡），与预测卡、挑战共用同一账本。
- **防剧透**：所有接口只经上述纯函数与 `state.py` 取数，关卡包本身不下发；匿名模式下代码、名称、日期、链接均脱敏，揭示页前不出现真实代码（集成测试逐阶段断言）。

