# schemas

接口的 Pydantic 模型。

| 文件 | 内容 |
| --- | --- |
| `auth.py` | 注册、登录、改密的请求体 |
| `user.py` | 用户响应 `UserOut`；偏好修改 `MePatch` |
| `stocks.py` | 股票目录 `StockOut` |
| `saves.py` | 存档创建/改名请求；存档响应 `SaveOut` |
| `market.py` | 行情快照（含 total/next_cursor）、时钟、个股日 K 与五档、当日分时 |
| `orders.py` | 下单请求 `OrderIn`；成交 `TradeOut`；下单结果 `OrderOut`；成交分页 |
| `portfolio.py` | 持仓与资产（含当日盈亏）、资产曲线 |
| `achievements.py` | 成就定义与已解锁项 |

字段约定：金额为整数分（`*_cents`），时间为 ISO 8601 UTC。
| `auto_trade.py` | 条件单（创建/替换）、条件单响应、运行状态、事件分页 |
| `legacy.py` | 旧版导入请求 `{content}`、旧存档严格结构、导入结果 |
| `debug.py` | 调试动作的请求体 |
| `predictions.py` | 预测卡题目、卡片、作答入参/出参、模式设置（02 §10.2） |
| `points.py` | 积分余额、流水、预测统计、称号 |
| `intel.py` | 情报卡购买入参与状态 |
| `challenges.py` | 每日挑战的响应（ChallengeOut、回合卡、报名、排行、reveal、复盘）与请求体（作答、调试） |
| `replay.py` | 真实复盘的关卡、会话、事件流（与 A 的 NewsOut 同形）、预测题、揭示与请求体（05 §5.8） |

预测市场（模式 D）：`prediction_markets.py`（市场、报价、下单、持仓、结算的请求与响应模型，04 §9.2）。
