# features/trade（详情报价、买卖表单、下单，给 agent）

## 边界
- 拥有：详情报价文字区（`#detail-*`、`#limit-*-price`、`#ask/bid{1..5}-*`）、`#buy-*` / `#sell-*` 表单、
  `#confirm-buy-btn` / `#confirm-sell-btn`、`.trade-tab`、`#quick-buy-btn` / `#quick-sell-btn`。
- 不拥有：持仓列表（`#trade-holdings-list`，属 portfolio）、图表（chart）、自选按钮（watchlist）。
- 行情数据只读 `../market/store.js`；下单后调用 `../market/controller.js#refreshAccount`，并派发 `window` 上的 `stocksim:order` 事件（常量 `ORDER_EVENT`，见 `state/events.js`；持仓页监听后刷新）。
- 监听 `window` 的 `stocksim:select-stock`（target=trade），把代码填入买卖表单。

## 不变量
- 金额整数分：`parseYuanToCents` 严格解析（≤2 位小数），手续费用 BigInt 半数向上取整到分。
- 价格框只在用户未编辑时跟随市价；`input` 事件（含步进按钮）即标记为已编辑，直到更换代码。
- 价格未编辑 -> 市价单；已编辑 -> 限价单（`limit_price_cents`）。
- 价格偏离：后端返回 `TRADE_PRICE_DEVIATION_CONFIRM`（不在 ErrorCode 枚举中，前端在 `controller.js` 单独识别）-> 确认弹窗 -> 带 `confirm_deviation:true` 重发一次。
- 错误码统一用 `market/notify.js#notifyError`（经 `i18n/errors.js` 映射）。
- 同一时刻只允许一笔下单在途（`inFlight`）。

## 文件地图
- `model.js` 纯逻辑（解析、费用、可买/可卖、校验、请求体）；`model.test.js`。
- `detailView.js` 报价区渲染；`form.js` 买卖表单；`controller.js` 下单流程；`confirm.js` 偏离确认弹窗。
- `index.js` mount：表单 + 报价 + 快捷买卖。

## 常见任务
- 新增下单参数：改 `model.js#buildOrderBody`，并同步 `api/endpoints.js` 的 `OrderIn`。
- 新增 T+1 等错误文案：`i18n/errors.js` + 两个 locale 同时加 `error.<CODE>`。

## 验证
- `cd frontend && npx vitest run src/features/trade`
- `cd frontend && npm run build`
