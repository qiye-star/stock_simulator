<p align="right">
  <a href="README_EN.md">
    <img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English README" />
  </a>
</p>

# 股市模拟器 v2

一个纯娱乐、零压力的 A 股模拟炒股平台。这是 [原版](legacy/README.md) 的重构版：原版完全在浏览器中运行，v2 拆分为 **FastAPI 后端** 与 **Vite 前端**，支持账号、多存档、服务端行情推进与 WebSocket 实时推送。

所有行情均由本地算法生成，不连接任何真实行情接口，可在无资金风险的环境中学习交易规则、体验波动并测试策略。

---

## 功能概览

- 多存档、多账号，存档可导出、导入（兼容旧版导出文本）
- 市价单 / 限价单，涨跌停 ±10%，T+1（可开启 T+0），交易单位 1 或 100 股
- 确定性行情：同一存档在任何时间重放结果一致，离线期间的行情自动补算
- 自动交易规则、成就系统、K 线与五档盘口
- 中英双语，浅色 / 深色主题

## 快速开始

### 方式一：Docker Compose（推荐）

需要 Docker 与 Docker Compose v2。

```bash
cp .env.example .env
docker compose up -d --build
```

打开 <http://localhost:18000>。端口可在 `.env` 中用 `FRONTEND_PORT` 修改。

停止服务：

```bash
docker compose down
```

### 方式二：本地开发（热更新）

需要 [uv](https://docs.astral.sh/uv/)（Python 3.12）、Node.js 22 与 `make`。

```bash
make dev
```

- 前端：<http://localhost:5173>
- 后端 API 文档：<http://127.0.0.1:8000/docs>

也可以只启动容器化的开发环境：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

运行 `make help` 查看全部命令。

## 切换数据库

默认使用 sqlite，数据保存在 compose 卷 `backend-data` 中，无需额外服务。如需 PostgreSQL 或 MySQL：

| 数据库 | 命令 | `.env` 中的 `DATABASE_URL` |
| --- | --- | --- |
| sqlite（默认） | `docker compose up -d --build` | `sqlite:////data/stocksim.db` |
| PostgreSQL | `docker compose --profile postgres up -d --build` | `postgresql+psycopg://stocksim:change-me@postgres:5432/stocksim` |
| MySQL | `docker compose --profile mysql up -d --build` | `mysql+pymysql://stocksim:change-me@mysql:3306/stocksim?charset=utf8mb4` |

要点：

1. 启动参数里的 `--profile` 和 `.env` 里的 `DATABASE_URL` 必须同时修改。
2. 切换数据库后是一个空库，启动时会自动执行迁移。旧库中的存档需要先导出再导入。
3. 修改 `.env` 后需要重新执行 `up`，容器才会读取新值。

更多细节见 [部署指南](docs/deployment.md)。

## 项目结构

| 路径 | 说明 |
| --- | --- |
| `backend/` | FastAPI 后端（uv 管理，包名 `stocksim`），含 Alembic 迁移 |
| `frontend/` | Vite 前端，原生 ES 模块 |
| `docs/` | 架构、部署、契约与 ADR 决策记录 |
| `scripts/` | 仓库级辅助脚本（目前为空） |
| `legacy/` | 原版前端代码（只读，用于对拍参考） |
| `docker-compose.yml` | 生产形态编排：migrate → backend → frontend，可选 postgres / mysql |
| `docker-compose.dev.yml` | 开发覆盖层：源码挂载与热更新 |
| `.env.example` | 环境变量模板 |
| `Makefile` | 常用命令：`make dev`、`make test`、`make lint`、`make up` 等 |
| `.github/workflows/ci.yml` | CI：后端 ruff + pytest、Alembic 冒烟、前端构建与测试 |

每个目录都有 `CLAUDE.md`（给 AI agent 的边界说明）与 `README.md`（给人的说明）。

## 文档

- [架构说明](docs/architecture.md)
- [部署指南](docs/deployment.md)
- [契约](docs/CONTRACT.md)
- [架构决策记录](docs/adr/README.md)

## 开发者说明

- 金额统一用整数分存储与传输，字段名以 `_cents` 结尾。
- 修改数据库模型必须同时添加 Alembic 迁移。
- 修改 API 需同步前端的 `frontend/src/api`。
- 后端测试：`cd backend && uv run pytest`；前端构建：`cd frontend && npm run build`。

## 致谢与许可证

原版作者：莫客星图（Bilibili）。许可证见 [LICENSE](LICENSE)。
