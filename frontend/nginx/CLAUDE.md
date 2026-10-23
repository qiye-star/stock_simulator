# frontend/nginx（给 agent）
default.conf.template 由 envsubst 注入 BACKEND_UPSTREAM（必须带 http:// 前缀，如 http://backend:8000）。改 CSP 时注意 style-src 需要 unsafe-inline。验证：`nginx -t` 于 nginx-unprivileged 镜像内。
