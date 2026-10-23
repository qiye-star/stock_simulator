# 领域层测试

| 文件 | 覆盖 |
|---|---|
| `test_rng.py` | 随机数金定值、范围、确定性 |
| `test_money.py` | 四舍五入、手续费、元与分转换 |
| `test_clock.py` | 交易时段边界、时间推进、跳过时间 |
| `test_rules.py` | 涨跌停、熔断、T+1 推导、数量校验 |
| `test_market_engine.py` | 行情确定性、±2%、涨跌停、交易日切换、彩蛋偏多、五档盘口 |
| `test_matching.py` | 买卖、手续费、限价单、T+1、快照与纯度 |
| `test_auto_trade.py` | 条件、冷却、上限（只计成功）、止损止盈、复用撮合 |
| `test_achievements.py` | 目录完整性、统计推导、判定 |
| `test_purity.py` | 领域层无 I/O、无框架依赖 |
