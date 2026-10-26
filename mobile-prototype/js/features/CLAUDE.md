# js/features/ — 玩法功能（⑤ 起）

每个子目录是一个玩法功能，**核心页面只留挂载点**，功能不改 `js/pages/`、`js/app.js` 的结构。

## 约定
- 固定文件：`mock.js`（假数据，挂 `SS.mockFeatures.<name>`）、`store.js`（mock 与 real 两套同名方法，末尾 `SS.assertSameKeys`）、`model.js`（可选，纯函数，供 `tests/`）、`*-page.js`（`SS.pages.<x> = { tab, render }`）、`index.js`（`SS.features.<name> = { routes, init }`）。
- 加载顺序：`index.html` 里用 `<!-- feature:<name> -->` 注释包住该段，插在 `js/pages/*` 之后、`js/app.js` 之前；段内顺序 mock → model → store → 页面 → index。
- `app.js` 统一注册 `routes`，并在进入就绪态后只调用一次各 `init()`（注册挂载点、订阅 `ws:*`、`save`）。
- 挂载点与行情分段用注册表：`SS.slots.register(name, {id, order, mount|html})`、`SS.marketLists.register({value,label,order,visible,load,empty})`。同 id 重复注册覆盖。
- 功能状态放 `SS.store.state.<name>`，由本功能的 `store.js` 初始化；切换存档（`save` 事件）时清空。
- 真实模式：接口不存在（`HTTP_404/405/501`）时用本功能的 `guarded()` 转为 `FEATURE_UNAVAILABLE` 并记入 `SS.api.missing`，本会话不再请求，页面显示“即将开放”；业务错误（如 `EVENTS_DISABLED`、`EVENT_NOT_FOUND`）原样交给页面。
- 功能间通过 `SS.store.emitLocal("<feature>:<evt>", payload)` 广播，不直接相互调用；核心 WS 消息 `ws:<type>` 由核心透传。
- 颜色只用 tokens（样式放 `css/features/<name>.css`）；红绿只用于行情数据。拼 HTML 用 `SS.html`，用户可见数据全部转义。

## 目录
| 目录 | 功能 | 步骤 |
| --- | --- | --- |
| `news/` | 快讯、事件详情（传导回放）、产业链、行情快讯条、事件相关分段、个股相关事件、收盘小结“今天的大事” | ⑤ |
| `predict/` | 预测卡弹层、结算复盘、我的预测、积分与校准、情报卡、称号；快讯/事件/产业链/收盘小结/我的页的预测挂件 | ⑥ |
| `challenge/` | 每日挑战：玩法页挑战卡、挑战存档横幅、挑战页（回合作答复用预测卡组件）、排行榜、赛后复盘与种子校验 | ⑦ |
| `replay/` | 真实复盘：玩法页分区、选关（匿名开关）、会话（四阶段推进、当日消息、预测题复用预测卡、买卖）、揭示页；假数据两关，见目录 `CLAUDE.md` | ⑨ |
| `pm/` | 预测市场：玩法页分区、市场列表（进行中/已结束）、合约详情（选项、概率曲线、买卖面板、滑点保护）、结算记录；LMSR 纯函数与 mock 成交；全服 WS（列表/详情页存活期间） | ⑧ |

## 注意
- `js/features/*/model.js` 不得在加载时访问 `document`、`localStorage`、`SS.store`（`tests/run.mjs` 在 vm 里加载它）。
- 玩法页面的 `params.query` 来自 hash 的 `?`（见 `js/lib/router.js`），切换焦点等场景用 `SS.router.replace("/path?k=v")`（不带 `#`）。
