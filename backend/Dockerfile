# syntax=docker/dockerfile:1.7
# 多阶段构建：builder 用 uv 安装锁定依赖，runtime 只带 venv 与源码。

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.22

FROM ${UV_IMAGE} AS uv

# ---------- builder ----------
FROM ${PYTHON_IMAGE} AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

# 第一层：只挂载 pyproject/uv.lock 装第三方依赖，依赖不变时命中缓存
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    uv sync --locked --no-dev --no-install-project

# 第二层：拷入源码，安装项目本身
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL="sqlite:////data/stocksim.db" \
    FORWARDED_ALLOW_IPS="*"

# 非 root 用户；代码目录属 root 只读，/data 为可写的 sqlite 数据卷
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown 10001:10001 /data

WORKDIR /app
COPY --from=builder /app /app

VOLUME ["/data"]
EXPOSE 8000

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz', timeout=2).status == 200 else 1)"]

# 单 worker：行情引擎与 WebSocket 广播状态保存在进程内，多 worker 会失去一致性
CMD ["uvicorn", "--factory", "stocksim.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
