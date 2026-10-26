# mobile-prototype — 手机端网页（纯静态前端，已对接后端 /api）

## 边界
- 纯 HTML/CSS/原生 JS，无构建、无依赖、无 React。不要引入打包器或 npm 依赖。
- 默认连真实后端：浏览器只请求同源 `/api/v1/*`（REST + WebSocket），由 `dev-server.mjs`（开发）或 `deploy/nginx.conf.template`（生产）转发；`?mock=1` 或 file:// 回退到 `js/mock/data.js` 假数据。不要改 `frontend/` `backend/` `legacy/`。
- 认证按契约是 httpOnly Cookie 会话（`session`），前端不存 token；401 一律跳 `#/login`。
- 所有脚本是**经典脚本**（非 module），挂在全局 `window.SS` 上，以支持 `file://` 直接打开。加载顺序见 `index.html`，新增文件必须按依赖顺序插入。

## 不变量
- 颜色只能来自 `css/tokens.css` 变量。唯一强调色 `--accent`（青绿）；`--up`/`--down`（红涨绿跌）**只用于行情数据**（价格、涨跌幅、K 线、盈亏）。买/卖按钮不用红绿。
- 金额整数分（`*_cents`），展示一律走 `SS.fmt`；涨跌幅为基点 `change_bp`；自动交易百分比为 float。
- 字段名与 `backend/src/stocksim/schemas/*.py` 一致（行情 QuoteOut、持仓 HoldingOut、成交 TradeOut 用 `code`、自动交易事件用 `stock_code`）。原型私有字段以 `_` 开头。
- 拼 HTML 用 `SS.html` 模板（默认转义）；只有内部生成的 SVG 才用 `SS.raw`。
- 触控目标 ≥44px；适配 safe-area；动画必须在 `prefers-reduced-motion` 下降级（CSS 全局降级 + JS 用 `SS.reducedMotion()`）。
- 滚动容器是 `#view`（body 不滚动），抽屉/Toast 定位在 `.app` 内。

## 文件地图
| 路径 | 职责 |
| --- | --- |
| `index.html` | 外壳（`.app` > `#view` + `#dock`）与脚本加载顺序 |
| `css/` | tokens / base / components / pages 四层样式 |
| `dev-server.mjs` | 零依赖 Node 开发服务器：静态 + `/api`（含 WS）反代，默认 18765 → 后端 8000 |
| `deploy/` | 生产 nginx 模板（安全头/CSP、gzip、/healthz、/api 与 WS 反代） |
| `Dockerfile` `.dockerignore` | 手机版镜像（nginx-unprivileged；只打包 index.html、css/、js/ 的静态文件，不含 dev-server.mjs、deploy/、文档） |
| `js/lib/` | html 模板、格式化、`clock-model.js`（时钟归一化与交易状态文案，纯函数）、`api.js`（fetch 客户端+模式开关）、`store.js`（假数据 store）、`store.real.js`（真实 store，覆盖前者）、SVG 图表、hash 路由（含 query）、`slots.js`（玩法挂载点/守卫注册） |
| `js/mock/` | 确定性假数据 |
| `js/components/` | React Bits 复刻组件 + 交易状态栏 `trade-bar.js`、交易时间说明 `clock-help.js`、收盘小结 `close-summary.js`（v2 收盘层 + 昨日小结条）、占位卡 `soon-card.js`，以及抽屉/下单等通用组件 |
| `js/pages/` | 页面：行情、个股、持仓、我的、自动交易（二级页）、玩法 hub、快讯占位（`coming-soon.js`）、登录 |
| `tests/` | 前端纯函数测试（`node tests/run.mjs`，零依赖，不进镜像）：`clock-model.test.mjs`、`clock-v2.test.mjs`、`news-model.test.mjs`（快讯 / 传导 / 产业链纯函数）、`predict-math.test.mjs`、`predict-model.test.mjs`（预测卡计分与分布）、`pm-model.test.mjs`（⑧ 预测市场）、`challenge-model.test.mjs`（每日挑战的倒计时、按钮状态、排行与承诺校验）、`replay-model.test.mjs`（真实复盘的推进、截止、缩放、计分与可见性） |
| `js/features/` | 玩法功能（⑤ 起）：`pm/`（⑧）预测市场（玩法分区、列表、合约详情与买卖、结算记录，LMSR 纯函数）；`news/` 快讯 / 事件详情 / 产业链 / 行情快讯条 / 事件相关 / 个股相关事件；`predict/`（⑥）预测卡 / 结算 / 我的预测 / 积分 / 校准 / 情报卡 / 称号；`challenge/`（⑦）每日挑战 / 挑战页 / 排行榜 / 赛后复盘；`replay/`（⑨）真实复盘：选关、会话、揭示、玩法分区，见 `js/features/CLAUDE.md` |
| `css/features/` | 玩法样式（⑤ 起），与 `js/features/` 对应，只用 tokens：`news.css`、`predict.css`（⑥）、`challenge.css`（⑦）、`replay.css`（⑨）、`pm.css`（⑧） |
| `js/app.js` | 注册路由（先 features、再核心、最后占位）、挂载 Dock、真实模式启动流程（init → 登录/错误页）、401 跳转 |

## 常见任务
- 加页面：在 `js/pages/` 新建 `SS.pages.x = { tab, render(view, params) → cleanup }`，`index.html` 引入，`js/app.js` 注册路由。
- 加玩法功能（⑤ 起）：放 `js/features/<name>/`（`mock.js` `store.js` `*-page.js` `index.js`），`index.js` 里声明 `SS.features.<name> = { routes, init }`，行情/我的/玩法等挂载点用 `SS.slots.register` 注册；核心页面不改。
- 时钟相关文案只经 `SS.clockModel`（`js/lib/clock-model.js`）：字段改名只改 `normalize`；状态栏、说明弹层、收盘小结不得自行推导时段或倒计时（收盘小结倒计时用 `closeTimer`，下单被拒文案用 `untradableText`）。
- 加/改接口：在 `js/lib/store.real.js` 与 `store.js` 同名实现（两者方法签名必须一致；写操作真实版返回 Promise，页面一律 `await`）。
- 后端没有的数据：语言/主题设置（占位）。分时曲线走 `GET /market/{code}/intraday`（历史）+ WS（增量），漏 tick 时重拉而非插值；行情缓存 `state.byCode` 只含已加载的股票（自选、持仓/规则涉及、翻过的页、看过的详情），「全部」列表走 `GET /market?limit&cursor&q&sort&order`，不要假设它含全部 385 只（需要全量时用 `store.loadAllQuotes()`）。资产曲线走 `GET /saves/{id}/equity-curve`，当日盈亏用 portfolio 的 `prev_equity_cents/day_pnl_cents/day_pnl_bp`（`_today_pnl_cents` 为页面沿用别名）。
- 迁移到 React：类名与 React Bits 组件对应（`.spotlight-card` `.animated-list` `.dock` `.shiny-text` `.blur-text` `.aurora`）。

## 部署（方案 A）
- compose 服务 `mobile`（端口 `MOBILE_PORT` 默认 18001 → 容器 8080，`BACKEND_UPSTREAM=http://backend:8000`），对外域名 `https://m.a.com/`；网页版 `https://a.com/` 对应 `frontend`（18000）。两者共用同一 backend 与数据库，HTTPS 与域名分流在外层 nginx（`../deploy/host-nginx.example.conf`）。
- CSP 随模板下发：`script-src 'self'`（只能用外链脚本，**不要加内联 `<script>`/eval**）、`style-src 'self' 'unsafe-inline'`（允许 `style=""`）、`img-src 'self' data:`（favicon 为 data: SVG）、`connect-src 'self'`（只连同源 /api 与 WS；不要引入外部 CDN/字体/第三方接口，否则要先改 `deploy/nginx.conf.template`）。
- HTTPS 下后端须 `COOKIE_SECURE=true`；Cookie 不设 Domain，m.a.com 与 a.com 会话互相独立。
- 改 `deploy/nginx.conf.template` 后用 `docker compose up -d --build mobile` 并检查 `/healthz`、`/api/v1/healthz`、WS 101。

## 验证
预测卡（⑥）：`?mock=1` 约 10 秒后快讯 e48-6 出卡（行情截停）→ 作答 → 继续；真实后端需事件模式存档 + `POST /clock/skip`。
真实复盘（⑨）：`?mock=1` → 玩法 → 真实复盘分区 →（打开关卡抽屉）开始 → 推进四阶段（盘前不能买卖）→ 第 2 日盘前作答（未答不能推进）→ 开盘买入（当日买入不可卖，T+1）→ 提前结束 → 揭示；真实模式后端没有复盘接口时显示“即将开放”。
每日挑战（⑦）：`?mock=1` → 玩法 → 每日挑战卡（4 段回合条、倒计时）→ 参加 → 进入第 2 轮 → 选档位与板块排序 → 提交（“更新答案”）→ 排行榜（今日未结算自动切本周）→ 复盘 `#/challenge/0b7e6c1a-2d3f-4a5b-8c9d-0e1f2a3b4c4c/review` →“验证种子”显示 ✓；真实模式后端没有挑战接口时全部显示“即将开放”。真实后端（`CHALLENGE_SCHEDULE=compact ENABLE_DEBUG_API=true`，`/api/v1/debug/challenges/ensure` 与 `shift` 准备与快进）：快放段显示“快放中”不倒计时，挑战存档内无暂停/速度、状态栏覆盖。
预测市场（⑧）：`?mock=1` → 玩法 → 预测市场分区 → 合约详情 → 选项与份数 → 买入（报价与滑点保护）→ 卖出 → 市场记录；真实后端没有预测市场接口时分区与页面显示“即将开放”。概率与积分无红绿。
```bash
# 先起后端（见根 CLAUDE.md，端口 8000），再：
node mobile-prototype/dev-server.mjs        # http://localhost:18765/ ；BACKEND_URL/PORT/HOST 可覆盖
# 离线看样式：http://localhost:18765/?mock=1（?mock=0 关闭）或直接双击 index.html
# 纯函数测试（时钟模型等，不需要后端）
node mobile-prototype/tests/run.mjs
```
390×844 视口检查：登录 → 行情（先看交易时间说明弹层，首次进入自动弹一次） → 左滑买入 → 持仓 → 我的（自动交易入口、游戏速度） → 自动交易增删 → 成交记录；玩法 tab 的未上线分区显示“即将开放”；快讯（⑤）：事件模式存档显示过滤与分组，非事件存档显示“本存档未开启事件模式”；无横向滚动、控制台无报错（未登录时的 401 属预期）。

