# scripts（辅助脚本）— 给 agent 的说明

- `convert_stockdata.py`：`legacy/stockData.js` -> `backend/src/stocksim/data/{stock_pool,industries}.json`。
  - 只读 legacy，幂等，会断言 385 只且代码唯一，并给影视飓风（999999）标记 `profile=bull_bias`。
  - 运行：`python3 scripts/convert_stockdata.py`（仅用标准库，无需 uv）。
- `e2e_smoke.py`：对运行中的后端做 HTTP 冒烟（`BASE_URL`，默认 `http://localhost:18000`）。只用标准库（urllib + http.cookiejar）。步骤：注册随机用户 -> 建存档 -> 读行情 -> 买 100 股 -> 当日卖出应得 `TRADE_T1_SELL_BLOCKED` -> 持仓 -> 自选 -> 自动交易条件单 -> 导出。非交易时段需要服务端 `ENABLE_DEBUG_API=true`。
  - 启动：`cd backend && uv run uvicorn --factory stocksim.main:create_app --port 18000`（main.py 没有模块级 `app`，不要用 `stocksim.main:app`）。
- 脚本应保持纯标准库、可重复运行；不要在此放业务逻辑（业务在 backend/src）。
- 修改输出格式后，同步更新 `backend/tests/unit/data/` 中的断言。
