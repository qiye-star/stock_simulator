# 领域层测试

| 文件 | 覆盖 |
|---|---|
| `test_rng.py` | 随机数金定值、范围、确定性 |
| `test_money.py` | 四舍五入、手续费、元与分转换 |
| `test_clock.py` | 交易时段边界、时间推进、跳过时间（v1） |
| `test_clock_v2.py` | v2 相位/撮合窗/文案/跳过表（8 次跳过走完一日）、对齐不变量逐分钟、TimeBase、墙钟调度（停留、截断、精确到期） |
| `test_clock_v2_rng_layout.py` | v2 RNG（共同因子 idx 400、日档位 `-2^33-d`）与 v1/init/事件命名空间无碰撞 |
| `test_market_engine_v2.py` | v2 引擎：换日只在次日 9:30、prev_close、涨跌停、成交量单调、档位纯函数、单股重放一致、drift 语义 |
| `test_market_engine_v2_golden.py` | v2 金值（3 个种子 × 全局 tick 300/700/1500），发布后冻结 |
| `test_market_engine_rules1.py` | 显式 `rules=1` 与 v1 金值逐位一致 |
| `test_rules.py` | 涨跌停、熔断、T+1 推导、数量校验 |
| `test_market_engine.py` | 行情确定性、±2%、涨跌停、交易日切换、彩蛋偏多、五档盘口 |
| `test_market_engine_golden.py` | 事件漂移上线前采集的引擎 sha256 金值；`drift=None/{}` 逐位一致 |
| `test_events_rng_layout.py` | 事件 RNG 命名空间与现有行情/init/开局分钟无碰撞 |
| `test_events_generate.py` | 事件生成确定性、频率、ID、辟谣率、priced_in 比例、文案渲染；v2 每日重大事件、同日发布 tick 错开、避开 11:30/15:00 偏移 |
| `test_events_propagation.py` | 传导方向/符号/门控/延迟/截断/跳数/环路/多父相加；v2 延迟随交易日长度缩放 |
| `test_events_path.py` | 形状曲线差分求和、归零、反向、步长与寿命上限 |
| `test_events_plan.py` | 日计划漂移上限、单股重放一致、无熔断、快讯区间 |
| `test_events_timing.py` | tick 常量按 ticks_per_day 参数化（20 恒等、242 自洽）；发布偏移合法集 v1/v2 |
| `test_events_reveal.py` | 情报提示准确率、传闻状态、事件阶段 |
| `test_matching.py` | 买卖、手续费、限价单、T+1、快照与纯度；v2 撮合窗（690/900 拒单，689/899 接单） |
| `test_auto_trade.py` | 条件、冷却、上限（只计成功）、止损止盈、复用撮合；v2 撮合窗 |
| `test_achievements.py` | 目录完整性、统计推导、判定；v2 夜猫窗口 895–899 |
| `test_purity.py` | 领域层无 I/O、无框架依赖 |

预测卡新增：`test_scoring.py`、`test_prediction_questions.py`、`test_prediction_titles.py`、`test_prediction_rng_layout.py`。
真实复盘：`test_replay.py`；`test_rules.py`、`test_matching.py` 增补 20% 板块用例。
