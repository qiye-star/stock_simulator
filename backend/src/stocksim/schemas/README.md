# schemas

接口的 Pydantic 模型。

| 文件 | 内容 |
| --- | --- |
| `auth.py` | 注册、登录、改密的请求体 |
| `user.py` | 用户响应 `UserOut`；偏好修改 `MePatch` |
| `stocks.py` | 股票目录 `StockOut` |
| `saves.py` | 存档创建/改名请求；存档响应 `SaveOut` |
| `market.py` | 行情快照、时钟、个股日 K 与五档 |
| `orders.py` | 下单请求 `OrderIn`；成交 `TradeOut`；下单结果 `OrderOut`；成交分页 |
| `portfolio.py` | 持仓与资产 |
| `achievements.py` | 成就定义与已解锁项 |

字段约定：金额为整数分（`*_cents`），时间为 ISO 8601 UTC。
| `auto_trade.py` | 条件单（创建/替换）、条件单响应、运行状态、事件分页 |
| `legacy.py` | 旧版导入请求 `{content}`、旧存档严格结构、导入结果 |
| `debug.py` | 调试动作的请求体 |
