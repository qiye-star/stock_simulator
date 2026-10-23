# domain/auto_trade（自动交易）— 给 agent 的说明

## 边界
- 纯函数，零 I/O，遵守 `../CLAUDE.md` 的纯度规则。
- 买卖逻辑只能经由 `matching.execute_order`（executor 中仅 import 它），禁止在此复制买卖/T+1/手续费代码。
- 冷却按 tick 计，不用毫秒；配置的时间单位由调用方转换（价格/盈亏为分，百分比为基点）。

## 文件
- `conditions.py`：`AutoTradeConfig`、`cooldown_ticks`、`base_triggered`、`stop_or_take_triggered`、`should_trigger`、`position_pnl_cents`
- `executor.py`：`AutoRuntime`（不可变运行时状态）、`AutoEvent`（每次尝试一条）、`AutoTickResult`、`run_auto_trades`

## 行为（对应 legacy game.js 5643-6039）
- 非交易时段直接返回；`quotes` 中找不到的股票跳过（不产生事件）。
- 冷却：key=`{code}-{direction}`，默认 2 tick，time 类 10 tick；进入执行即更新冷却（失败也计入）。
- 每个配置的 `max_trades` 只统计成功成交；全局 `total_success` 只统计成功成交（修复 legacy）。
- 全局达到上限：失败事件 `AUTO_LIMIT_REACHED`，params.notify 仅第一次为 True。
- 单次金额上限 `max_amount_cents`：价*量超过则 `AUTO_MAX_AMOUNT_EXCEEDED`。
- 自动单 `confirm_deviation=True`（legacy 自动单无偏离确认）。

## 不变量
- 成功事件的 `amount_cents` 等于成交记录的 cash_cents；失败事件 `success=False` 且 `reason` 为错误码。
- 新成交按顺序追加到工作副本，供同一 tick 后续配置做 T+1 判断。

## 常见任务
- 增加条件类型：改 conditions.base_triggered，并在 tests/unit/domain/test_auto_trade.py 加用例。
- 改冷却：改 conditions.DEFAULT_COOLDOWN_TICKS / TIME_COOLDOWN_TICKS。

## 验证
`cd backend && uv run pytest tests/unit/domain/test_auto_trade.py -q`
