# tests/ — 测试（给 agent）

## 边界
- `conftest.py` 与 `integration/` 归 backend 接口线。`tests/unit/`（领域纯函数）归 domain agent，不要改。

## 不变量
- 每个用例使用独立临时 sqlite 库（`tmp_path`），并用 Alembic `upgrade head` 建表，测试与线上 schema 一致。
- `Settings(_env_file=None, ...)` 不读取开发者本地 `.env`。
- `client` 为 TestClient（进入上下文即运行 lifespan）；`registered_client` 已登录 alice。
- 测试模块不要互相 import；共享常量直接写在模块内或用夹具。

## 文件地图
- `conftest.py` settings / migrated / app / client / registered_client 夹具。
- `integration/` 健康、错误契约、认证、当前用户接口测试。

## 验证
`cd backend && uv run pytest tests/integration -q`
