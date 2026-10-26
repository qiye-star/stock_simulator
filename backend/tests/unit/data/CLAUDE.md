# tests/unit/data（静态数据测试）— 给 agent 的说明

- 校验 `backend/src/stocksim/data/*.json`：股票数量 385、代码唯一、profile 标记、行业统计一致。
- 数据变更后若断言需要更新，先确认是否由 `scripts/convert_stockdata.py` 生成的预期变化。
- `test_event_data_files.py`：产业链/暴露度/模板的契约、与转换脚本产物一致、md→json→md 往返无损、模板全槽位可渲染；数据由 `scripts/` 生成，断言失败先重跑脚本。
- 运行：`cd backend && uv run pytest tests/unit/data -q`
