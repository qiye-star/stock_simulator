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
3. `frontend`（网页版）与 `mobile`（手机版）启动。两者共用同一个 `backend` 与数据库；
4. `challenge-runner`（每日挑战定时任务，见 §6a）与 `backend` 同时启动、共用同一数据库。

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
| `backend-data` | `/data`（backend、migrate、challenge-runner） | sqlite 文件 `stocksim.db` |
| `postgres-data` | postgres 数据目录 | postgres 数据 |
| `mysql-data` | mysql 数据目录 | mysql 数据 |
| `replay-data` | `/replay`（replay-collector） | 真实复盘原始数据（见 §6b），只供离线构建，不进运行时 |

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

## 6a. 每日挑战定时任务（challenge-runner）

- `challenge-runner` 与 backend 同镜像、同环境变量（compose 用 YAML 锚点共用），执行 `stocksim-challenge loop --interval 15`。无人在线时它也会按时生成当日与明日（本地 12:00 起）挑战、开局、推进行情、结算、发奖与清理。**推荐生产开启**。
- 没有 runner 时挑战只会在有人访问挑战接口时懒触发（节流 `CHALLENGE_RUN_DUE_MIN_INTERVAL_S` 秒），没人在线的时段不会结算与发奖。
- 多实例与 runner 并存是安全的：生成靠 `challenge_date` 唯一键，状态迁移与结算靠条件更新与乐观锁，奖励靠积分账本的幂等键。
- **`CHALLENGE_SEED_KEY` 生产必须设置**。为空时由 `SECRET_KEY` 派生；若 `SECRET_KEY` 仍是开发默认值，后端启动会告警“挑战 seed 可预测”。
- `CHALLENGE_SCHEDULE=compact` 只用于开发与 e2e，且**要求 `ENABLE_DEBUG_API=true`**，否则后端启动失败。生产保持 `daily`。
- 常用命令（在 runner 容器内执行）：

```bash
docker compose exec challenge-runner stocksim-challenge run-due
docker compose exec challenge-runner stocksim-challenge show --date 2026-10-26   # 结算前只显示承诺，结算后显示 seed
docker compose exec challenge-runner stocksim-challenge void --date 2026-10-26 --reason "运维作废"
```

- 本地不用 Docker：`cd backend && uv run stocksim-challenge run-due`（读取 `backend/.env`）。
- 配置项与默认值见根目录 `.env.example`（`CHALLENGE_*`）与 `backend/src/stocksim/core/config.py`。

## 6a'. 预测市场多实例与后台任务

- 预测市场的后台 Hub 与 sweeper 默认在每个 backend 实例上启动（`PM_BACKGROUND_ENABLED=true`，`PM_POLL_MS=1000`，`PM_SWEEP_MS=10000`）。多个实例共用同一数据库即可，**不需要粘性会话，也不需要 Redis**；各实例的 sweeper 靠行锁、版本号与幂等键保证结算只生效一次（集成测试 `test_concurrent_sync_due_settles_once` 以三个线程并发执行 `sync_due` 验证结算只生效一次）。
- 每个实例每秒一次的小查询数为 `被关注挑战数`；配合索引可以忽略。规模变大时可把 `PM_POLL_MS` 调大，代价是推送延迟上限随之变大。
- **推荐 PostgreSQL**：多实例或多 worker 时 SQLite 的写锁会让下单频繁返回 `PM_BUSY`（重试 5 次后）。切换方式见本文 §3。
- 只需要 API、不需要实时推送的副本可设 `PM_BACKGROUND_ENABLED=false`；至少要有一个实例保持开启，否则结算只能靠用户访问时的惰性同步。

## 6b. 复盘数据抓存（replay-collector）

真实复盘（模式 E）的关卡要用到**只保留最近数据**的接口：财联社电报（最新 20 条）和东财个股新闻（每只股票最新 10 条）。`replay-collector` 从现在起定时抓存它们，供以后的复盘关卡离线构建。设计依据见 `docs/10.26-plan/05-真实复盘.md` §2.5。

- **默认不启动**（profile `collector`）。`docker compose up -d --build` 不会包含它。
- 启动与停止：

```bash
docker compose --profile collector up -d --build replay-collector
docker compose --profile collector logs -f replay-collector
docker compose --profile collector stop replay-collector
```

- 镜像 `stocksim-ingest:local` 由后端 Dockerfile 的 `ingest` stage 构建：基于 builder，额外安装 `ingest` 依赖组（akshare）。运行时镜像（`runtime`，默认构建目标）不含 akshare，内容与大小不变。
- 抓取计划（单进程 `collect --loop`，不需要 cron）：

| 任务 | 频率 | 去重 | 落盘 |
| --- | --- | --- | --- |
| 财联社电报 `全部` 与 `重点` | 每 120 秒各一次 | `sha1(发布日期+发布时间+标题+内容前 50 字)` | `cls/<yyyy-mm>/<发布日期>.jsonl` |
| 东财个股新闻 | 每 10 秒轮转一只（约 384 只，一轮约 64 分钟） | `sha1(新闻链接)` | `em_news/<代码>/<yyyy-mm>.jsonl` |
| 每日补抓 | 北京时间 20:30，当日一次（重启后当日未完成会补跑，完成后不重跑） | 覆盖当日文件 | 新闻联播 `cctv/`、公司动态 `gsrl/`、股票池当季公告 `cninfo/` |

- 相邻两次电报 `全部` 没有任何重叠时，写入 `_state/collect_log.jsonl`（`event: gap_suspected`），表示可能漏抓（高峰期 20 条可能不足以覆盖 120 秒）。
- 环境变量（写在 `.env` 中）：
  - `REPLAY_COLLECT_UNIVERSE`：默认 `pool`（股票池真实代码，排除彩蛋 999999）；也可写逗号分隔的 6 位代码，用于缩小范围。
  - `HTTP_PROXY` / `HTTPS_PROXY`：东财与财联社经 `requests` 访问，需要代理时设置，留空即直连。
  - `REPLAY_RATE_<HOST>_MS`：限速间隔覆盖（默认 eastmoney 1500ms、cninfo 3000ms、cctv 30000ms；财联社不限速，间隔 120 秒本身已足够慢）。
- 原始数据在卷 `replay-data`（容器内 `/replay`）。查看：

```bash
docker compose --profile collector exec replay-collector sh -c 'ls /replay/cls /replay/em_news'
docker compose --profile collector exec replay-collector tail -n 1 /replay/_state/collect_cursor.json
```

- 不想常驻容器时，也可以用宿主机 crontab 单次运行（与常驻二选一，不要同时开）：`docker compose --profile collector run --rm replay-collector python -m stocksim.replay_ingest collect --once`（建议每 2 分钟一次）和 `... daily`（每天 20:30）。`--once` 每次只轮转一只个股新闻，个股覆盖会明显变慢，因此推荐常驻。
- 体量与运维：原始数据约每年不到 1GB（电报约 0.75MB/天、个股新闻约 2MB/天，按月 gzip 后约 200MB/年）。**调用日志 `_state/fetch_log.jsonl` 每次请求一行（约 120 字节），常驻运行约每天 1.4MB，需要定期归档或轮转**。
- 版权：电报与东财新闻的正文属版权内容。原始数据只在卷里，不进 git，也不对外分发；关卡包只保留标题与不超过 300 字的摘要加来源链接（05 §10）。

## 国内构建加速

构建镜像时的依赖源已默认指向国内镜像，可在 `.env` 里改：

| 变量 | 默认值 | 海外官方源 |
|---|---|---|
| `PIP_INDEX_URL` | `https://pypi.tuna.tsinghua.edu.cn/simple`（清华） | `https://pypi.org/simple` |
| `NPM_REGISTRY` | `https://registry.npmmirror.com`（npmmirror） | `https://registry.npmjs.org` |

- 后端 Dockerfile 不再从 `ghcr.io` 拉 uv，而是用 pip 从镜像安装；依赖由 `uv.lock` 导出为带哈希的 requirements 后经镜像安装（镜像文件与官方一致，哈希照常校验）。
- 基础镜像（`python`、`node`、`nginx-unprivileged`、`postgres`）仍来自 Docker Hub，国内拉取慢时请给 Docker 守护进程配置镜像加速：在 `/etc/docker/daemon.json` 写入 `{"registry-mirrors": ["<你的加速地址>"]}` 后 `sudo systemctl restart docker`（1Panel 的「容器 → 配置」里也可设置镜像加速）。加速地址请用你自己可用的服务（如云厂商提供的专属加速器），公共镜像站变动频繁，仓库里不写死。
- 本地开发（`uv sync` / `npm ci`）与开发覆盖层 `docker-compose.dev.yml`（使用 `ghcr.io/astral-sh/uv` 镜像）未改动。

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
