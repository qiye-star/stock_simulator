# domain/achievements（成就）— 给 agent 的说明

## 边界
- 纯函数，零 I/O。名称与描述不在后端，由前端 i18n 的 `achievement.<id>.name/desc` 提供。
- 统计只从成交记录（TradeRecord，含 trade-time 快照）和当前持仓/行情推导，不读任何可变存档字段。

## 文件
- `catalog.py`：54 个成就（`CATALOG`，`CATALOG_BY_ID`），`AchievementDef(id, level, category, stat, threshold, hidden, hidden_reason, op)`。
  - `threshold`：金额单位分（1000 元 = 100000），收益率单位基点（1000 = 10%）。
  - `op="gte"` 为 stat >= threshold；`op="all_others"` 为除隐藏成就外其它可见成就全部已解锁。
  - `hidden=True` 共 15 个，永不解锁，`hidden_reason` 说明原因（legacy 从未写入其输入或无法可靠推导）。
- `stats.py`：`AchievementStats` 与 `compute_stats(...)`。
- `evaluator.py`：`evaluate(stats, unlocked_ids, catalog)` 返回新解锁 id（按目录顺序，不重复）。

## 与 legacy 的差异（有意修复）
- sectors 用集合去重（legacy 对数组取 length 的问题已修）。
- 高买/涨停买入等用成交时的 prev_close 快照，不用当前昨收。
- 夜猫/早起等时段用成交的 minute_of_day。
- all_in 用成交前资金 fund_before_cents（legacy 用当前资金）。
- day_trader / day_trader_pro 由成交推导（legacy 的 dayTrades 从未递增）。
- perfect_game 由卖出盈亏推导（legacy 从未写入）。
- “累计盈利”= max(0, 当前净值 - 初始资金)，与 legacy 语义一致但显式计算。
- 隐藏成就（15 个）见 catalog.py 的 hidden_reason。

## 常见任务
- 新成就：在 catalog.py 加 AchievementDef，stat 必须是 AchievementStats 的字段；在 stats.py 计算；在 tests/unit/domain/test_achievements.py 加用例。
- 解除隐藏：必须有可靠的数据来源（如记录卖出后即时价），否则保持 hidden。

## 验证
`cd backend && uv run pytest tests/unit/domain/test_achievements.py -q`
