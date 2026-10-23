# 架构说明

本文描述重构版（v2）的分层与数据流。契约（API、错误码、领域规则）见 [CONTRACT.md](CONTRACT.md)，关键取舍见 [adr/](adr/README.md)。

## 1. 总览

```
浏览器 ──HTTP/WS──► frontend (nginx 或 vite dev)
                       │  /api/*  /api/v1/ws/*
                       ▼
                    backend (FastAPI, 单 worker)
                       │  SQLAlchemy 2 (同步)
                       ▼
          sqlite | postgres | mysql
```

- `backend/`：FastAPI + SQLAlchemy 2 + Alembic，使用 uv 管理依赖，包名 `stocksim`，源码在 `backend/src/stocksim/`。
- `frontend/`：Vite + 原生 ES 模块，无框架。源码在 `frontend/src/`。
- 部署：`docker-compose.yml` 编排 `migrate -> backend -> frontend`，数据库通过 profile 可选 postgres / mysql。

## 2. 后端分层

依赖方向只能从上往下：

```
api/routers   HTTP/WS 入口：参数校验（schemas）、鉴权、调用 services、映射错误码
   │
services      用例编排：开事务、读写 models、调用 domain 纯函数、产生副作用（DB、WS 推送）
   │
domain        纯函数领域逻辑：撮合、涨跌停、费用、T+1、确定性行情引擎。零 I/O
```

辅助包：

| 包 | 职责 |
| --- | --- |
| `core/` | 配置（`config.py`）、错误码（`errors.py`）、密码与会话（`security.py`） |
| `db/` | `Base`、会话工厂、自定义列类型（`types.py`，如 JSON 的方言变体） |
| `models/` | SQLAlchemy 表定义，任何改动必须配 Alembic 迁移 |
| `schemas/` | Pydantic 请求/响应模型，金额字段统一为整数分，名称以 `_cents` 结尾 |
| `data/` | 股票池等静态数据（`stock_pool.json`） |

约束：

- `domain/` 禁止 import `sqlalchemy`、`fastapi`，禁止调用 `datetime.now()`、全局 `random`。时间与随机数由调用方注入，因此可以用固定输入做单元测试。
- 金额一律整数分；费率使用 `Decimal` 或字符串，避免浮点误差。
- 错误以 `ErrorCode` 返回，HTTP 体为 `{"code": "...", "params": {...}}`，前端据此本地化。

## 3. 确定性行情引擎

行情不依赖真实行情接口，也不依赖进程内的随机状态，而是由 `(seed, tick, stock_idx, k)` 唯一决定：

- `domain/rng.py` 实现计数器式 splitmix64：`rand01(seed, tick, stock_idx, k) -> float[0,1)`。同样的输入永远得到同样的输出。
- 每个交易日包含 `TICKS_PER_TRADING_DAY`（默认 20）个 tick，单 tick 波动 ±2%，涨跌停 ±10%，价格四舍五入到分。
- 存档记录当前 tick 与种子；行情状态可以从任意 tick 重放，结果与是否实时观察无关。

### 补帧（catch-up ticks）

用户关闭页面、服务重启或暂停时间后，服务端根据存档记录的最后 tick 与当前时间计算应当推进的 tick 数，并按确定性规则逐个补算：

1. 读取 `market_states` 中的最后 tick；
2. 依据时钟（运行中的时间 / 暂停 / 跳过）算出目标 tick；
3. 对区间内每个 tick 调用 domain 引擎，结果写入 `candles` 并更新五档与涨跌停价；
4. 补算过程中触发的自动交易规则按 tick 顺序执行，保证结果可复现。

因为补帧是纯函数推导，同一存档在任何设备、任何时刻重放得到的 K 线都一致，这也是自动化测试与"对拍 legacy"的基础。

## 4. 数据流

### 4.1 下单

```
POST /saves/{id}/orders
  -> api/routers/orders.py     校验 schema、取当前用户
  -> services/trading.py       加载存档 + 持仓 + 当日 trades（推导 T+1）
  -> domain/trading.py         纯函数：校验数量、涨跌停、限价、资金、费用
  -> services（写库）          trades / holdings / save_stats 同一事务提交
  -> ws 推送 {"t":"trade",...}
```

限价单规则（契约）：买单限价 ≥ 市价则按市价成交，否则拒绝 `ORDER_LIMIT_NOT_REACHED`；卖单反之。

### 4.2 行情与实时推送

```
浏览器 WS /api/v1/ws/saves/{id}
  <- {"t":"tick", ...}     服务端在 tick 产生后推送（进程内广播）
浏览器 GET /saves/{id}/market/{code}   日 K + 五档 + 涨跌停价（按需拉取）
```

WebSocket 连接由 nginx 长期保持（读超时 1 小时），应用层不做心跳以外的会话状态。

### 4.3 自动交易

`auto_trade_configs` 保存规则，`auto_trade_events` 记录触发历史。规则在补帧与实时 tick 中以同一套 domain 函数求值，保证"离线期间触发的规则"与"在线期间触发的规则"结果一致。

## 5. 前端结构

```
frontend/src/
  api/        fetch 封装与 REST/WS 客户端
  state/      单一状态仓库，订阅式更新
  i18n/       双语文案；错误码文案在 i18n/errors.js
  ui/         基础组件与 ui/html.js（默认转义的 tagged template）
  features/   按功能切分：trading、market、saves、achievements、auto-trade ...
  styles/     样式（沿用 legacy/styles.css 的结构）
  main.js     入口
```

约束：禁止直接 `innerHTML` 拼接用户数据，一律通过 `ui/html.js` 渲染，默认转义。

## 6. 部署拓扑

| 容器 | 镜像 | 说明 |
| --- | --- | --- |
| `migrate` | `stocksim-backend` | 运行 `alembic upgrade head` 后退出 |
| `backend` | `stocksim-backend` | `uvicorn --workers 1`，healthcheck `/api/v1/healthz` |
| `frontend` | `stocksim-frontend` | nginx-unprivileged，监听 8080，反代 `/api/` 与 WS |
| `postgres` / `mysql` | 官方镜像 | 仅在对应 profile 下启动 |

详见 [deployment.md](deployment.md)。

## 7. 为什么是单 worker

行情引擎的时钟推进、WebSocket 的订阅表都在进程内。多 worker 会导致同一存档在不同进程中被重复推进、推送不到订阅者。在引入外部消息总线之前，只能水平扩展为"多实例 + 按存档粘性路由"，目前不做。
