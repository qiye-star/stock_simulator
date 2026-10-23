# deploy/（给 agent）
仓库级部署示例，只放「容器之外」的配置。目前只有 `host-nginx.example.conf`：宿主机 nginx 终止 HTTPS，按域名把 a.com -> 127.0.0.1:18000（frontend）、m.a.com -> 127.0.0.1:18001（mobile）。
- 端口与 `docker-compose.yml` 的 `FRONTEND_PORT` / `MOBILE_PORT` 保持一致；改了要同步这里与 README。
- 两个 server 块都必须保留：80 跳 443、`/api/v1/ws/` 的 Upgrade + `proxy_read_timeout 1h`、`X-Forwarded-Proto/Host`。
- 不要给 Cookie 设 Domain=.a.com（两域名会话刻意隔离）；HTTPS 下后端需 `COOKIE_SECURE=true`。
- 容器内 nginx 模板在 `frontend/nginx/` 与 `mobile-prototype/deploy/`，不在这里。
