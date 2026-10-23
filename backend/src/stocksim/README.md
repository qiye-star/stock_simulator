# stocksim 包

后端 Python 包。应用由 `stocksim.main:create_app` 构建。

| 子包 / 文件 | 说明 |
| --- | --- |
| `main.py` | 应用工厂 `create_app(settings, engine=)` 与命令行入口 `run()` |
| `core/` | 配置 `Settings`、错误码 `ErrorCode` 与处理器、密码与会话工具 |
| `db/` | `Base`、列类型 `Money` / `UTCDateTime` / `json_column_type`、引擎与 `get_db` |
| `models/` | 15 张表的 ORM 模型 |
| `schemas/` | 接口的 Pydantic 请求响应模型 |
| `services/` | 业务服务 |
| `api/` | 依赖注入与路由 |
| `domain/`、`data/` | 纯领域规则与静态数据，由另一条线维护 |

更多见 [backend/README.md](../../README.md)。
