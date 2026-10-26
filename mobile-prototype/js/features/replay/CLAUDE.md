# js/features/replay/ — 真实复盘（⑨ E）

对应 `docs/10.26-plan/05-真实复盘.md`（§1 玩家体验、§5.8 API、§7 手机端）与 `08-手机端.md` §5.9；画板 Replay / Play。只做手机端，不改 `frontend/` `backend/`。

## 文件
| 文件 | 职责 |
| --- | --- |
| `model.js` | `SS.replayModel`（纯函数，`tests/` 在 vm 里加载）：位置 `pos = day_idx*4 + 阶段序`、推进目标 `targetPos`、题目截止检查 `checkQuestions`、题目状态、价格缩放/还原 `scalePrice`/`unscalePrice`/`pickScalePpm`、RPS 与 NDCG 计分、方向题档位 `autoEdges`、可见性（`seenBar`、`quoteOf`、`candlesAt`、`eventsAt`、`questionOf`）、下单预览与封板、预测卡适配 `predictionCardOf` |
| `mock.js` | `SS.mockFeatures.replay`：两个虚构小关卡（`SPECS`），`replayPack(slug)` 确定性生成关卡包（真实价、别名与 `mask_scale_ppm`、日历、基准、事件、题目） |
| `store.js` | `SS.store` 的复盘方法（mock/real 同名，`SS.assertSameKeys` 对照）。mock 是内存会话引擎（下单、推进、计分、结算、揭示）；real 经 `guarded()`：404/405/501 → `FEATURE_UNAVAILABLE`，本会话不再请求 |
| `ui.js` | `SS.replayUi`：阶段条、股票切换、股票头（名称、代码、行业、现价与阶段涨跌）、K 线（`.chart` 结构 + 右侧虚线“未来”）、消息行、题目行、关卡卡、会话行 |
| `replay-order-sheet.js` | `SS.replayOrder.open`：下单抽屉，只按当前阶段价格市价成交，100 股步进，“1/4·1/2·3/4·全仓”，预估金额与手续费（只做预览） |
| `replay-list-page.js` | `SS.pages.replayList`（`#/replay`，二级页）：说明、进行中、关卡、已结算；关卡抽屉（匿名开关、开始）；`?level=<slug>` 直接打开抽屉 |
| `replay-session-page.js` | `SS.pages.replaySession`（`#/replay/:id`）：四阶段推进（主按钮 `next_phase`、次按钮“跳到下一天” `next_day`、“提前结束”两步确认）、股票切换、当日消息、预测题（抽屉作答）、买入与卖出 |
| `replay-reveal-page.js` | `SS.pages.replayReveal`（`#/replay/:id/reveal`）：积分与收益、股票真身与完整 K 线（游戏期底色）、事件影响、题目结果、资产曲线、讲解、“再玩一次” |
| `play-card.js` | `SS.replayCard.mount`：玩法页分区（进行中会话“继续”、前两关卡卡、“全部关卡”） |
| `index.js` | `SS.features.replay = { routes, init }`：三条路由；挂 `play`（order 30）；不订阅 WS |

## 约定
- **不切换当前存档**：所有方法显式带 `saveId`；复盘存档不进存档列表；不订阅 WS（复盘存档的 WS 为 4409，页面不连，因此没有重连）。关卡列表按 `next_cursor` 读完。
- **时间只经 `SS.replayModel`**：位置 `pos = day*4 + 阶段序`（盘前 0 / 开盘 1 / 收盘 2 / 盘后 3）。推进用 `targetPos` 与 `checkQuestions`；页面不自行推导阶段。`expected_tick` = 当前 `pos`，服务端 `stale` 时页面重拉。
- **成交**：只在开盘（按开盘价）与收盘（按收盘价）。盘前/盘后按钮禁用并说明原因（`blockedText`）。T+1、封板、停牌以服务端判定，页面的 disabled 只是预检。
- **匿名**：real 模式的价格与名称由服务端给出（别名 `990001…`、`股票 A…`）。页面不缩放价格；mock 按 `mask_scale_ppm` 生成，`scalePrice`/`unscalePrice` 供 mock 与单测使用。
- **预测题**：复用 `SS.predictionCard.render/bind/draftFor/buildAnswers/setBusy/showErr`，由 `predictionCardOf` 把 `ReplayQuestionOut` 适配成一张卡（题干取后端 `prompt`，`ReplayQuestionOut` 没有 `title`；`kicker` 为“第 N 天 · 预测题”，`skip=false`）。一张卡只含一道题，页面按题打开。只支持 5 档方向题与 `top_k=3` 的排序题。
- **主存档预测卡不打断复盘**：`js/features/predict/prediction-card.js` 的 `open_` 在 `#/replay*` 下跳过弹层（主存档与复盘互不相关），卡片仍由行情页顶部的“去作答”处理。
- **积分**：匿名 ×1.0，实名 ×0.5（取整），同一题只计一次；交易盈亏不发积分。提前结束时，已答未到结算点的题按真实结果计分，未答记 0 分。
- **错误**：`REPLAY_*` 文案在 `js/lib/store.js` 与 `store.real.js` 的 `ERROR_TEXT`。页面专门处理：`REPLAY_PREDICTION_PENDING`（toast 并打开该题）、`REPLAY_SESSION_SETTLED`（去揭示页）、`REPLAY_REVEAL_LOCKED`（回会话页）、`REPLAY_QUESTION_CLOSED`（关抽屉并刷新）。
- **颜色**：红绿只用于价格、涨跌、K 线、收益与超额；买入按钮与积分用 `--accent`；卖出不用红绿。
- **转义**：用户可见数据经 `SS.html`；K 线与曲线 SVG 由 `SS.chart` 生成后用 `SS.raw`。

## mock（假数据，仅用于界面验证）
- `stamp-duty-2023`：5 只股票、8 个交易日、4 日揭示、10 条事件、2 道题（方向题、排序题）。
- `supply-halt-2021`：3 只股票、6 个交易日、4 条事件、1 道方向题。
- 演示会话：`stamp-duty-2023` 进行中（第 3 日开盘，已持有 300 股，次日起可卖，q1 已跳过）。新建的会话在内存中，刷新即重置。
- 计分、收益、基准、超额、积分与服务端同口径；揭示里的事件影响按重要度给固定值，仅作展示。

## 未覆盖（待后端 / 其它步骤）
- 真实联调（`REPLAY_PACKS_DIR` 的 fixture-min）已走通：选关 → 开始 → 四阶段推进 → 开盘买入 → 次日题目截止 → 作答 → 停牌日卖出被拒 → 提前结束 → 揭示。后端无复盘接口（404/405/501）时仍降级为“即将开放”。
- 未做：玩家自选日期或个股（E6）、2 档 `binary` 题、情绪标注、行情页顶栏的复盘小入口（05 §1.1，08 §7 视为可选）、长按“下一日”（以“跳到下一天”按钮代替）。
- 题目 `top_k ≠ 3` 时预测卡无法作答（预测卡组件固定 3 个）。
