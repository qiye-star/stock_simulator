# js/lib/ — 基础设施

| 文件 | 导出 | 说明 |
| --- | --- | --- |
| `html.js` | `SS.html` `SS.raw` `SS.mount` `SS.el` `SS.$/$$` `SS.icon` `SS.haptic` `SS.reducedMotion` | 转义模板与 DOM 小工具、线性图标 |
| `format.js` | `SS.fmt` | 金额（分）/基点/股数/成交量/时钟/时段文案；`parseYuan` 输入转分 |
| `api.js` | `SS.api` `SS.ApiError` `SS.isMock` | 同源 `/api/v1` fetch 客户端（Cookie 会话、错误体 `{code,params}`、401 回调）；`?mock=1`/file:// 模式开关 |
| `store.real.js` | `SS.store`（真实模式） | 内存缓存 + REST + WebSocket 推送（断线轮询）；时钟字段白名单 `CLOCK_KEYS`（ClockOut / tick.clock 的 v2 字段，收到 `server_time` 时写 `_offset_ms`），WS `phase` 消息 emit `phase`；`setClockSpeed(speed)`（`PATCH /me {clock_speed}`）、`loadDaySummary(tradingDay?)`（`GET /day-summary`）；新建存档显式 `clock_rules: 2`；`isTrading()` 取 `normalize(...).trading`（与暂停无关）；方法/事件与 `store.js` 一致，写操作返回 Promise；另有 init/login/logout/存档管理/loadDetail；行情分页 `listQuotes({q,sort,order,cursor,limit,watchlisted})→{items,next_cursor,total}`、`loadQuote(code)`、`loadAllQuotes()`、分时 `loadSeries(codes)`（完成后 emit `series`）；时钟 `skipClock()`（`POST /clock/skip`）、`applyClock(c)`、`setPaused`、`setRefreshRate`；WS 未知消息 emit `ws:<t>` 透传给玩法功能 |
| `store.js` | `SS.store`（假数据模式） | 内存状态 + 假 API：行情 tick；v1 节奏（午休/收盘后时钟照走，只有交易分钟变价）；v2 调度器（`scheduleV2`/`fireV2`/`publishV2`，停留与快进、换日、收盘日 K、`phase` 事件）；`setClockSpeed`、`loadDaySummary`；`skipClock()`（v1 `skipTargetOf`，v2 `skipTargetV2`）、下单（费用/T+1/限价/涨跌停校验，抛 `ApiError{code}`）、持仓计算、自选、自动交易 CRUD；事件 `tick` `order` `auto` `watchlist` `save` |
| `clock-model.js` | `SS.clockModel` | 时钟纯函数（无 DOM、不读 store）：`normalize(state.clock, opts)` 把 ClockOut/WS tick.clock 归一化（v2 字段缺失按 v1 推算，`derived=true`）；`view(c, {now})` 生成状态栏文案；`skipTargetOf(m)`（v1，与后端 `skip_target_minutes` 一致）与 `skipTargetV2(m)`（07 §6.5）；v2 调度镜像 `stepV2(m, ms, dwell)`、`msUntilV2`；`closeTimer(c, {now,total_ms})` 收盘小结倒计时；`untradableText(c)` 下单被拒文案；速度档 `SPEEDS_V1/V2`、`speedOf`、`formatReal/formatCountdown` |
| `predict-math.js` | `SS.predictMath` | 预测卡共用纯函数：`probsFromPick`（档位+把握→分布，与 02 §5.2 同式）、`argmaxPick`、`confRange`、`bucketLabels`、`bucketRangeText`（⑥） |
| `slots.js` | `SS.features` `SS.slots` `SS.guards` `SS.marketLists` `SS.assertSameKeys` | 玩法注册机制（08 §3.2）：挂载点 `mount/html/has/register`、动作守卫 `guards.add/check`（如 `resume`）、行情分段注册；provider 抛错不影响宿主 |
| `chart.js` | `SS.chart` | sparkline / intraday / kline / area 生成 SVG 字符串；`crosshair` 拖动读数 |
| `router.js` | `SS.router` `SS.href` | hash 路由（`add/navigate/replace/back/start`），`params.query` 为 hash 中 `?` 之后的参数；`SS.href(path, query)` 拼链接；一级页记忆滚动位置 |

## 不变量
- 行情缓存只含已加载的股票：持仓/自动规则涉及的代码由 `ensureAccountQuotes` 保证在缓存内，其余页面用 `quote(code)` 前须经 `listQuotes/loadQuote/loadAllQuotes`。分时 `_series`（按分钟下标，供分时图）与 `_spark`（当日逐 tick，供迷你图）都由后端分时点重建；WS tick 只在已加载历史的股票上追加，漏 tick/跨日重新拉取，禁止插值。
- `store.js` 与 `store.real.js` 的对外方法必须同名同义；改一个要改另一个。真实版里 `toggleWatch`/`autoToggle` 是乐观更新（同步返回），其余写操作 `await`。
- 真实模式不得往后端发 schema 之外的字段（`AutoConfigIn` 是 `extra=forbid`，store 里已按白名单过滤）。
- store 的方法名与 REST 端点对应（文件头有映射），错误码取自 `docs/CONTRACT.md`。
- 下单规则与契约一致：限价买 ≥ 市价按市价成交，否则 `ORDER_LIMIT_NOT_REACHED`；手续费单独四舍五入到分。
- chart 只输出 class（up/down/accent），颜色由 CSS 决定。
- 时钟字段只经 `SS.clockModel.normalize` 读取；`clock-model.js` 必须保持纯函数（`tests/` 在 node:vm 里加载它，加载时不得访问 `document`/`localStorage`）。
- `SS.emitLocal(evt, payload)`（两套都有）用于本地广播，如速度改变后 `emitLocal("user", …)` 刷新“我的”。

## ⑤ 变更（快讯 / 事件）
- `api.js`：`SS.api.missing`（Set，本会话内记住的缺失功能名）与 `SS.api.isMissing(err)`（`HTTP_404/405/501`）。功能 store 的 `guarded()` 用它把缺失接口转为 `FEATURE_UNAVAILABLE`。
- `store.real.js`：`createSave(name, {events_enabled})`（事件模式，创建后不可改）；`ERROR_TEXT` 新增 `EVENTS_DISABLED`、`EVENT_NOT_FOUND`、`SUPPLY_EDGE_NOT_FOUND`、`FEATURE_UNAVAILABLE`。WS 未知消息 `news` 经 `default` 分支 emit `ws:news`（核心不处理，由 `features/news/index.js` 订阅）。
- `slots.js`：`marketLists.register` 的 `empty` 字段（分段无数据时的文案）。行情页按 `SS.marketLists.list()` 渲染分段按钮。
- `store.js` / `store.real.js` 的 `SS.store` 上由功能 store 追加 `ensureNews/newsFeed/majorNews/listNews/listEvents/loadEvent/loadSupplyChain/newsEnabled/resetNews`（两套同名，见 `js/features/news/store.js`）。

## ⑧ 变更（预测市场）
- `store.js` 与 `store.real.js` 的 `ERROR_TEXT` 新增 04 §9.3 的 `PM_*` 共 11 个错误码（`PM_NOT_FOUND`、`PM_NOT_OPEN`、`PM_LOCKED_AHEAD`、`PM_NOT_ELIGIBLE`、`PM_SLIPPAGE_EXCEEDED`、`PM_INSUFFICIENT_SHARES`、`PM_TRADE_TOO_SMALL`、`PM_POSITION_LIMIT`、`PM_DAILY_LIMIT`、`PM_RATE_LIMITED`、`PM_BUSY`）。预测市场的方法由 `features/pm/store.js` 追加到 `SS.store`（两套同名），`onPredictions` 为进程内广播。

## ⑦ 变更（每日挑战）
- `store.js` 与 `store.real.js` 的 `ERROR_TEXT` 新增 `CHALLENGE_NOT_FOUND`、`CHALLENGE_NOT_STARTED`、`CHALLENGE_ENTRY_CLOSED`、`CHALLENGE_ENDED`、`CHALLENGE_NOT_ENTERED`、`CHALLENGE_ROUND_NOT_FOUND`、`CHALLENGE_ROUND_CLOSED`、`CHALLENGE_ANSWER_LIMIT`、`CHALLENGE_NOT_SETTLED`、`CHALLENGE_UNSUPPORTED`（03 §10.3）。
- `store.real.js` 的 `switchSave(id)`：挑战存档不在 `GET /saves` 列表里，找不到时按 id 直接取 `GET /saves/{id}`。
- `store.real.js` 的 `init()`：上次存档（`ss.saveId`）不在普通存档列表时（例如停在挑战存档），回退到 `ss.returnSaveId`（参加挑战前的存档），再回退到第一个。
- 挑战的方法由 `features/challenge/store.js` 追加到 `SS.store`（两套同名）；挑战相关的 WS 消息 `challenge` 经默认分支 emit `ws:challenge`。

## ⑥ 变更（预测卡 / 积分 / 情报卡）
- `store.js` 与 `store.real.js` 的 `ERROR_TEXT` 新增 `PREDICTION_NOT_FOUND`、`PREDICTION_CLOSED`、`POINTS_INSUFFICIENT`、`INTEL_LIMIT_REACHED`、`INTEL_UNAVAILABLE`、`TITLE_NOT_UNLOCKED`；mock 表补齐 A 的 `EVENTS_DISABLED`、`EVENT_NOT_FOUND`、`SUPPLY_EDGE_NOT_FOUND`、`FEATURE_UNAVAILABLE`。
- `store.real.js` 的 `init()` 自动创建的第一个存档显式 `events_enabled: true`（决策 14：新建存档事件模式默认开）。
- 预测卡的 WS 消息 `prediction` / `title` 经默认分支 emit `ws:prediction` / `ws:title`，核心不处理，由 `features/predict/index.js` 订阅。
- `store.js` / `store.real.js` 的 `SS.store` 上由 `features/predict/store.js` 追加 `ensureCards`、`listPredictions`、`answerPrediction` 等（两套同名）。
