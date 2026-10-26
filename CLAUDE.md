# stock-simulator-v2

股市模拟器重构版 monorepo。契约见 [docs/CONTRACT.md](docs/CONTRACT.md)，原版冻结在 `legacy/`（只读，用于对拍）。

## 结构
- `backend/` FastAPI + SQLAlchemy 2 + Alembic，uv 管理
- `frontend/` Vite + 原生 ES 模块（网页版）
- `mobile-prototype/` 手机版纯静态前端（有自己的 Dockerfile 与 nginx 模板）
- `deploy/` 宿主机 nginx 反代示例（HTTPS + 域名分流）
- `mobile-prototype/` 手机端纯静态前端（无构建），已对接后端 `/api`：先起后端，再 `node mobile-prototype/dev-server.mjs`（:18765，同源反代 /api 含 WS，BACKEND_URL 可覆盖）；`?mock=1` 回退假数据
- `docs/` 架构与契约 · `scripts/` 辅助脚本 · `legacy/` 原版

## 规则
- 每个目录都有 CLAUDE.md + README.md，改了目录职责要同步更新。
- 金额整数分；改 model 必须配 Alembic 迁移；改 API 要同步 frontend/src/api。
- 后端命令：`cd backend && uv run pytest`；前端：`cd frontend && npm run build`。
- 端到端冒烟：启动 `cd backend && uv run uvicorn --factory stocksim.main:create_app --port 18000`（需 `DATABASE_URL` 与 `alembic upgrade head`），再 `BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py`。
- 每日挑战：compose `challenge-runner` 服务（`stocksim-challenge loop --interval 15`，与 backend 共用 `CHALLENGE_*`）推荐生产开启（见 `docs/deployment.md` §6a）；挑战段 e2e 需以 `CHALLENGE_SCHEDULE=compact CHALLENGE_MIN_ACCOUNT_AGE_HOURS=0 ENABLE_DEBUG_API=true CHALLENGE_SEED_KEY=<任意串>` 启动后端，再 `E2E_CHALLENGE=1 BASE_URL=... python3 scripts/e2e_smoke.py`。
- 部署（方案 A）：网页版 `https://a.com/`（compose `frontend`，`FRONTEND_PORT` 默认 18000）与手机版 `https://m.a.com/`（compose `mobile`，`MOBILE_PORT` 默认 18001）共用同一 backend 与数据库；外层宿主机 nginx 负责 HTTPS 与分流（`deploy/host-nginx.example.conf`），容器只提供 HTTP。HTTPS 下 `.env` 需 `COOKIE_SECURE=true`；Cookie 不设 Domain，两域名会话隔离；开发覆盖层后端端口为 18002（`BACKEND_DEV_PORT`）。
- 前后端字段以 `backend/src/stocksim/schemas/*.py` 为准；前端 `api/endpoints.js` 的 typedef 必须与之一致（自动交易字段名见 `backend/src/stocksim/models/CLAUDE.md`）。
