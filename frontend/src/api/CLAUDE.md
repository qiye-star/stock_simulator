# src/api（后端通信，给 agent）

## 边界与不变量
- `http.js`：唯一的 fetch 出口。`credentials: 'same-origin'`，基址 `/api/v1`。非 2xx 解析 `{code, params}` 抛 `ApiError`；网络失败 code=`NETWORK`；错误体不合规 code=`UNKNOWN`。
- `endpoints.js`：每个 REST 端点一个函数，与 `docs/CONTRACT.md` 一一对应；参数/返回以后端 schemas 为准。
- `ws.js`：`createSaveSocket(saveId, opts)` 带指数退避重连；`close()` 后不再重连。
- 字段名保持 snake_case（与服务端一致），金额为整数分。

## 文件地图
- `http.js` request/get/post/put/patch/del、ApiError、buildUrl
- `endpoints.js` 每个端点一个函数，JSDoc 的响应 typedef 与 backend/src/stocksim/schemas 一一对应；列表接口返回 `{items, next_cursor}` 的需调用方取 `items`。错误文案统一用 `errorMessage(err, t)`（i18n/errors.js），不要在功能模块自建码表。
- `endpoints.js` 的 `getMarket(saveId, query?)` query 全可选（limit/cursor/q/sort/order/watchlisted），不传即旧行为；`getEquityCurve`、`getIntraday` 为资产曲线与分时接口。
- `ws.js` createReconnectingSocket、createSaveSocket、buildWsUrl
- `endpoints.js` 全部端点

## 常见任务
- 新增端点：在 endpoints.js 增加函数并写 JSDoc；如需新错误码，同步 `src/i18n/errors.js`。
- 调试代理：开发时由 vite.config.js 转发到后端。
