# features/portfolio（持仓页，给 agent）

移植 legacy/game.js 3577-3766（updatePortfolio）与 3606-3633（行右键菜单）。挂载根：`#portfolio-page`。

## 边界
- 只写 `#portfolio-page` 内节点：`#total-assets` `#stock-value` `#available-fund` `#floating-pnl` `#total-return`、`#portfolio-holdings-tbody`、`#trade-records-tbody`；`.portfolio-records` 内自建 `.portfolio-records-footer`。
- 不做全局 contextmenu 禁用（legacy 6156 不移植），右键菜单只挂在 `tr[data-code]` 上。
- 导航用 `session.showTab`；选股意图派发到 `window` 的 `stocksim:select-stock`（detail `{code, target: 'trade'|'auto-trade'|'market'}`，事件名见 `state/events.js`），由 market / trade / auto-trade 监听。
- 监听 `window` 的 `stocksim:order`（trade 下单成功派发）后立即刷新持仓与成交。
- 不改 `state/session.js`、`api/endpoints.js`，只读 `session.get()`。

## 不变量
- 金额为整数分；展示走 `ui/format.js`（formatMoney / formatPercent），单价固定两位小数（同 legacy toFixed(2)）。
- 成交按 seq 降序 `mergeTrades` 合并；无 100 条上限，“加载更多”用 `next_cursor` 直到 null。
- 轮询 3s，且仅持仓页可见、文档可见时请求；存档切换靠 `generation` 丢弃旧响应。
- 所有写入经 `setHtml(html``)`，用户数据（股票名/代码）默认转义。

## 依赖的响应形状（已与后端 schemas 核对）
- `GET /saves/{id}/portfolio` → PortfolioOut `{ tick, trading_day, cash_cents, initial_fund_cents, market_value_cents, equity_cents, net_pnl_cents, holdings: [{ code, name, quantity, sellable_quantity, avg_price_cents, total_cost_cents, market_price_cents, market_value_cents, pnl_cents, pnl_bp }] }`。估值用 `market_price_cents`（后端在行情缺失时回落到成本价）。
- `GET /saves/{id}/trades[?cursor=]` → `{ items: [TradeOut], next_cursor }`；TradeOut 股票代码字段为 `code`（不是 stock_code）。
- `GET /stocks` → `[{ code, name, industry }]`（仅用于名称映射）

## 文件地图
- `index.js` mount（找不到 #portfolio-page 则不挂载）
- `controller.js` 拉取、轮询、游标分页、右键菜单
- `view.js` html`` 渲染（返回 SafeHtml，供 setHtml）
- `model.js` 纯逻辑：摘要、行模型、合并、分页解析（无 DOM）
- `model.test.js` `view.test.js`

## 常见任务
- 改盈亏口径：`model.js` 的 `portfolioSummary` / `holdingRow`，同步 `model.test.js`。
- 改成交字段：`model.js` 的 `tradeRow` / `parseTradePage`。
- 新增右键菜单项：`view.js` 的 `renderContextMenu` + `controller.js` 的 `runMenuAction`。

## 验证
`cd frontend && npm run build && npx vitest run src/features/portfolio`
