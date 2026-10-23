# schemas/ — 请求与响应模型（给 agent）

## 边界
- 只描述 HTTP 形状。业务校验（用户名字符集、密码长度、不可重复、交易单位等）在 `services/` 或 domain 抛 AppError/DomainError。

## 不变量
- 金额字段名以 `_cents` 结尾，类型为 int。
- 枚举型输入用 `Literal`，与 CHECK 约束一致。
- 下单数量与限价用 `StrictInt`，避免 bool/字符串被静默转换。
- 费率输出为去掉尾零的字符串（见 `SaveOut._rate_text`）。
- 响应模型用 `from_attributes=True` 从 ORM 对象构造；绝不返回 `password_hash`。
- 每个资源一个文件，其他 agent 的模型放在各自的新文件中。

## 文件地图
- `auth.py` RegisterIn、LoginIn、PasswordChangeIn。`user.py` UserOut、MePatch。
- `stocks.py` StockOut。`saves.py` SaveCreateIn、SaveUpdateIn、SaveOut。
- `market.py` QuoteOut、ClockOut、MarketOut（含 total、next_cursor）、StockMarketOut（日 K 与五档）、IntradayOut（当日分时）。
- `orders.py` OrderIn、TradeOut、OrderOut、TradePageOut。`portfolio.py` HoldingOut、PortfolioOut（含 prev_equity/day_pnl）、EquityPointOut、EquityCurveOut。
- `achievements.py` AchievementDefOut、SaveAchievementOut。

## 验证
`uv run pytest tests/integration/test_saves.py tests/integration/test_market.py tests/integration/test_orders.py tests/integration/test_portfolio.py -q`
- `auto_trade.py` 条件单请求/响应（百分比用 float，如 2.5 表示 2.5%，服务层转为 ×100 整数）、运行状态、事件分页。
- `legacy.py` 旧版导出的严格结构模型（已知字段严格类型，未知字段忽略）与导入请求/响应。`debug.py` 调试请求体。
