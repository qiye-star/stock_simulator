# js/lib/ — 基础设施

| 文件 | 导出 | 说明 |
| --- | --- | --- |
| `html.js` | `SS.html` `SS.raw` `SS.mount` `SS.el` `SS.$/$$` `SS.icon` `SS.haptic` `SS.reducedMotion` | 转义模板与 DOM 小工具、线性图标 |
| `format.js` | `SS.fmt` | 金额（分）/基点/股数/成交量/时钟/时段文案；`parseYuan` 输入转分 |
| `api.js` | `SS.api` `SS.ApiError` `SS.isMock` | 同源 `/api/v1` fetch 客户端（Cookie 会话、错误体 `{code,params}`、401 回调）；`?mock=1`/file:// 模式开关 |
| `store.real.js` | `SS.store`（真实模式） | 内存缓存 + REST + WebSocket 推送（断线轮询）；方法/事件与 `store.js` 一致，写操作返回 Promise；另有 init/login/logout/存档管理/loadDetail；行情分页 `listQuotes({q,sort,order,cursor,limit,watchlisted})→{items,next_cursor,total}`、`loadQuote(code)`、`loadAllQuotes()`、分时 `loadSeries(codes)`（完成后 emit `series`） |
| `store.js` | `SS.store`（假数据模式） | 内存状态 + 假 API：行情 tick、下单（费用/T+1/限价/涨跌停校验，抛 `ApiError{code}`）、持仓计算、自选、自动交易 CRUD；事件 `tick` `order` `auto` `watchlist` |
| `chart.js` | `SS.chart` | sparkline / intraday / kline / area 生成 SVG 字符串；`crosshair` 拖动读数 |
| `router.js` | `SS.router` | hash 路由（`add/navigate/back/start`），一级页记忆滚动位置 |

## 不变量
- 行情缓存只含已加载的股票：持仓/自动规则涉及的代码由 `ensureAccountQuotes` 保证在缓存内，其余页面用 `quote(code)` 前须经 `listQuotes/loadQuote/loadAllQuotes`。分时 `_series`（按分钟下标，供分时图）与 `_spark`（当日逐 tick，供迷你图）都由后端分时点重建；WS tick 只在已加载历史的股票上追加，漏 tick/跨日重新拉取，禁止插值。
- `store.js` 与 `store.real.js` 的对外方法必须同名同义；改一个要改另一个。真实版里 `toggleWatch`/`autoToggle` 是乐观更新（同步返回），其余写操作 `await`。
- 真实模式不得往后端发 schema 之外的字段（`AutoConfigIn` 是 `extra=forbid`，store 里已按白名单过滤）。
- store 的方法名与 REST 端点对应（文件头有映射），错误码取自 `docs/CONTRACT.md`。
- 下单规则与契约一致：限价买 ≥ 市价按市价成交，否则 `ORDER_LIMIT_NOT_REACHED`；手续费单独四舍五入到分。
- chart 只输出 class（up/down/accent），颜色由 CSS 决定。
