# syntax=docker/dockerfile:1.7
# 多阶段构建：node 负责构建静态产物，nginx-unprivileged 负责托管并反代 /api/。

ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.27-alpine
# npm 镜像（默认 npmmirror，国内可直连）；海外构建可传 --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com

# ---------- build ----------
FROM ${NODE_IMAGE} AS build

ARG NPM_REGISTRY

ENV npm_config_fund=false \
    npm_config_audit=false \
    npm_config_registry=${NPM_REGISTRY}

WORKDIR /app

# 先拷依赖清单，保证 npm ci 层可以缓存
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY . .
RUN npm run build

# ---------- runtime ----------
FROM ${NGINX_IMAGE} AS runtime

# 后端地址：compose 中为 http://backend:8000；nginx 模板在启动时用它替换 ${BACKEND_UPSTREAM}
ENV BACKEND_UPSTREAM=http://backend:8000 \
    NGINX_ENVSUBST_FILTER=BACKEND_

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]

# 镜像默认以 uid 101 运行，无需 root
