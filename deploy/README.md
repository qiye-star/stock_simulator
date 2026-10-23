# deploy

宿主机 nginx 反代示例 `host-nginx.example.conf`（方案 A：两个域名、一个后端、一个数据库）。

| 域名 | 宿主机端口 | 容器服务 | 内容 |
| --- | --- | --- | --- |
| `https://a.com/` | 18000（`FRONTEND_PORT`） | `frontend` | 网页版（Vite 构建产物） |
| `https://m.a.com/` | 18001（`MOBILE_PORT`） | `mobile` | 手机版（静态原型） |

两个容器里的 nginx 都把同源 `/api`（含 `/api/v1/ws/` WebSocket）转发到同一个 `backend:8000`，所以数据库共享：同一账号在两边看到同一份存档。

## 使用

```bash
cp .env.example .env     # 设 SECRET_KEY（随机串）与 COOKIE_SECURE=true
docker compose up -d --build
sudo cp deploy/host-nginx.example.conf /etc/nginx/conf.d/stocksim.conf   # 改域名与证书路径
sudo nginx -t && sudo systemctl reload nginx
```

示例包含：80 跳 443、证书路径占位、`/api/v1/ws/` 的 Upgrade 与 `proxy_read_timeout 1h`、`X-Forwarded-Proto/Host`。容器端口只需绑定宿主机即可，防火墙不要对公网开放 18000/18001（可把 compose 的端口映射改为 `127.0.0.1:18000:8080`）。

## Cookie 与会话

- 后端的 `session` Cookie 为 httpOnly、SameSite=Lax、Path=/，**不设 Domain**，因此 a.com 与 m.a.com 各持一份，登录/登出互不影响。需要单点登录时才考虑 Domain=.a.com，当前刻意不做。
- HTTPS 部署必须在 `.env` 设 `COOKIE_SECURE=true`（compose 已透传给 backend）；纯 http 本地验证保持 false。
- 后端没有 CORS、Host、Origin 限制：两个站点都是同源 `/api`，无需跨域配置。
