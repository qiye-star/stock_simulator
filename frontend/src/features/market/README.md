# 行情模块（market）

游戏内的行情面板左侧：股票列表（搜索、按名称/最新价/涨跌幅排序、仅看自选），以及游戏时钟、暂停/继续与跳过时间。
本模块同时负责与服务端的实时连接：存档切换时拉取快照并订阅 `/api/v1/ws/saves/{id}`，每个 tick 更新共享状态，
其它行情相关模块（详情报价、K 线、交易表单、自选）都从这里读取数据。

## 快速开始
无需单独启动，功能随前端加载。开发时执行 `cd frontend && npm run dev`，并确保后端运行在 `localhost:8000`。

## 目录
| 文件 | 说明 |
|---|---|
| `index.js` | 功能入口（mount） |
| `controller.js` | 会话绑定、快照、WebSocket、详情刷新、暂停/跳过 |
| `view.js` | 股票列表视图（行级更新） |
| `clock.js` | 时钟显示与暂停/跳过按钮 |
| `model.js` | 纯函数：数据归一化、排序过滤、时钟状态 |
| `store.js` | 共享状态 `marketStore` |

## 接口依赖
- `GET /stocks`、`GET /saves/{id}`、`GET /saves/{id}/market`、`GET /saves/{id}/market/{code}`、`GET /saves/{id}/portfolio`
- `POST /saves/{id}/clock/pause|resume|skip`
- WebSocket `/api/v1/ws/saves/{id}`：`{"t":"tick","tick","clock","q":[[code,price_cents,change_bp,volume],...]}`
