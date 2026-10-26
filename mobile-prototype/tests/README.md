# tests

前端纯函数的零依赖测试（Node 内置 `node:vm` 与 `node:assert`）。

```bash
node mobile-prototype/tests/run.mjs
```

- `run.mjs`：在 `vm` 上下文里加载 `js/lib/format.js`、`js/lib/clock-model.js` 等无 DOM 脚本，然后运行所有 `*.test.mjs`。
- `clock-model.test.mjs`：交易时钟的时段划分、倒计时与状态栏文案、v1 跳过规则（与后端一致）。
- `clock-v2.test.mjs`：v2 调度表与 skip 序列（07 §5.2 / §6.5）、收盘小结倒计时、下单不可交易文案。
- `news-model.test.mjs`：快讯合并与过滤、传导回放窗口与步骤、产业链视图、事件相关分段（`js/features/news/model.js`）。
- `predict-math.test.mjs`：预测卡的档位分布、argmax、把握范围、分档文案（`js/lib/predict-math.js`）。
- `predict-model.test.mjs`：预测卡计分镜像（RPS、均匀基准、基线分、NDCG，02 §5 示例）、结算表、为什么这样走、校准几何（`js/features/predict/model.js`）。
- `pm-model.test.mjs`：预测市场 LMSR 报价（04 §4.4 金值）、滑点与限额、文案、曲线与推送合并，以及 mock 成交的守恒。
- `replay-model.test.mjs`：真实复盘的阶段推进、题目截止、价格缩放、计分、档位、可见性与预测卡适配（`js/features/replay/model.js`、`mock.js`）。
- `challenge-model.test.mjs`：每日挑战的倒计时与阶段推导、主按钮状态、排行与成绩展示、承诺校验的输入格式（`js/features/challenge/model.js`），以及 mock 承诺哈希的独立校验。

本目录不进手机版镜像。
