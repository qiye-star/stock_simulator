# js/ — 原生脚本（经典脚本，全局 window.SS）

加载顺序（见 index.html）：`lib/html.js` → `lib/format.js` → `lib/clock-model.js` → `mock/data.js` → `lib/store.js`（假数据）→ `lib/api.js` → `lib/store.real.js`（真实模式下覆盖 `SS.store`）→ `lib/chart.js` → `lib/router.js` → `lib/slots.js` → `components/*`（含 `trade-bar.js`、`clock-help.js`、`close-summary.js`、`soon-card.js`）→ `pages/*`（含 `login.js`、`coming-soon.js`、`play.js`）→ `features/news/`（⑤：`mock.js` → `model.js` → `store.js` → `news-page.js` → `event-page.js` → `chain-page.js` → `index.js`，用 `<!-- feature:news -->` 注释包住）→ `features/predict/`（⑥：`model.js` → `mock.js` → `titles.js` → `store.js` → 弹层与页面 → 挂件 → `index.js`，`<!-- feature:predict -->`）→ `features/challenge/`（⑦：`model.js` → `mock.js` → `store.js` → `verify.js` → `ui.js` → `flow.js` → 挂件与页面 → `index.js`，`<!-- feature:challenge -->`）→ `features/pm/`（⑧：`model.js` → `mock.js` → `store.js` → `ui.js` → `trade-panel.js` → 列表/记录/详情页 → `play-card.js` → `index.js`，`<!-- feature:pm -->`）→ `features/replay/`（⑨：`model.js` → `mock.js` → `store.js` → `ui.js` → `replay-order-sheet.js` → 选关/会话/揭示页 → `play-card.js` → `index.js`，`<!-- feature:replay -->`）→ `app.js`。

`lib/predict-math.js` 在 `lib/slots.js` 之后加载（预测卡共用纯函数）。

- 每个文件是一个 IIFE，往 `SS` 上挂一个命名空间（`SS.fmt` `SS.store` `SS.chart` `SS.router` `SS.sheet` `SS.orderSheet` `SS.clockModel` `SS.tradeBar` `SS.clockHelp` `SS.slots` `SS.guards` `SS.pages.*`…）。
- 不用 ES module：file:// 下 module 会被 CORS 拦截。
- 页面 render 返回 cleanup，用于取消 `store.on(...)` 订阅。

| 子目录 | 职责 |
| --- | --- |
| `lib/` | 无 UI 的基础设施 |
| `mock/` | 假数据 |
| `components/` | 可复用 UI |
| `pages/` | 路由页面 |
| `features/`（⑤ 起） | 各玩法功能，每个子目录自带 mock、store（两套同名）、页面与 `index.js` 注册 |
