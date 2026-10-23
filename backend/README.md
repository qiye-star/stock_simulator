# 股市模拟器后端

FastAPI 应用，提供账号、存档、行情、交易与自动交易的 REST 接口（前缀 `/api/v1`）。使用 SQLAlchemy 2 同步 ORM，数据库可在 SQLite、PostgreSQL、MySQL 间切换，表结构由 Alembic 管理。

## 技术栈
- Python 3.12，依赖与虚拟环境由 uv 管理
- FastAPI + uvicorn，pydantic-settings 读取配置
- SQLAlchemy 2.x + Alembic（`render_as_batch` 适配 sqlite）
- 密码：argon2id（pwdlib）；会话：httpOnly Cookie `session`，库内只存 HMAC

## 快速开始
```bash
cd backend
uv sync                       # 安装依赖（含 dev 组：pytest、ruff）
cp .env.example .env          # 按需修改 SECRET_KEY 等
uv run alembic upgrade head   # 建表（默认 ./data/stocksim.db）
uv run stocksim               # 开发模式启动 http://127.0.0.1:8000
```
生产启动：`uv run uvicorn stocksim.main:create_app --factory --host 0.0.0.0 --port 8000`。

## 测试与检查
```bash
uv run pytest tests/integration -q
uv run ruff check .
```

## 目录
| 路径 | 说明 |
| --- | --- |
| `src/stocksim/main.py` | 应用工厂 `create_app`、生命周期、路由挂载 |
| `src/stocksim/core/` | 配置、错误码与错误处理器、密码与会话工具 |
| `src/stocksim/db/` | 声明式基类、自定义列类型、引擎与 `get_db` |
| `src/stocksim/models/` | 16 张表的 ORM 模型 |
| `src/stocksim/schemas/` | 请求/响应的 Pydantic 模型 |
| `src/stocksim/services/` | 业务服务（当前：账号与会话） |
| `src/stocksim/api/` | 依赖注入与路由 |
| `alembic/` | 数据库迁移 |
| `tests/` | 测试夹具与集成测试 |

## 已实现接口
- `GET /api/v1/healthz`、`GET /api/v1/readyz`（检查数据库）
- `POST /api/v1/auth/register` · `POST /api/v1/auth/login` · `POST /api/v1/auth/logout` · `PUT /api/v1/auth/password`
- `GET /api/v1/me` · `PATCH /api/v1/me` · `DELETE /api/v1/me`

错误响应统一为 `{"code": "...", "params": {...}}`，错误码见 `src/stocksim/core/errors.py`。
