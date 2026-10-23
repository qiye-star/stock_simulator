# stock-simulator-v2

股市模拟器重构版 monorepo。契约见 [docs/CONTRACT.md](docs/CONTRACT.md)，原版冻结在 `legacy/`（只读，用于对拍）。

## 结构
- `backend/` FastAPI + SQLAlchemy 2 + Alembic，uv 管理
- `frontend/` Vite + 原生 ES 模块
- `docs/` 架构与契约 · `scripts/` 辅助脚本 · `legacy/` 原版

## 规则
- 每个目录都有 CLAUDE.md + README.md，改了目录职责要同步更新。
- 金额整数分；改 model 必须配 Alembic 迁移；改 API 要同步 frontend/src/api。
- 后端命令：`cd backend && uv run pytest`；前端：`cd frontend && npm run build`。
- 端到端冒烟：启动 `cd backend && uv run uvicorn --factory stocksim.main:create_app --port 18000`（需 `DATABASE_URL` 与 `alembic upgrade head`），再 `BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py`。
- 前后端字段以 `backend/src/stocksim/schemas/*.py` 为准；前端 `api/endpoints.js` 的 typedef 必须与之一致（自动交易字段名见 `backend/src/stocksim/models/CLAUDE.md`）。
