# js/features/pm/ — 预测市场（⑧ D）

对应 `docs/10.26-plan/04-预测市场.md` §9（REST / schemas / 错误码）、§8（WS）、§10.3（手机端）与 `08-手机端.md` §5.8；画板 Play（分区）/ Contract（合约详情）。只做手机端，不改 `frontend/` `backend/`。

## 文件
| 文件 | 职责 |
| --- | --- |
| `model.js` | `SS.pmModel`（纯函数，`tests/` 在 vm 里加载）：LMSR 浮点（`costOf`、`pricesPpm`、`buyPoints`/`sellPoints` 向上/向下取整、`quoteOf`、`maxSharesForBudget`）；`slippageLimit`（买 ceil·1.02、卖 floor·0.98）、`netCostCap`（max(200, S//4)）；展示 `formatProb`、`outcomeLabels`、`questionText`、`closeText`；`curvePaths`；`applyTick`（只接受更新的 seq）；`holdingValue` |
| `mock.js` | `SS.mockFeatures.pm`：4 个确定性市场（今日：有色 5 档 open、两个传闻（一个 open、一个已被辟谣 +84）；昨日：分档已结算 −40）；本地成交（余额、持仓、成本、限额、滑点）按 04 §9.3 抛 `ApiError`；`nudge()` 模拟全服成交（只改价格） |
| `store.js` | `SS.store` 上的预测市场方法，mock 与 real 两套同名（`SS.assertSameKeys("pm")`）；共用 `onPredictions(fn)`（进程内广播，返回取消函数）。real 的 WS `/ws/prediction-markets` 由 `watchPredictions` 引用计数打开、最后一个页面离开时关闭；断线后 3 s 轮询 |
| `ui.js` | `SS.pmUi`：市场卡 `cardHtml`、结算卡 `settledCardHtml`、选项行 `optsHtml`、曲线 `curveHtml`、就地更新 `setOptPct` |
| `trade-panel.js` | `SS.pmTrade.mount(host, {onDone})`：买/卖两种方向（主按钮提交、次按钮切换）、`.stepper` 份数、300 ms 防抖报价、滑点保护提交、`PM_SLIPPAGE_EXCEEDED` 自动重报价；非 open 市场显示结果/停止交易 |
| `list-page.js` | `SS.pages.pmList`（`#/pm?status=open|ended`）：进行中（open + closed）/ 已结束（resolved + voided）分段，游标加载，WS `list` 重拉、`tick` 只替换一张卡 |
| `records-page.js` | `SS.pages.pmRecords`（`#/pm/records`）：我的结算记录，游标加载 |
| `detail-page.js` | `SS.pages.pmDetail`（`#/pm/:id`）：问题与关闭说明、选项行、开市以来的概率曲线、买卖面板；`tick` 就地改数字与曲线 path；离开时取消订阅与引用 |
| `play-card.js` | `SS.pmPlayCard.mount`：玩法页分区（进行中最多 2 张、最近一张已结算、“全部市场 ›”） |
| `index.js` | `SS.features.pm = { routes, init }`：路由（`/pm/records` 必须先于 `/pm/:id`）；挂 `play`（order 20） |

## 约定
- **持仓取值按 idx**：`PmMarketDetailOut.my.outcomes` 是稀疏列表（只含有过持仓的选项），必须用 `SS.pmModel.positionOf(my, i)`，不得按数组下标取；`my_shares`（列表项）是按选项补齐的整数组。
- **无挑战**：`/prediction-markets` 返回 `CHALLENGE_NOT_FOUND` 时，真实版列表返回空页（页面写“今日挑战开始后开市”），不当错误。
- **概率与积分只用中性色与 `--accent`**，不用 `--up/--down`（04 §10.1，08 §8 Q9）。`css/features/pm.css` 只用 tokens。
- **报价口径**：页面显示的“预计花费/回款”来自 `quotePredictionMarket`（真实版为服务端报价）；滑点保护与提交的 `max_cost_points` / `min_proceeds_points` 由 `model.slippageLimit` 按 04 §5.4 计算。mock 的 LMSR 只用于模拟，不作为权威数字。
- **关闭说明**：bucket 写“第 N 个交易日开盘前停止交易”（N = `question.to_day + 1`，04 §3.3 的 `close_tt = first_tt(to_day)`）；rumor 关闭时点保密，写“揭晓前停止交易”。画板的“第 k 轮开始时停止交易”未采用（市场按交易日而非回合关闭，见 04 §3.3）。
- **WS 生命周期**：只在列表页与详情页存活期间连接（`watchPredictions` / `unwatchPredictions` 引用计数）；详情页另有 `subscribePrediction(id)`（最多 20 个）。玩法页分区只拉一次，不连 WS。
- **真实模式降级**：接口 404/405/501 → `FEATURE_UNAVAILABLE`（本会话记入 `SS.api.missing`），页面显示“即将开放”；业务错误（`PM_NOT_FOUND`、`PM_NOT_OPEN`、`PM_SLIPPAGE_EXCEEDED`、`PM_POSITION_LIMIT` 等）原样交给页面，错误文案在 `js/lib/store.js` 与 `store.real.js` 的 `ERROR_TEXT`。
- **Idempotency-Key**：真实版每次提交新生成（`crypto.randomUUID`）。
- 文件内所有用户数据（问题、事件标题）经 `SS.html` 转义。

## mock
- 今日挑战（`TODAY_ID`）：m1 有色 5 档（open，持有 >5% 两份，成本 98）、m2 传闻（open，未揭晓）、m3 传闻（resolved，辟谣，持有 8 份，兑付 800，净投入 716，盈亏 +84）；昨日挑战（`DAY_ID`）：m4 分档（resolved，持有 1 份，盈亏 −40）。
- 买卖在内存里生效，刷新即重置；余额初始 1286。`nudge()` 每约 4 s 让两个 open 市场随机成交一次。

## 真实联调（已在 18104 后端上走通）
- 列表（进行中 / 已结束）、合约详情（选项、曲线、报价）、买入（份数、滑点上限、Idempotency-Key）后持仓与余额即时更新、卖出（份额不足时不报价）、记录页、玩法分区；外部账号成交经 WS `pm_tick` 就地改概率。
- WS 不可用（注入立即关闭的 WebSocket 桩）时退化为 3 s 轮询，外部成交约 6 s 内反映到详情页；WS 重连带退避，4401 跳登录。
- 390 / 375 / 430 无横向滚动，触控目标 ≥40px。
- 结算记录（`PmSettlementOut`）不含事件标题，传闻结算用通用问句“传闻合约：会被辟谣吗？”（后端字段限制，见 06 / 后端 schemas）。

## 未覆盖
- 04 §5.5 的 `PM_RATE_LIMITED`、`PM_LOCKED_AHEAD`、`PM_BUSY` 只在错误表中，mock 不会触发；真实版也未专门构造触发。
- 滑点（`PM_SLIPPAGE_EXCEEDED`）只在单测与 mock 中验证，真实联调未在界面上构造价格变动。
- 合约详情的“所属挑战第 k 轮”文案未显示（按交易日描述关闭时点）。
- 画板的“全服示例”、事件摘要、个股 K 线标记不在本步范围（08 Q11）。
- 真实 store 位于 `js/features/pm/store.js` 的 real 分支（与 mock 同文件，`SS.assertSameKeys` 对照），未放进 `js/lib/store.real.js`，与 `js/features/CLAUDE.md` 的功能约定一致。
