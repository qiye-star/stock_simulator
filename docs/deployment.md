# 部署指南

## 1. 前置条件

- Docker 24+ 与 Docker Compose v2（`docker compose version`，需支持 `required: false` 与 `!reset`，即 v2.24+）
- 可选：`make`、`uv`（Python 3.12）、Node.js 22（仅本地开发需要）

## 2. 使用 Docker Compose 启动（默认 sqlite）

```bash
cp .env.example .env
docker compose up -d --build
```

访问网页版 `http://localhost:18000`（`FRONTEND_PORT`）、手机版 `http://localhost:18001`（`MOBILE_PORT`）。

启动顺序由 `depends_on` 保证：

1. `migrate` 执行 `alembic upgrade head`，成功后退出（`service_completed_successfully`）；
2. `backend` 启动并通过 healthcheck `GET /api/v1/healthz`；
3. `frontend`（网页版）与 `mobile`（手机版）启动。两者共用同一个 `backend` 与数据库。

查看状态与日志：

```bash
docker compose ps
docker compose logs -f backend
```

## 3. 切换数据库

数据库由 `.env` 中的 `DATABASE_URL` 决定，同时需要启用对应 profile 以启动数据库容器。

| 数据库 | 启动命令 | `DATABASE_URL` 示例 |
| --- | --- | --- |
| sqlite（默认） | `docker compose up -d --build` | `sqlite:////data/stocksim.db` |
| postgres | `docker compose --profile postgres up -d --build` | `postgresql+psycopg://stocksim:change-me@postgres:5432/stocksim` |
| mysql | `docker compose --profile mysql up -d --build` | `mysql+pymysql://stocksim:change-me@mysql:3306/stocksim?charset=utf8mb4` |

注意：

- 切换数据库后，`migrate` 会在新库上重新执行所有迁移。旧数据不会自动迁移，需要使用"导出存档 -> 导入"的方式迁移（`POST /import/legacy` 或存档导出接口）。
- 密码中包含 `@ : / ? #` 等字符时需要 URL 编码。
- MySQL 必须使用 `utf8mb4` 字符集，否则中文用户名与存档名会报错。
- `--profile` 只控制数据库服务是否启动，不会修改 `DATABASE_URL`。忘记同步两者是最常见的配置错误。

## 4. 数据卷与备份

| 卷 | 挂载位置 | 内容 |
| --- | --- | --- |
| `backend-data` | `/data`（backend、migrate） | sqlite 文件 `stocksim.db` |
| `postgres-data` | postgres 数据目录 | postgres 数据 |
| `mysql-data` | mysql 数据目录 | mysql 数据 |

sqlite 备份（服务不停机时使用 sqlite 在线备份命令，避免直接复制正在写入的文件）：

```bash
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/data/stocksim.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp backend:/data/backup.db ./stocksim-backup-$(date +%F).db
docker compose exec backend rm /data/backup.db
```

postgres / mysql 使用各自的 `pg_dump` / `mysqldump`。

## 5. 升级

```bash
git pull
docker compose up -d --build
```

`migrate` 会在 `backend` 启动前运行新的迁移。若迁移失败，`backend` 不会启动，旧版本的 `backend` 容器保持原状，可以 `docker compose logs migrate` 排查。

回滚：迁移默认不可逆时，请先备份数据库再升级。

## 6. 安全配置

- 生产环境保持 `ENABLE_DEBUG_API=false`，调试接口会修改存档资金与时间。
- 后端端口不对外暴露，只有 frontend 的 `FRONTEND_PORT` 与 mobile 的 `MOBILE_PORT` 对宿主机开放（公网部署建议绑定 127.0.0.1，由外层 nginx 对外）。
- 前端 nginx 已设置 CSP、`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy`，并隐藏 nginx 版本号。
- 若前面还有一层反向代理或负载均衡（TLS 终止），请确保它转发 `X-Forwarded-*` 头，并将 `/api/v1/ws/` 的 `Upgrade` 头透传。后端以 `--proxy-headers` 启动，`FORWARDED_ALLOW_IPS` 默认为 `*`，仅在容器网络内可达时安全；若后端对公网可达，请收紧该值。
- 将 `change-me` 等示例密码替换为强随机值。

### 双域名（a.com 网页版 + m.a.com 手机版）

- `https://a.com/` -> 宿主机 18000（`frontend`）；`https://m.a.com/` -> 宿主机 18001（`mobile`）；两个容器都把同源 `/api`（含 `/api/v1/ws/`）转发到 `backend:8000`，数据库共享。
- HTTPS 与域名分流由宿主机 nginx 完成，示例见 `deploy/host-nginx.example.conf`（80 跳 443、证书占位、WebSocket 1 小时读超时、`X-Forwarded-Proto/Host`）。
- `.env` 必须设置 `COOKIE_SECURE=true` 与随机 `SECRET_KEY`（compose 已透传）。Cookie 为 httpOnly + SameSite=Lax，不设 Domain：两个域名各自登录、互不影响，账号与存档共享。
- 后端没有 CORS / Host / Origin 校验，两站均为同源 `/api`，无需额外配置。
- 手机版资产曲线的存放位置以 `mobile-prototype/CLAUDE.md` 当前说明为准。

## 7. 本地开发（不使用 Docker）

```bash
make dev        # uvicorn --reload (8000) + vite (5173)
make test       # pytest + vitest
make lint       # ruff
make migrate    # 本地库升级到 head
```

## 8. 容器内开发（热更新）

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- 后端：`uv run uvicorn --reload`，源码挂载，依赖在命名卷 `backend-venv` 中。访问 `http://localhost:18002`（`BACKEND_DEV_PORT`，避开手机版的 18001）。
- 前端：`vite` 开发服务器，访问 `http://localhost:5173`，`/api` 由 vite 代理到 `backend`。
- 开发覆盖层不构建生产镜像，`migrate` 同样使用 uv 运行。

## 9. 常见问题

| 现象 | 处理 |
| --- | --- |
| `migrate` 退出码非 0 | `docker compose logs migrate`，多为 `DATABASE_URL` 错误或数据库未就绪 |
| 前端 502 | backend 未通过 healthcheck，`docker compose ps` 查看 `backend` 状态 |
| WebSocket 频繁断开 | 检查上游代理的读超时，应不小于 1 小时 |
| 启动 postgres 后连接失败 | 确认同时使用了 `--profile postgres` 与对应 `DATABASE_URL` |
| 中文乱码（mysql） | 确认 `DATABASE_URL` 含 `charset=utf8mb4` 且库为 utf8mb4 |
