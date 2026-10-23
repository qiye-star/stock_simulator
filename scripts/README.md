# 脚本（scripts）

项目级辅助脚本，与后端运行环境无关。

| 脚本 | 用途 |
|---|---|
| `convert_stockdata.py` | 把 legacy 的股票数据转换为后端使用的 JSON |
| `e2e_smoke.py` | 端到端 HTTP 冒烟：注册、建存档、行情、买入、T+1 拦截、持仓、自选、自动交易条件单、导出（仅标准库） |

```bash
python3 scripts/convert_stockdata.py

# 先启动后端（需迁移到最新）：
#   cd backend && uv run alembic upgrade head
#   cd backend && ENABLE_DEBUG_API=true uv run uvicorn --factory stocksim.main:create_app --port 18000
BASE_URL=http://localhost:18000 python3 scripts/e2e_smoke.py
```

`e2e_smoke.py` 逐步打印 PASS/FAIL，任一失败以非零码退出。若开局不在交易时段，会调用 `debug/time`（需要 `ENABLE_DEBUG_API=true`）。`BASE_URL` 默认 `http://localhost:18000`。
