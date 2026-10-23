# js/ — 原生脚本（经典脚本，全局 window.SS）

加载顺序（见 index.html）：`lib/html.js` → `lib/format.js` → `mock/data.js` → `lib/store.js`（假数据）→ `lib/api.js` → `lib/store.real.js`（真实模式下覆盖 `SS.store`）→ `lib/chart.js` → `lib/router.js` → `components/*` → `pages/*`（含 `login.js`）→ `app.js`。

- 每个文件是一个 IIFE，往 `SS` 上挂一个命名空间（`SS.fmt` `SS.store` `SS.chart` `SS.router` `SS.sheet` `SS.orderSheet` `SS.pages.*`…）。
- 不用 ES module：file:// 下 module 会被 CORS 拦截。
- 页面 render 返回 cleanup，用于取消 `store.on(...)` 订阅。

| 子目录 | 职责 |
| --- | --- |
| `lib/` | 无 UI 的基础设施 |
| `mock/` | 假数据 |
| `components/` | 可复用 UI |
| `pages/` | 路由页面 |
