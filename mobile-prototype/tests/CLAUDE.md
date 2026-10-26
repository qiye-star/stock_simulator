# tests/ — 前端纯函数测试（给 agent）

## 职责
零依赖的 Node 测试，只覆盖无 DOM 的纯逻辑（当前：`js/lib/clock-model.js`）。运行：`node mobile-prototype/tests/run.mjs`，失败退出码 1。

## 边界与不变量
- `run.mjs` 用 `node:vm` 在独立上下文里按需加载经典脚本，`ctx.window = ctx`，只挂 `window.SS`。
- 被加载的脚本**不得**在加载时访问 `document`、`localStorage`、`location`；需要时只能在函数调用里访问。新增可测文件要登记到 `run.mjs` 的 `SCRIPTS`（按依赖顺序）。
- 测试文件命名 `*.test.mjs`，默认导出 `(SS, assert, t) => void`，用 `t(name, fn)` 注册用例。
- 不引入任何 npm 依赖；`tests/` 不进 Docker 镜像（`Dockerfile` 只拷 `index.html css js`）。
- 测试期望值以 `backend/src/stocksim/domain/clock.py` 为准（如跳过规则），不要为了通过测试改实现去偏离后端。

## 文件地图
| 文件 | 职责 |
| --- | --- |
| `run.mjs` | 加载器与用例运行器；`SCRIPTS` 登记 `js/lib/format.js`、`js/lib/clock-model.js`、`js/features/news/model.js`、`js/lib/predict-math.js`、`js/features/predict/model.js`、`js/features/pm/model.js`、`js/features/pm/mock.js`、`js/features/challenge/model.js`、`js/features/challenge/mock.js`、`js/features/replay/model.js`、`js/features/replay/mock.js` |
| `clock-v2.test.mjs` | v2 调度表（`stepV2` 停留/tick/跳转）、`msUntilV2`、`skipTargetV2` 的 8 次跳过走完一个交易日、`closeTimer` 收盘小结倒计时（进度/暂停/完成/旧后端回退/server_time 偏差）、`untradableText`、`normalize` 的 v2 停留与暂停 |
| `clock-model.test.mjs` | 时段端点（v1 闭区间 / v2 半开区间）、`gap` 跨日、`progress`、格式化边界、速度档、`normalize` 的 v1 推算与 v2 字段优先、`view` 各情形文案与按钮、`skipTargetOf` 端点 |
| `predict-math.test.mjs` | `js/lib/predict-math.js`：档位+把握分布（02 §5.2 用例）、argmax、把握范围、分档文案 |
| `predict-model.test.mjs` | `js/features/predict/model.js`：RPS / 均匀基准 / 基线分 / NDCG 计分镜像（02 §5 示例）、结算表、为什么这样走、校准几何、tab 过滤 |
| `replay-model.test.mjs` | `js/features/replay/model.js` + `mock.js`：阶段位置与推进目标、题目截止（阻塞 / 跳过 / 停靠）、题目状态、价格缩放与还原、RPS 与 NDCG（与 B 的示例一致）、方向题档位、假日历、盘前 / 开盘 / 收盘的报价与可见性、事件可见性、预测题视图与预测卡适配、关卡包确定性 |
| `challenge-model.test.mjs` | `js/features/challenge/model.js`：倒计时（含 skew）与格式化、回合条映射、阶段文案与时间线（含快放段 `next_change_at = null` 的“快放中”/“最后一段”/“最迟 HH:mm 结算”）、刷新节流 `refreshDue`、挑战主按钮状态机（08 §5.7 表）、排行行（日榜/周榜/我的）、成绩展示、作答与结果摘要、群体均值、承诺原文解析与一致性；用 `node:crypto` 校验 `mock.js` 的承诺哈希 |
| `pm-model.test.mjs` | `js/features/pm/model.js`：LMSR 报价与 04 §4.4 金值（分档 1/5/10 份、传闻 5/10/20 份、往返不套利）、概率和为 1e6、拆单、预算反求、滑点与净投入上限、文案与关闭说明、曲线 path、推送合并；mock 成交的余额/持仓守恒与 04 §9.3 错误码（需要 `pm/mock.js`，`run.mjs` 已登记） |
| `news-model.test.mjs` | `js/features/news/model.js`：合并去重、过滤、按日分组、传导窗口与步骤（按日截止）、产业链视图、揭示文案、搜索与默认焦点、快讯条与收盘大事、事件相关分段（事发/传导）、深链筛选参数（`filterFromQuery`）、K 线标记对齐（`klineMarks`）与图例、行业成分股（`constituents`） |

## 验证
```bash
node mobile-prototype/tests/run.mjs
```
