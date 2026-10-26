# 静态数据（stocksim/data）

股票池与行业配置，供行情初始化使用。

| 文件 | 内容 |
|---|---|
| `stock_pool.json` | 385 只股票（代码、名称、行业、行情配置） |
| `industries.json` | 行业列表、股票数量与开局价格区间 |
| `supply_chain.json` | 82 个行业的上下游边（事件行情的传导图），由 `scripts/convert_supply_chain.py` 从 01a 草稿生成 |
| `stock_exposure.json` | 个股龙头标记与跨行业暴露度，由 `scripts/build_stock_exposure.py` 生成 |
| `news_templates.json` | 事件快讯文案模板与槽位，由 `scripts/news/build_templates.py` 生成 |

这些文件由 `scripts/` 下对应脚本生成，请勿手工编辑（改源后重跑脚本）。
股票顺序决定行情随机数的位置，修改顺序会改变所有历史行情的复现结果。
