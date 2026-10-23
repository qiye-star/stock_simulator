# syntax=docker/dockerfile:1.7
# 手机版镜像：无构建步骤，nginx-unprivileged 直接托管静态文件并反代同源 /api。
# 构建上下文为 mobile-prototype/ 本目录；dev-server.mjs、文档不进镜像（见 .dockerignore）。

ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.27-alpine

FROM ${NGINX_IMAGE} AS runtime

# 后端地址：compose 中为 http://backend:8000；启动时 envsubst 替换模板里的 ${BACKEND_UPSTREAM}
# （NGINX_ENVSUBST_FILTER 限定只替换 BACKEND_ 开头的变量，nginx 自身的 $host 等保持原样）
ENV BACKEND_UPSTREAM=http://backend:8000 \
    NGINX_ENVSUBST_FILTER=BACKEND_

COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template

# 只拷运行所需的静态文件（显式列出，避免把 deploy/、dev-server.mjs 带进去）
COPY index.html /usr/share/nginx/html/index.html
COPY css /usr/share/nginx/html/css
COPY js /usr/share/nginx/html/js

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]

# 镜像默认以 uid 101 运行，无需 root
