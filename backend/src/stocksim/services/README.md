# services

业务服务层。

| 文件 | 内容 |
| --- | --- |
| `auth.py` | 账号与会话：注册、登录、登出、改密、偏好设置、注销账号 |
| `stocks.py` | 股票池静态数据读取（`stock_pool()` 顺序即 stock_idx）、stocks 表查询 |
| `seed.py` | 股票表幂等种子，启动时调用 |
| `market.py` | 行情推进（挂钟补推、跳过）、行情列表（分页/搜索/排序/键集游标）与个股视图、个股当日分时（确定性重放）、暂停/继续/跳过时钟、新存档行情初始化 |
| `trading.py` | 下单（手动与自动共用）、持仓同步、成交流水分页、Idempotency-Key |
| `portfolio.py` | 资产与持仓估值、T+1 可卖股数、当日盈亏 |
| `equity.py` | 收盘权益快照（幂等 upsert；并发冲突由 `market._retrying` 回滚重算）与资产曲线 |
| `achievements.py` | 成就目录、已解锁列表、成交后判定落库 |
| `saves.py` | 存档 CRUD、归属校验 `open_save`、导出、自选 |

服务函数只接受普通参数与 `Session`，失败时抛出 `AppError`，由 API 层统一转换为 HTTP 响应。

| `auto_trade.py` | 自动交易：条件单 CRUD、启停/暂停/恢复/重置、事件分页、`run_auto_trade` 评估执行 |
| `legacy_import.py` | 旧版导出文本（XOR+Base64 / JSON）解码、严格校验、映射为当前用户的新存档、审计 |
| `events.py` | 事件行情服务：漂移与快讯入口、快讯/事件列表与详情、个股标记、产业链结构、情报揭示与传闻提示（01 §8） |
| `event_hooks.py` | 事件扩展点：发布暂停钩子、reset 钩子、揭示 provider |
| `debug.py` | 调试操作：资金、时钟、成就、重置行情、清空存档（仅 `ENABLE_DEBUG_API`） |

新增：`points.py`（积分账本）、`tx.py`（事务重试）、`predictions.py`（预测卡）、`intel.py`（情报卡）、`titles.py`（称号）、`day_summary.py`（收盘小结）。

`challenges/`：每日挑战服务（生成、推进与镜像、报名、回合与判定、结算与排行、给 D 的契约函数），详见 `challenges/README.md`。

预测市场（模式 D，04 §3–§6）：`pm_lifecycle.py`（物化、两阶段同步、结算与作废、sweeper `sync_due`）、`prediction_markets.py`（报价、下单、列表与详情视图、历史、成交带、我的持仓与结算、收益榜）。
