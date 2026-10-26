# js/lib

无界面的工具层：转义模板、格式化、时钟模型（`clock-model.js`，纯函数）、假数据 API（store）、SVG 图表、路由（含 query）、玩法挂载点（`slots.js`）。

`store.js` 是假数据实现，`store.real.js` 是对接真实后端的实现（经 `api.js` 请求同源 `/api/v1`，行情走 WebSocket），两者方法签名一致，页面不区分。真实版的行情缓存是按需的（自选 + 已翻过的页 + 看过的详情），「全部」列表经 `listQuotes` 服务端分页/搜索/排序，分时经 `loadSeries`/`loadDetail` 拉后端历史后再接 WS 增量；假数据版给出同形的本地实现。返回结构与后端 schemas 对齐。
