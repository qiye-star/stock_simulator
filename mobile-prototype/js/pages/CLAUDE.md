# js/pages/ — 路由页面

约定：`SS.pages.<name> = { tab, render(view, params) }`。
- `tab` 填 market、portfolio、auto 或 me，用来高亮 Dock；填 `null` 表示二级页，此时隐藏 Dock。
- `render` 返回 cleanup 函数（取消 store 订阅）。
- 行情 tick 到来时只就地更新数字或 SVG，不整页重绘，以免打断滑动、光晕和入场动画。

| 文件 | 路由 | 对应接口 |
| --- | --- | --- |
| `market.js` | `#/market` | GET /market?limit&cursor&q&sort&order（「全部」分页/搜索，滚动加载更多）、自选来自缓存、/portfolio（概览）、迷你图用 /market/{code}/intraday |
| `stock.js` | `#/stock/:code` | GET /market/{code}、GET /market/{code}/intraday（分时历史，WS 追加）、PUT/DELETE /watchlist/{code}；缓存里没有该代码时按需 `loadQuote` |
| `portfolio.js` | `#/portfolio` | GET /portfolio；曲线按住读数：`kind==='initial'` 显示「起点」，其余 `D<trading_day>` |
| `auto.js` | `#/auto` | /auto-trade/configs、status、events、start/pause/resume/stop；`auto` 事件同时重绘状态/规则/触发记录，触发记录按事件 id 增量入场（已渲染行不重播动画） |
| `me.js` | `#/me` | GET /me、/trades（游标分页）、PATCH /me、/clock/pause|resume、/saves、/saves/{id}/export、/auth/logout |
| `login.js` | `#/login` | POST /auth/login、/auth/register（无 Dock） |

新增页面时：在 `index.html` 引入，并在 `js/app.js` 中注册路由。
