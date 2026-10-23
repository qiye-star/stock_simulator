# deploy

生产部署用的 nginx 片段 `nginx.conf.template`：托管 `mobile-prototype/` 静态文件，并把同源 `/api`（含 WebSocket）反代到后端。变量 `BACKEND_UPSTREAM`（如 `http://backend:8000`）用 envsubst 注入。`Dockerfile` 构建时已内置；含安全响应头与 CSP、gzip、`/healthz`、1 MB 请求体上限；`X-Forwarded-Proto` 优先透传外层反代传来的值。开发期不需要它，用 `../dev-server.mjs`。
