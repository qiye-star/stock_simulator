# js/mock/ — 假数据

`data.js` 用固定种子（mulberry32）生成，刷新页面结果不变，导出 `SS.mock`。

- 字段名以 `backend/src/stocksim/schemas/*.py` 为准：QuoteOut、CandleOut、HoldingOut（原始部分）、TradeOut（`code`）、AutoConfigOut / AutoStatusOut / AutoEventOut（`stock_code`）、UserOut。
- 金额是整数分；`change_bp` 单位为基点；自动交易百分比是 float。
- 原型私有字段以 `_` 开头：`_series` 是分时价格，`_candles` 是历史日 K。
- 股票取自 `backend/src/stocksim/data/stock_pool.json`，包括 `999999 影视飓风` 彩蛋。
- 修改 POOL 里的涨跌幅可以调整红绿分布。分时数据用布朗桥生成，保证终点落在目标涨跌幅上。
- 时钟默认是 v2 存档（`clock_rules: "v2"`，`ms_per_minute` 由 `SPEEDS_V2.normal` 得出）。演示参数只在假数据模式生效：`?mockclock=HH:MM` 覆盖起始分钟（非法值忽略，分时下标按午休折叠，与 `store.real.js::minuteIdx` 一致）；`?mockrules=v1` 切到经典存档；`?mockspeed=N` 把每分钟毫秒数除以 N（只加速 `ms_per_minute`，停留时长不变）。
- v2 调度（`js/lib/store.js`）镜像 07 §5.2：11:30 停 5 s 跳 12:59，15:00 停 15 s 跳次日 9:29，9:30 换日（`rollDay`，昨收 = 上一日收盘，T+1 冻结解除，权益曲线新增 live 点）；收盘时 `closeDay` 生成日 K；每次时段变化先发 `tick` 再发 `phase`（与后端一致）；假数据 `_offset_ms = 0`。`loadDaySummary` 按 DaySummaryOut 形状计算；历史日行情用当前股票池近似。

## ⑤ 变更
- POOL 追加 `601899 紫金矿业`（有色，自选）、`603993 洛阳钼业`（有色，自选）、`002460 赣锋锂业`（新能源）。
- 存档 `events_enabled: true`（事件模式，便于快讯/事件/产业链演示）。
- 快讯、事件、产业链假数据在 `js/features/news/mock.js`（`SS.mockFeatures.news`），不放在本目录。
