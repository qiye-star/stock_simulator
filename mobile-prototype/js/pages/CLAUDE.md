# js/pages/ — 路由页面

约定：`SS.pages.<name> = { tab, render(view, params) }`。
- `tab` 填 market、news、portfolio、play 或 me，用来高亮 Dock；填 `null` 表示二级页，此时隐藏 Dock（`auto.js` 是 `null`，入口在“我的”）。
- 状态栏：行情页 full 变体，持仓/个股页 compact 变体，统一 `SS.tradeBar.mount(el, {variant})`，不要在页面里自己算时段或倒计时。
- `render` 返回 cleanup 函数（取消 store 订阅）。
- 行情 tick 到来时只就地更新数字或 SVG，不整页重绘，以免打断滑动、光晕和入场动画。

| 文件 | 路由 | 对应接口 |
| --- | --- | --- |
| `market.js` | `#/market` | GET /market?limit&cursor&q&sort&order（「全部」分页/搜索，滚动加载更多）、自选来自缓存、/portfolio（概览）、迷你图用 /market/{code}/intraday；顶部 `SS.tradeBar`（full），banner 挂载点 `market.banner`；首次进入触发 `SS.clockHelp.maybeAutoOpen()` |
| `stock.js` | `#/stock/:code` | GET /market/{code}、GET /market/{code}/intraday（分时历史，WS 追加）、PUT/DELETE /watchlist/{code}；缓存里没有该代码时按需 `loadQuote` |
| `portfolio.js` | `#/portfolio` | GET /portfolio；曲线按住读数：`kind==='initial'` 显示「起点」，其余 `D<dayNo>`；右上角紧凑状态栏 |
| `auto.js` | `#/auto` | /auto-trade/configs、status、events、start/pause/resume/stop；`auto` 事件同时重绘状态/规则/触发记录，触发记录按事件 id 增量入场（已渲染行不重播动画）；二级页，顶栏返回 |
| `me.js` | `#/me` | GET /me、/trades（游标分页）、PATCH /me、/clock/pause|resume、/saves、/saves/{id}/export、/auth/logout；行入口“自动交易”（→ `#/auto`）与“游戏速度与交易时间”（→ 说明弹层）；挂载点 `me.badges` `me.cards` `me.rows` |
| `play.js` | `#/play` | 玩法 hub：挂载点 `play`；未注册的分区（每日挑战、预测市场、真实复盘）显示“即将开放”占位 |
| `coming-soon.js` | 占位工厂 | `SS.pages.comingSoon({tab, title, desc})`，用于尚未上线的 Dock 入口（⑤ 起 `#/news` 由 features 提供，占位已被覆盖） |
| `login.js` | `#/login` | POST /auth/login、/auth/register（无 Dock） |

新增页面时：在 `index.html` 引入，并在 `js/app.js` 中注册路由。

## ⑤ 核心页面的改动（仅挂载点与分段，不含玩法逻辑）
- `market.js`：分段按钮追加 `SS.marketLists.list()`；选中玩法分段时由 `paintCustom` 按 `def.load()` 渲染（缓存 20 秒、按存档隔离）；行可带注记（`rowHtml(s, note)`，“事发”用强调色）。
- `me.js`：存档抽屉的“新建存档”展开表单（名称 + “事件模式”开关，默认开，创建后不可改）；存档行带“事件”标签；`SS.openSaves` 暴露给快讯页的“新建事件模式存档”。
- `stock.js`：底部 `[data-role="extra"]` 挂载 `stock.extra`（相关事件）；日 K 绘制后挂载 `stock.kline`（事件标记，⑤）。

## ⑦ 核心页面的改动（挑战存档，仅挂载点与显隐）
- `me.js`：挑战存档内隐藏“游戏速度与交易时间”行与“行情暂停”开关（`paintRows`，监听 `save`）。
- `components/clock-help.js`：挑战存档内不渲染速度选择器（说明弹层其余内容照常）。
- `components/trade-bar.js`：挑战存档时由 `challenge` 功能的 overlay 覆盖状态文案与动作（“继续 / 跳过”不出现）。
- `auto.js`：挑战存档内显示“挑战中不可用自动交易”（既有分支）。
