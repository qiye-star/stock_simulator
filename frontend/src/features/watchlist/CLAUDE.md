# features/watchlist（自选增删与星标，给 agent）

## 边界
- 拥有：`#add-watch-btn`（详情区 +自选 / -自选）与列表星标的点击处理（`[data-watch-toggle]`，由 market/view.js 渲染）。
- 只改 `../market/store.js` 的 `watchlist`（数组，整体替换）；列表显示由 market 负责。

## 不变量
- 乐观更新：先写 store，再 `PUT|DELETE /saves/{id}/watchlist/{code}`；失败时仅在列表仍为本次乐观版本时回滚。
- 同一代码请求在途时忽略重复点击（`pending` 集合）。
- 不调用成就检查（legacy checkAchievements 归 achievements 模块）。

## 文件地图
- `model.js` `toggleWatch` 纯函数（`model.test.js`）。
- `controller.js` `toggleWatchlist(code)`。
- `index.js` 按钮文案与可用状态、星标委托。

## 验证
- `cd frontend && npx vitest run src/features/watchlist`
- `cd frontend && npm run build`
