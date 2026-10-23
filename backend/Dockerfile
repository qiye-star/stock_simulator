# syntax=docker/dockerfile:1.7
# 多阶段构建：builder 用 uv 安装锁定依赖，runtime 只带 venv 与源码。

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_VERSION=0.8.22
# PyPI 镜像（默认清华源，国内可直连）；海外构建可传 --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# ---------- builder ----------
FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION
ARG PIP_INDEX_URL

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL}

# 从镜像源安装 uv，避免依赖 ghcr.io（国内常不可达）
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} uv==${UV_VERSION}

WORKDIR /app

# 说明：uv.lock 里记录的源是 pypi.org，直接 `uv sync --locked` 换镜像会判定锁文件过期，
# 且 --frozen 会直连 files.pythonhosted.org（国内慢）。所以先把锁文件导出为带哈希的
# requirements，再用镜像源安装：镜像里的文件与官方完全一致，哈希校验照常通过。
# 第一层：只挂载 pyproject/uv.lock 装第三方依赖，依赖不变时命中缓存
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/requirements.txt \
 && uv venv /app/.venv \
 && uv pip install --python /app/.venv/bin/python --require-hashes -r /tmp/requirements.txt

# 第二层：拷入源码，以可编辑方式安装项目本身（与 uv sync 行为一致，不再装依赖）
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /app/.venv/bin/python --no-deps -e .

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
