# backend/ — 股市模拟器后端（给 agent）

FastAPI + SQLAlchemy 2（同步）+ Alembic，uv 管理，Python 3.12。契约见 `../docs/CONTRACT.md`。

## 边界
- 只改 `backend/` 下 agent 被分配的路径。`src/stocksim/domain/`、`src/stocksim/data/`、`tests/unit/` 由实施对应玩法/模式的 agent 修改，须遵守各自 CLAUDE.md 的约束（domain 纯函数与 `test_purity.py`、data 只放脚本生成的静态 JSON、单测模块名全局唯一、RNG 与引擎金值不得为过测试而修改），并同步更新相关 CLAUDE.md。`frontend/` 不碰。
- 依赖只用 `uv add` / `uv sync`，不用 pip。离线抓取依赖（akshare）放 `ingest` 依赖组（`uv add --group ingest`），运行时代码不得依赖它。

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
- `src/stocksim/models/` — 33 张表（字段权威表见 `models/CLAUDE.md`；预测卡/积分/情报/称号 8 张，每日挑战 4 张，预测市场 5 张）。
- `src/stocksim/schemas/` · `services/` · `api/`（deps、routers）。
- `src/stocksim/domain/challenge/` — 每日挑战纯函数（时间线、剧本、承诺、计分；C0）；`src/stocksim/services/challenges/` — 挑战服务层（生成、推进镜像、报名、回合、结算、runner），见其 CLAUDE.md。
- `src/stocksim/domain/prediction_market/` — 预测市场纯函数（LMSR、合约生成、限额；04 §4）；`services/pm_lifecycle.py`（生命周期、sweeper）、`services/prediction_markets.py`（报价、下单、视图）、`api/pm_ws.py`（全服 Hub 与 WS 循环）。见各目录 CLAUDE.md。
- `src/stocksim/cli_challenge.py` — 挑战维护 CLI `stocksim-challenge`（`run-due` / `loop --interval 15` / `show [--date]` / `void --date --reason`，`pyproject.toml` 的 `[project.scripts]`）。
- `src/stocksim/replay_ingest/` — 真实复盘离线数据管道（抓取/构建/校验），运行时不得导入；只有其中 `client.py` 导入 akshare。见其 CLAUDE.md。
- `src/stocksim/services/replay/` — 真实复盘服务（关卡包导入、会话、防剧透视图、预测计分；模式 E）。见其 CLAUDE.md。
- `alembic/` 迁移；`tests/conftest.py` 夹具；`tests/integration/` 接口测试。

## 常见任务
- 新增/修改表：改 `models/*.py` → `uv run alembic revision --autogenerate -m "msg"` → 检查生成文件 → `uv run alembic upgrade head`。
- 新增接口：`schemas/` 请求响应模型 → `services/` 业务逻辑 → `api/routers/` 路由并在 `routers/__init__.py` 注册 → `tests/integration/` 用例。
- 新增错误码：`core/errors.py` 的 `ErrorCode` + `ERROR_STATUS`，并同步 `docs/CONTRACT.md`。

## 验证命令
```
cd backend
uv run pytest tests/integration -q        # 本目录负责的集成测试
uv run pytest tests/ingest -q             # 复盘离线管道（不联网）
uv run ruff check src/stocksim/{core,db,models,schemas,services,api} src/stocksim/main.py alembic tests/integration tests/conftest.py
uv run ruff check src/stocksim/replay_ingest tests/ingest
DATABASE_URL=sqlite:////tmp/x.db uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
uv run pytest tests/unit/domain/test_challenge_*.py -q   # 挑战纯函数（domain/challenge）
uv run pytest tests/integration/test_challenge_*.py -q   # 挑战服务与 HTTP（每用例迁移，数分钟）
uv run stocksim-challenge run-due                        # CLI：单次 run_due（读 backend/.env）
```
端到端挑战段（`scripts/e2e_smoke.py::s_challenge`，默认跳过）：后端以 `CHALLENGE_SCHEDULE=compact CHALLENGE_MIN_ACCOUNT_AGE_HOURS=0 ENABLE_DEBUG_API=true CHALLENGE_SEED_KEY=<任意串>` 启动（compact 只允许 `ENABLE_DEBUG_API=true`），再 `E2E_CHALLENGE=1 BASE_URL=http://localhost:<port> python3 scripts/e2e_smoke.py`。
