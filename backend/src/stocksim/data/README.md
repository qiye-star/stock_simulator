# 静态数据（stocksim/data）

股票池与行业配置，供行情初始化使用。

| 文件 | 内容 |
|---|---|
| `stock_pool.json` | 385 只股票（代码、名称、行业、行情配置） |
| `industries.json` | 行业列表、股票数量与开局价格区间 |

这些文件由 `scripts/convert_stockdata.py` 生成，请勿手工编辑。
股票顺序决定行情随机数的位置，修改顺序会改变所有历史行情的复现结果。
