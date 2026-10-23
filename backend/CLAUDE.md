# backend/ — 股市模拟器后端（给 agent）

FastAPI + SQLAlchemy 2（同步）+ Alembic，uv 管理，Python 3.12。契约见 `../docs/CONTRACT.md`。

## 边界
- 只改 `backend/` 下 agent 被分配的路径。`src/stocksim/domain/`、`src/stocksim/data/`、`tests/unit/` 归 domain agent，不要动。`frontend/` 不碰。
- 依赖只用 `uv add` / `uv sync`，不用 pip。

## 不变量
- 金额一律整数分，字段名以 `_cents` 结尾；费率用 `Decimal`（`Numeric(8,6)`）。Money 类型拒绝 float。
- 时间存 UTC 且带时区（`UTCDateTime`）。
- 错误体固定 `{"code","params"}`，只能抛 `core.errors.AppError(ErrorCode.X)`；新码先加 `ErrorCode` 与 `ERROR_STATUS`。
- 会话 token 明文只给客户端，库内存 `HMAC-SHA256(SECRET_KEY, token)`。
- 改 `models/` 必须同时生成 Alembic 迁移（`alembic/versions/` 提交进库）。
- 所有路由挂在 `/api/v1`（见 `stocksim/main.py` 的 `API_PREFIX`）。
- 测试用 `alembic upgrade head` 建临时库，与线上 schema 一致。

## 文件地图
- `src/stocksim/main.py` — `create_app(settings, engine=)` 应用工厂；`run()` 为 `stocksim` 命令。
- `src/stocksim/core/` — 配置、错误码、密码/会话 token。
- `src/stocksim/db/` — Base 与命名约定、Money/UTCDateTime/JSON 类型、引擎与 `get_db`。
- `src/stocksim/models/` — 16 张表（字段权威表见 `models/CLAUDE.md`）。
- `src/stocksim/schemas/` · `services/` · `api/`（deps、routers）。
- `alembic/` 迁移；`tests/conftest.py` 夹具；`tests/integration/` 接口测试。

## 常见任务
- 新增/修改表：改 `models/*.py` → `uv run alembic revision --autogenerate -m "msg"` → 检查生成文件 → `uv run alembic upgrade head`。
- 新增接口：`schemas/` 请求响应模型 → `services/` 业务逻辑 → `api/routers/` 路由并在 `routers/__init__.py` 注册 → `tests/integration/` 用例。
- 新增错误码：`core/errors.py` 的 `ErrorCode` + `ERROR_STATUS`，并同步 `docs/CONTRACT.md`。

## 验证命令
```
cd backend
uv run pytest tests/integration -q        # 本目录负责的集成测试
uv run ruff check src/stocksim/{core,db,models,schemas,services,api} src/stocksim/main.py alembic tests/integration tests/conftest.py
DATABASE_URL=sqlite:////tmp/x.db uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
```
