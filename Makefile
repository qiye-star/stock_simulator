SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help dev test lint migrate migration up up-pg up-mysql down build logs gen-types

help: ## 列出所有目标
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## 本地热更新：uvicorn --reload (8000) + vite (5173)，Ctrl+C 一起退出
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(BACKEND_DIR) && uv sync --locked && uv run alembic upgrade head && \
	  uv run uvicorn --factory stocksim.main:create_app --reload --host 127.0.0.1 --port 8000 ) & \
	( cd $(FRONTEND_DIR) && npm ci && npm run dev ) & \
	wait

test: ## 运行后端 pytest 与前端 vitest
	cd $(BACKEND_DIR) && uv run pytest
	cd $(FRONTEND_DIR) && npm run test --if-present

lint: ## ruff 检查后端代码
	cd $(BACKEND_DIR) && uv run ruff check . && uv run ruff format --check .

migrate: ## 本地数据库升级到最新版本（alembic upgrade head）
	cd $(BACKEND_DIR) && uv run alembic upgrade head

migration: ## 生成迁移：make migration m="add xxx"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	cd $(BACKEND_DIR) && uv run alembic revision --autogenerate -m "$(m)"

up: ## 以 docker compose 启动（sqlite）
	$(COMPOSE) up -d --build

up-pg: ## 以 docker compose 启动并包含 postgres 服务
	$(COMPOSE) --profile postgres up -d --build

up-mysql: ## 以 docker compose 启动并包含 mysql 服务
	$(COMPOSE) --profile mysql up -d --build

down: ## 停止并移除容器（保留数据卷）
	$(COMPOSE) --profile postgres --profile mysql down

build: ## 构建后端与前端镜像
	$(COMPOSE) build

logs: ## 跟随容器日志
	$(COMPOSE) logs -f --tail=100

gen-types: ## [占位] 从后端 OpenAPI 生成前端类型，尚未实现
	@echo "gen-types: TODO，待 API schema 稳定后接入 openapi-typescript（backend 导出 openapi.json -> frontend/src/api/types.d.ts）"
	@exit 0
