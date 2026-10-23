# api/routers

| 文件 | 路径（前缀 `/api/v1`） | 说明 |
| --- | --- | --- |
| `health.py` | `GET /healthz`、`GET /readyz` | 存活与就绪探针 |
| `auth.py` | `POST /auth/register`、`POST /auth/login`、`POST /auth/logout`、`PUT /auth/password` | 账号与会话 |
| `me.py` | `GET /me`、`PATCH /me`、`DELETE /me` | 当前用户 |
| `stocks.py` | `GET /stocks` | 股票池目录 |
| `achievements.py` | `GET /achievements/catalog`、`GET /saves/{id}/achievements` | 成就目录与已解锁列表 |
| `saves.py` | `GET/POST /saves`、`GET/PATCH/DELETE /saves/{id}`、`GET /saves/{id}/export` | 存档 |
| `market.py` | `GET /saves/{id}/market`、`GET /saves/{id}/market/{code}` | 行情快照、个股日 K 与五档 |
| `clock.py` | `POST /saves/{id}/clock/pause｜resume｜skip` | 游戏时钟 |
| `orders.py` | `POST /saves/{id}/orders`、`GET /saves/{id}/trades?cursor=` | 下单（可选 `Idempotency-Key`）与成交流水 |
| `portfolio.py` | `GET /saves/{id}/portfolio` | 资产与持仓 |
| `watchlist.py` | `PUT/DELETE /saves/{id}/watchlist/{code}` | 自选股（幂等） |
| `__init__.py` | — | 自动发现并汇总为 `api_router` |
| `auto_trade.py` | `/saves/{id}/auto-trade/configs`（CRUD）、`…/start｜pause｜resume｜stop｜reset`、`…/status`、`…/events?cursor=` | 自动交易 |
| `legacy.py` | `POST /import/legacy` | 旧版存档导入 |
| `debug.py` | `POST /saves/{id}/debug/fund｜time｜achievements｜reset-market｜clear` | 调试（需 `ENABLE_DEBUG_API=true`） |
| `ws.py` | `WS /api/v1/ws/saves/{id}` | 行情与事件推送（cookie 鉴权） |
