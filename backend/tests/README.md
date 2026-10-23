# tests

| 路径 | 说明 |
| --- | --- |
| `conftest.py` | 临时数据库、迁移、应用与客户端夹具 |
| `integration/` | 接口级测试（健康检查、错误契约、认证、当前用户） |
| `unit/` | 领域纯函数测试（由 domain 线维护） |

运行：`cd backend && uv run pytest`（仅接口测试：`uv run pytest tests/integration`）。
