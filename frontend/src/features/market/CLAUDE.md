# features/market（行情列表 / 时钟 / 行情连接，给 agent）

## 边界
- 唯一拥有行情 WebSocket 与存档快照的模块；其它功能只读 `store.js` 的 `marketStore`。
- 拥有 DOM：`#stock-list`、`#stock-search`、`#watchlist-toggle-btn`、`.stock-list-header .sortable`、
  `#market-time`、`#market-status`、`#portfolio-time`、`#portfolio-status`、`#time-pause-btn`、`#time-skip-btn`。
- 不写详情报价区（属 trade）、不画图（属 chart）、不改自选（属 watchlist）。

## 不变量
- 金额整数分；`change_bp` 为基点。展示用 `centsText` / `changeText`。
- 列表是行级 diff：tick 只改 `tickInfo.codes` 对应行的文本；仅排序/过滤/自选变化时重排（insertBefore），禁止 innerHTML 重建。
- 星标点击由 watchlist 处理（`[data-watch-toggle]`），列表行点击要跳过该元素。
- 切换存档：`generation` 自增，所有异步结果先比对 generation；详情请求同一时刻最多一个在途，tick 期间合并补拉。
- 时钟窗口与状态优先级同 legacy（`model.js#clockStatus`）。

## 文件地图
- `index.js` mount：列表 + 时钟 + `bindSession()`；卸载时 `teardown()`。
- `controller.js` 会话绑定、loadAll/refreshAccount、WS tick、refreshDetail、selectStock、togglePause、skipTime。
- `view.js` 股票列表（搜索、排序、自选过滤、行 diff）；`clock.js` 时钟与暂停/跳过按钮。
- `model.js` 纯函数：归一化（quote/tick/snapshot/detail/save 相关）、排序过滤、时钟文案、涨跌停；`model.test.js`。
- `store.js` 共享 store；`dom.js` 仅变化时写 DOM；`notify.js` 错误码 -> 提示。

## 常见任务
- 后端字段变化：改 `model.js` 的 normalize*（字段名以 backend schemas 为准，`*_cents`）。

## 已核对的后端事实
- 快照 `GET /saves/{id}/market`：MarketOut = `{paused, tick, trading_day, clock_minute, session, skipped_ticks, stocks: QuoteOut[]}`。自选列表没有接口，由 `QuoteOut.watchlisted` 得出。
- 详情 `GET /saves/{id}/market/{code}`：QuoteOut + `candles`（CandleOut：`open_cents/high_cents/low_cents/close_cents`，映射为 Detail.history）+ `order_book{bids,asks}`。
- WS tick：`{t:'tick', tick, advanced, clock:{minute, trading_day, paused, trading}, full, q:[[code, price_cents, change_bp, volume], ...]}`。时钟是对象，不是字符串。
- 时钟接口 ClockOut：暂停/继续读 `clock_minute`；跳过读 `skipped_ticks`（0 = 无需跳过）。
- 持仓（用于 `Account.holdings`）：`code`、`sellable_quantity`、成本取 `avg_price_cents`。
- 监听 `window` 的 `stocksim:select-stock`（target=market）调用 `selectStock`。事件名见 `state/events.js`。
- 新增列表列：`view.js#patchRow`，并保证 tick 路径只改文本。

## 验证
- `cd frontend && npx vitest run src/features/market`
- `cd frontend && npm run build`
