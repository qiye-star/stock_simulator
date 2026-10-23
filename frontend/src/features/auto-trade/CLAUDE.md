# features/auto-trade（自动交易页，给 agent）

移植 legacy/game.js 5021-5641（配置表单、启停）与 6041-6100（统计与事件）。挂载根：`#auto-trade-page`。

## 边界
- 只写 `#auto-trade-page` 内节点；`#profit-tip` 为本模块按需创建/删除。
- 事件失败文案在**渲染时**经 `i18n/errors.js`（`errorI18nKey`）翻译，不存译文。
- 监听 `window` 上的 `stocksim:select-stock`（target=auto-trade）填入股票代码（事件名定义在 `state/events.js`）。
- 运行状态与统计来自 `GET /saves/{id}/auto-trade/status`（AutoStatusOut：enabled/paused/max_total_trades/total_trades/success_trades/failed_trades/total_pnl_cents）；存档切换由 `session` 驱动。

## 请求体契约（model.js `buildConfigPayload`，改名只改这一处）
与后端 `schemas/auto_trade.py` AutoConfigIn 一致（`extra="forbid"`，多余字段 422）：
`code, direction, condition_type, condition_operator, condition_value_cents, condition_percent, quantity, price_type, limit_price_cents, stop_loss_percent, take_profit_percent, max_trades, max_amount_cents`
- price/profit：`condition_value_cents`（分，>0），`condition_operator` 必填；percentage：`condition_percent`（float，%，如 2.5），`condition_operator` 必填；time：`condition_operator` 与两个阈值都必须为 null。
- `stop_loss_percent` / `take_profit_percent` 是占持仓成本的百分比（float，0-100 / 0-1000），不是金额。止损取绝对值；0 或留空 = null。
- `max_trades` 0 = 不限。`max_amount_cents` 留空 = null。
- `condition_percent` 后端限 0-1000（负值被拒绝，前端同样拦截；后端 domain 支持有符号 bp，但 schema 不允许，属已知限制）。最多两位小数；元值最多两位小数，超出即拒绝。
- 买入禁用 profit（仅卖出可用）。
- 响应 AutoConfigOut 字段：同上 + `id, name`；列表为 `{items}`。

## 响应与统计（已与后端核对）
- 事件：`GET .../auto-trade/events?cursor=&limit=` -> `{items, next_cursor}`；元素 AutoEventOut：`id, config_id, stock_code, direction, condition_type, success, reason_code, amount_cents, pnl_cents, pnl_percent, buy_price_cents, sell_price_cents, tick, trading_day, created_at`。无 `params` 字段。
- `reason_code` 仅失败事件有值，取值为 `AUTO_LIMIT_REACHED`、`AUTO_MAX_AMOUNT_EXCEEDED` 或下单失败的交易错误码，统一经 `errorI18nKey` 渲染。
- 统计：只来自 `GET .../auto-trade/status`（AutoStatusOut）。全局上限只计成功成交，剩余 = max_total_trades - success_trades。
- 全局上限（max_total_trades）后端目前**没有设置接口**，前端只读展示（输入框 disabled）。待后端补接口后再开放。
- 按比例下单：读取 `GET /saves/{id}/portfolio`（holdings[].code/quantity）与 `GET .../market/{code}` 的 `price_cents`。

## 不变量
- 金额整数分；百分比为 float（2.5 = 2.5%），前端不做 bp 换算。
- 轮询 3s，仅页面可见且文档可见时请求；存档切换靠 `generation` 丢弃旧响应。
- 编辑态 `editingId` 仅在本模块内；重复检查排除自身。

## 文件地图
- `index.js` mount · `controller.js` 表单/启停/轮询 · `view.js` 列表与事件模板
- `model.js` 校验、映射、配置<->表单、视图模型（纯函数）· `model.test.js` `view.test.js`

## 常见任务
- 新增条件类型：`model.js` 的 `CONDITION_TYPES`、`buildConfigPayload`、`conditionText`，并补测试。
- 新增事件码文案：加到 `i18n/errors.js` + 两个 locale（本模块不再维护本地码表）。

## 验证
`cd frontend && npm run build && npx vitest run src/features/auto-trade`
