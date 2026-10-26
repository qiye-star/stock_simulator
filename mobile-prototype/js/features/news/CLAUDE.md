# js/features/news/ — 快讯 / 事件 / 产业链（⑤ A）

对应 `docs/10.26-plan/01-事件行情.md` §1、§8 与 `08-手机端.md` §5.5；画板见 08 §1.2。事件模式存档（`saves.events_enabled`）才有快讯，其它存档页面显示“本存档未开启事件模式”，行情页不显示快讯条与分段。

## 文件
| 文件 | 职责 |
| --- | --- |
| `mock.js` | `SS.mockFeatures.news`：6 个已发布事件 + 3 个待推送事件（`_queued`），12 个产业链节点、16 条边（取自 `supply_chain.json` 的行业名）。今天 = 第 48 个交易日 10:35 |
| `model.js` | `SS.newsModel`（纯函数）：`mergeNews`（去重、倒序、截断）、`matchesFilter`（全部/重大/我的持仓/政策/传闻）、`filterFromQuery`（`?filter=` 合法值）、`groupByDay`、`newsTags`、`propWindow`（传导窗口 3 日、已走天数、默认日）、`propSteps`（按日截止的节点与步骤）、`chainView`（上游/下游/同题材）、`revealText`、`suggestIndustries`、`defaultFocus`、`pickStrip`、`dayMajors`、`relatedQuotes`（事件相关分段与注记）、`klineMarks`（标记按 `trading_day` 对齐日 K 下标）、`markLegend`（图例行）、`constituents`（行业成分股，按代码升序、带 total）|
| `store.js` | `ensureNews({force})`、`newsFeed()`、`majorNews()`、`listNews`、`listEvents`、`loadEvent`、`loadEventMarks(code, days)`（K 线标记；mock 与后端同口径）、`loadSupplyChain({force})`，以及共用的 `newsEnabled()`、`resetNews()`。mock 与 real 同名；real 经 `guarded()` |
| `news-page.js` | `#/news`（快讯 tab）：过滤胶囊（深链 `#/news?filter=rumor` 直接选中，非法值保持上次选择）、按交易日分组、重大整卡、分页（全部/重大走服务端，其它前端过滤并续拉至多 5 页）、WS 实时插入顶部 |
| `event-page.js` | `#/event/:id`：头部标签与标题、传导回放（日 tab、节点按 `arrived_trading_day` 显示、未来日禁用）、锁提示（`event.intel` 槽，缺省“看产业链”）、后续快讯、`event.footer` 槽 |
| `chain-page.js` | `#/chain?focus=`：行业搜索（候选）、上游/下游/同题材、未揭示的边显示锁（`chain.edgeAction` 槽）、已揭示显示强度/滞后；切换焦点用 `router.replace`；点中心行业打开**行业抽屉**（`SS.sheet`）：成分股（`loadAllQuotes` 过滤，龙头有标记，点行进个股）、关联（只显示谁连着谁，不含强度/滞后，点行切焦点）、最近快讯（`listNews({industry, limit:5})`，无则隐藏）|
| `index.js` | 注册 routes；挂载 `market.banner`（快讯条）、`closeSummary.extra`（今天的大事，最多 2 条）、`stock.extra`（相关事件，最近 5 条）、`stock.kline`（日 K 下方事件标记：`.kmark` 点 + 最近 5 条图例，点击进事件详情；按（代码, 交易日）缓存，快讯 WS 与切存档清空）；`marketLists` “事件相关”（事件详情→已到达的行业股票，事发/传导注记）；订阅 `ws:news`（合并缓存、`news:update`、重大 toast、truncated 时强制重拉首屏）；mock 模式按队列推送 |

## 数据约定
- 字段与 `backend/src/stocksim/schemas/events.py` 一致：`NewsOut`、`EventOut`、`EventDetailOut`（`news` 按时间升序、`propagation` 只含已到达节点）、`SupplyChainOut`。
- 每个节点的 `change_bp` 是后端口径：到达后 3 个交易日的行业等权涨跌（从到达日前一日收盘起算，不随回放日变化）；页面注明此口径，切日不重算。
- 强度/滞后只在 `revealed_level` ≥ 1/2 时出现；未揭示的边不展示数字。
- `state.news` = `{saveId, items（最近 50 条，倒序）, majors（最近 20 条重大）, loaded, chain}`，切换存档时清空。

## 降级与状态
- `FEATURE_UNAVAILABLE`（接口缺失）：快讯/事件/产业链整页显示“即将开放”卡；`stock.extra`、`stock.kline` 与快讯条静默隐藏。
- `EVENTS_DISABLED`：快讯页显示“本存档未开启事件模式”+“新建事件模式存档”（调用 `SS.openSaves`，即 `me.js` 的存档抽屉）。事件模式关闭的存档不发任何快讯请求。
- `EVENT_NOT_FOUND`：事件详情显示“事件不存在或尚未发布”。
- 其它错误：页面内“加载失败，点击重试”。

## mock 与 real 差异
- mock 固定 `events_enabled: true`（`js/mock/data.js`），`queue` 每约 18 秒推送一条（首条约 9 秒后），用 `ws:news` 广播。
- mock 的 `loadEvent` 只返回已推送的快讯与 `arrived_trading_tick ≤ 当前` 的节点。

## 未做（08 §8 决策与 ⑥ 之后）
- 情报卡、“你的预测”已由 ⑥ 预测卡功能（`js/features/predict/slot-widgets.js`）填充上述槽位。
- 个股 K 线只标事件的发布日（source / market）与传导到达日（propagated），不画强度。

## ⑥ 变更
- `chain-page.js`：未揭示或只揭示强度的边右侧附 `chain.edgeAction` 槽（情报按钮）；点击情报按钮不切换焦点（委托给 `[data-intel-edge]`）；监听 `intel` 事件重新加载产业链。
- `mock.js`：产业链边增加私有字段 `_strength` / `_lag`（隐藏真值，情报卡购买后揭示）。

## 第 4–6 项（挑战联调期补齐）
- K 线标记：`stock.kline` 槽由 `index.js` 注册，`js/pages/stock.js` 日 K 绘制后挂载；`event-marks` 的 `role`：`source` 事发（强调色实心点）、`propagated` 传导（强调色空心）、`market` 大盘（虚线空心）。
- 行业抽屉：只使用 `chain` 的 `nodes`（`leaders` 为代码）与 `edges` 结构；未揭示的强度/滞后不出现在抽屉里。
- 快讯深链：`#/news?filter=rumor` 等，`render(view, params)` 读取 `params.query.filter`。

## 验证
- `node mobile-prototype/tests/run.mjs`（`tests/news-model.test.mjs`）。
- 真实后端（挑战联调库，`CHALLENGE_SCHEDULE=compact` 与 `ENABLE_DEBUG_API=true`）：事件存档 `POST /clock/skip` 约 30 次后，快讯“传闻”只显示传闻；`601899` 的 K 线出现事发/大盘标记与图例；产业链抽屉显示 7 只成分股与关联，窄屏无横向滚动。
- `?mock=1`：快讯（过滤、分组、推送插入）、事件详情（日 tab）、产业链（焦点切换、搜索）、行情“事件相关”、收盘小结（`SS.closeSummary.open({tradingDay: 47})`）、个股相关事件。
- 真实后端（事件模式存档，`alembic upgrade head` 后 `POST /clock/skip` 数次即出现快讯）：快讯 → 事件详情 → 产业链 → 行情分段。
