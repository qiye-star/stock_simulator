# core/ — 配置、错误、安全（给 agent）

## 边界
- 不依赖 `db/`、`models/`、`services/`、`api/`。可依赖 fastapi（仅用于错误处理器注册）。

## 不变量
- `ErrorCode` 枚举值与 `docs/CONTRACT.md` 的错误契约逐字一致；每个码必须在 `ERROR_STATUS` 有状态码。
- 业务失败只抛 `AppError(code, params)`；`error_body()` 生成 `{"code","params"}`。
- 非业务错误：`HTTP_<status>`（如未知路由）、`INTERNAL_ERROR`（500），不属于 ErrorCode。
- `Settings` 字段名即环境变量名；默认值与 `.env.example` 保持一致。
- 密码 argon2id（`PasswordHash.recommended()`）；会话 token 用 `hash_session_token` 做 HMAC 后入库。

## 文件地图
- `config.py` Settings、`get_settings()`（lru_cache）、`DEV_SECRET_KEY`。
  - `CHALLENGE_*`（03 §11.1）：每日挑战的开关、seed 密钥、调度（daily/compact）、时段、快放节奏、门槛与保留期。`main.create_app` 校验：compact 需 `ENABLE_DEBUG_API=true`，daily 的时段个数 = 回合数 + 1；挑战服务经 `services/challenges/config.current_settings()` 读取本应用的 Settings。
- `errors.py` ErrorCode、ERROR_STATUS、AppError、`register_error_handlers`。
- `security.py` 密码哈希/校验、dummy 哈希（防用户名枚举计时）、会话 token。

## 常见任务
- 新增配置项：`config.py` 加字段 → `.env.example` 加注释行 → 需要时更新 README。
- 新增错误码：`ErrorCode` + `ERROR_STATUS` + `docs/CONTRACT.md`。

## 验证
`uv run pytest tests/integration/test_errors.py -q`
