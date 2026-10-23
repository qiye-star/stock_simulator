# js/mock/ — 假数据

`data.js` 用固定种子（mulberry32）生成，刷新页面结果不变，导出 `SS.mock`。

- 字段名以 `backend/src/stocksim/schemas/*.py` 为准：QuoteOut、CandleOut、HoldingOut（原始部分）、TradeOut（`code`）、AutoConfigOut / AutoStatusOut / AutoEventOut（`stock_code`）、UserOut。
- 金额是整数分；`change_bp` 单位为基点；自动交易百分比是 float。
- 原型私有字段以 `_` 开头：`_series` 是分时价格，`_candles` 是历史日 K。
- 股票取自 `backend/src/stocksim/data/stock_pool.json`，包括 `999999 影视飓风` 彩蛋。
- 修改 POOL 里的涨跌幅可以调整红绿分布。分时数据用布朗桥生成，保证终点落在目标涨跌幅上。
