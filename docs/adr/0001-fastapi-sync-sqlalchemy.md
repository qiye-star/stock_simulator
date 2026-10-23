# ADR 0001：后端采用 FastAPI + 同步 SQLAlchemy 2

- 状态：已采纳
- 日期：2026-10

## 背景

原版（`legacy/`）完全运行在浏览器中，没有服务端。重构后需要账号、存档与 WebSocket 推送，后端成为必需。约束：

- 请求量小（单机模拟器，同时在线用户数有限），瓶颈不在数据库 I/O；
- 行情推进与补帧计算是 CPU 密集的纯函数，必须保证确定性；
- 需要同时支持 sqlite、postgres、mysql，并且迁移要可控（Alembic）。

## 决策

- Web 框架使用 FastAPI，同时提供 REST 与 WebSocket，并由 Pydantic 生成请求校验与 OpenAPI。
- ORM 使用 SQLAlchemy 2.x 的同步接口（`Session`），不使用 async 引擎。
- 迁移使用 Alembic，`render_as_batch=True` 以兼容 sqlite 的 ALTER 限制。
- 服务以单 worker 运行（见 [architecture.md](../architecture.md) 第 7 节）。

## 理由

- 同步代码更容易推理事务边界。每个请求一个 `Session`，`services/` 层显式 commit，不存在 async 下的隐式懒加载问题。
- 我们的热路径是纯函数（`domain/`），不需要协程。同步数据库驱动（psycopg、pymysql、sqlite3）成熟稳定。
- FastAPI 的同步路由由线程池执行，足以应对预期负载。
- 同步 + 单 worker 的组合让行情引擎的进程内状态不需要跨进程同步。

## 后果

- 正面：代码简单，测试可用同步 TestClient，调试直观。
- 负面：若将来需要大量并发长连接，线程池会成为瓶颈，届时需重新评估（可能迁移到 async 驱动，但 `domain/` 不受影响）。
- 负面：同步 Session 不能跨线程共享，依赖注入必须按请求创建。
