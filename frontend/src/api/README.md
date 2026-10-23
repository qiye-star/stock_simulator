# src/api

与后端 FastAPI 通信的模块。

- `http.js`：fetch 封装，统一基址 `/api/v1`、Cookie 会话，错误转为 `ApiError`（含 `code`、`status`、`params`）。
- `ws.js`：WebSocket 客户端，断线指数退避重连，消息自动 JSON 解析。
- `endpoints.js`：REST 端点的类型化函数，一个端点一个函数。含行情分页查询（`getMarket(saveId, query?)`）、分时（`getIntraday`）、资产曲线（`getEquityCurve`）。

调用示例：

```js
import { login } from './endpoints.js';
const user = await login({ username, password }); // 失败时抛出 ApiError
```

接口契约见 `../../../docs/CONTRACT.md`。
