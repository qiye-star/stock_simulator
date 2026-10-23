# tests/unit/data（静态数据测试）— 给 agent 的说明

- 校验 `backend/src/stocksim/data/*.json`：股票数量 385、代码唯一、profile 标记、行业统计一致。
- 数据变更后若断言需要更新，先确认是否由 `scripts/convert_stockdata.py` 生成的预期变化。
- 运行：`cd backend && uv run pytest tests/unit/data -q`
