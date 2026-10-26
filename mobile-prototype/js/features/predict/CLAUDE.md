# js/features/predict/ — 预测卡 / 积分 / 情报卡 / 称号（⑥ B）

对应 `docs/10.26-plan/02-预测卡.md` §1、§3、§5、§7–§8、§10–§12 与 `08-手机端.md` §5.6；画板 Predict / Settle / Me / EventDetail。只在事件模式存档里出卡；其它存档的挂件隐藏。

## 文件
| 文件 | 职责 |
| --- | --- |
| `model.js` | `SS.predictModel`（纯函数，tests 加载）：题目标题、`revealDay`、tab 过滤、结算表 `settleRows`、`rankHits`、“为什么这样走” `whyBullets`、校准几何 `calibrationPoints`、`errorText`；计分镜像 `rpsScore / uniformRpsScore / ndcgScore / baselineScore / rdiv`（**仅 mock 用**，真实计分在后端） |
| `titles.js` | `SS.predictTitles`：11 个称号的名称、等级、条件说明（02 §8） |
| `mock.js` | `SS.mockFeatures.predict`：3 张卡（待答 c-open / 已结算 c-settled / 已过期 c-expired，含私有 `_truth` 真值）、积分、称号、设置、统计、流水、情报；`sim` 模拟后端：`open(eventId)`（e48-6 出卡并截停）、`answer`、`skip`、结算（30 秒后）、校验答案 |
| `store.js` | 两套同名方法（`SS.store`）：`ensureCards`、`listPredictions`、`loadPrediction`、`answerPrediction`、`skipPrediction`、`loadPredictionSettings`、`setPredictionMode`、`loadPoints`、`listLedger`、`loadPointStats`、`loadTitles`、`equipTitle`、`loadIntel`、`buyEdgeReveal`、`buyRumorHint`；共用 `predictEnabled`、`resetPredict`、`upsertCard`。real 经 `guarded()`（`HTTP_404/405/501` → `FEATURE_UNAVAILABLE`） |
| `prediction-card.js` | `SS.predictionCard`：弹层 `open/isOpen/close/refreshOverlay`、`render/bind`；草稿按卡保存；提交/不答；收起后交易状态栏 overlay “去作答” |
| `intel-sheet.js` | `SS.intelSheet.open({edgeId}|{eventId})`：产业链边 L1/L2（补差价）与传闻真假提示；购买后刷新产业链 |
| `calib-chart.js` | `SS.predictChart.calibration(bins, w, h)`：校准 SVG（只输出 class） |
| `settle-page.js` | `SS.pages.prediction`（`#/prediction/:id`）：结算复盘 |
| `predictions-page.js` | `SS.pages.predictions`（`#/predictions?status=open|pending|settled`）：我的预测列表与积分余额 |
| `me-widgets.js` | `SS.predictWidgets`：我的页挂件（称号墙、积分卡、校准卡、情报卡、预测记录行、预测卡模式） |
| `slot-widgets.js` | `SS.predictSlots`：快讯底行、事件详情（“用情报卡查看”/真假提示/“你的预测”）、产业链情报按钮、收盘小结“待结算” |
| `index.js` | `SS.features.predict = { routes, init }`：注册挂载点与守卫 `resume`，订阅 `ws:prediction` / `ws:title` / `save`，委托点击 `[data-intel-edge]`/`[data-intel-event]`，mock 出卡触发 |

## 约定
- 加载顺序（`index.html`）：`model → mock → titles → store → prediction-card → intel-sheet → calib-chart → settle-page → predictions-page → me-widgets → slot-widgets → index`。`mock.js` 加载时就计算初始结果，因此 `model.js` 必须先加载。
- 概率与积分只用 `--accent`；红绿只在涨跌幅（`.up/.down`）上。
- 作答截止由服务端判定；前端不做时钟推导。草稿只是内存态，不落 localStorage。
- 不替代后端计分：前端的 `rpsScore` 等只为 mock 结算与测试。
- 所有出卡/结算事件走 `ws:prediction`（op：opened / answered / expired / void / settled），与真实 WS 同形。
- 卡片渲染与交互可被其它玩法复用（⑦ 挑战回合）：`SS.predictionCard.render(card, draft, opts)`（`opts`：`kicker`、`note`、`submitLabel`、`skip:false`）、`bind(root, card, draft, st, handlers)`（`handlers.onSubmit(answers)` 替换默认的弹层提交；`st.root` 供 `setBusy`/`showErr`）、`initialDraft`、`draftFor`、`buildAnswers`。`aOf` 同时读 `answers`（预测卡）与 `my_answers`（挑战回合卡）。

## 降级与状态
- 真实模式接口缺失 → `FEATURE_UNAVAILABLE`：积分卡 / 校准卡显示“即将开放”，称号与预测记录行隐藏，情报卡隐藏。
- `EVENTS_DISABLED`（非事件存档）：情报卡、预测卡模式行、“你的预测”隐藏；列表页显示“本存档未开启事件模式”。
- `PREDICTION_CLOSED`：弹层关闭并刷新；`VALIDATION_ERROR`：弹层内提示。

## mock 与 real 差异
- mock：`?mock=1` 时快讯 e48-6（重大突发，有色）推送即出卡并 `setPaused(true)`；作答后约 30 秒结算并弹 “+N 积分”；称号按作答解锁。
- real：出卡、截停、结算、称号均由后端 WS 推送；`answer/skip` 的 `clock` 经 `SS.store.applyClock` 写回。

## 验证
- `node mobile-prototype/tests/run.mjs`（`predict-math.test.mjs`、`predict-model.test.mjs`）。
- `?mock=1`：等约 10 秒 → 弹卡（横幅、5 档、把握、排序 chips、底部按钮）→ 作答 → 行情继续；收起 → 状态栏“去作答”；结算 toast；我的页 / `#/predictions` / `#/prediction/c-settled`；产业链情报购买。
- 真实后端（事件模式存档，`POST /clock/skip` 数次出卡）：已联调弹卡、作答后行情继续、结算 toast、情报购买。
