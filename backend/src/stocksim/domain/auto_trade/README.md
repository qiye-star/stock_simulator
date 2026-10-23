# 自动交易（domain/auto_trade）

根据价格、涨跌幅、盈亏金额或固定时间间隔自动下单，并支持止损与止盈。
每次检查返回新的运行时状态、账户、新增成交与事件列表，由服务层保存并推送给前端。

## 用法
```python
from stocksim.domain.auto_trade.executor import AutoRuntime, run_auto_trades

result = run_auto_trades(
    configs,
    runtime,
    tick=t,
    trading_day=d,
    minute_of_day=m,
    quotes=quotes,
    account=account,
    settings=settings,
    trades=trades,
)
```

## 文件
- `conditions.py`：条件与冷却判断
- `executor.py`：执行与事件生成（买卖复用 `matching.execute_order`）

## 说明
- 冷却与上限的口径、与旧版的差异见 [CLAUDE.md](CLAUDE.md)。
- 自动交易不做 10%-20% 偏离确认，但 20% 以上的偏离仍会被拒绝。
