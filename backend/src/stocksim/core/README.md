# core

应用的基础设施，不含业务规则。

| 文件 | 内容 |
| --- | --- |
| `config.py` | `Settings`（读取环境变量与 `backend/.env`）、`get_settings()` |
| `errors.py` | `ErrorCode` 枚举、HTTP 状态映射、`AppError`、统一错误响应 |
| `security.py` | argon2id 密码哈希、会话 token 生成与 HMAC |

配置项说明见 `backend/.env.example`。
