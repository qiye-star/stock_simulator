# 成就（domain/achievements）

成就目录、统计与判定。所有统计都从成交记录推导，因此同一存档重算结果一致。

## 用法
```python
from stocksim.domain.achievements.stats import compute_stats
from stocksim.domain.achievements.evaluator import evaluate

stats = compute_stats(
    trades=trades, holdings=holdings, prices=prices, fund_cents=fund, initial_fund_cents=initial
)
new_ids = evaluate(stats, unlocked_ids)
```

## 文件
- `catalog.py`：成就定义（54 个，其中 39 个可见）
- `stats.py`：统计计算
- `evaluator.py`：解锁判定

## 说明
- 隐藏成就与原因见 [CLAUDE.md](CLAUDE.md)。
- 成就名称与描述在前端 i18n 中维护。
