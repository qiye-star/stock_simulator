# src/stocksim/ — 后端包根（给 agent）

包名 `stocksim`，src 布局。入口：`main.py`（`create_app`、`run`）。

## 子包边界
- `core/` 配置、错误、安全工具。不得 import `db/`、`models/`、`api/`。
- `db/` 引擎、会话、列类型、基类。不得依赖业务层。
- `models/` ORM 表（权威列规格见 `models/CLAUDE.md`）。
- `schemas/` 请求响应模型，只做形状校验；业务校验放 `services/`。
- `services/` 业务编排，抛 `AppError`。
- `api/` 依赖与路由，只做 HTTP 适配。
- `domain/`、`data/`：纯函数、零 I/O，禁止 import sqlalchemy/fastapi；由实施对应玩法的 agent 修改，遵守其 CLAUDE.md。
- `replay_ingest/`：真实复盘离线数据管道，运行时代码不得 import 它；akshare 只在其 `client.py` 中导入。

## 不变量
- 金额整数分；时间 UTC；`/api/v1` 前缀；错误体 `{"code","params"}`。
- `main.py` 不做模块级副作用（引擎在 `create_app` 内创建，应用状态挂在 `app.state`）。

## 文件地图
- `__init__.py` 版本号 `__version__`。
- `main.py` 应用工厂与 `run()`。
- 子包各自的 `CLAUDE.md` 为准。

## 验证
```
cd backend && uv run pytest tests/integration -q
uv run ruff check src/stocksim/{core,db,models,schemas,services,api} src/stocksim/main.py
```
