# js/components/ — 可复用组件

| 文件 | 对应 React Bits | 导出 / 类名 |
| --- | --- | --- |
| `effects.js` | SpotlightCard / AnimatedList / BlurText（ShinyText、Aurora 只有 CSS） | `.spotlight-card`（全局委托）、`SS.animatedList(container)`、`SS.blurText(text)` |
| `dock.js` | Dock（触屏版，5 项：行情/快讯/持仓/玩法/我的） | `SS.dock.mount(el)` / `setActive(tab|null)`；等分列数读 `--dock-n` |
| `trade-bar.js` | — | `SS.tradeBar.mount(el, {variant: "full"\|"compact"})` 返回卸载函数；`SS.tradeBar.setOverlay(key, overlay\|null)`（预测卡/挑战等覆盖文案；overlay 写了 `action` 键即接管动作区，值为 `null` 时隐藏按钮，挑战存档运行中如此）。唯一数据源 `store.state.clock` → `SS.clockModel`；点开 `SS.clockHelp.open()`；暂停时“继续”、v1 非交易时段“跳到开盘”按钮 |
| `clock-help.js` | — | `SS.clockHelp.open({focus})` 交易时间说明底部弹层（时间线、三张规则卡、速度三档）；`maybeAutoOpen()` 首次进入弹一次，记忆键 `localStorage["ss.clockHelp"]` = 规则版本（v1/v2），localStorage 全部 try/catch |
| `close-summary.js` | — | `SS.closeSummary.watch()`（订阅 phase/tick/save，v2 收盘自动弹出，每交易日一次）、`open({tradingDay?})` / `close()`、`mountRecap(el)`（行情页“查看昨日小结 ›”条，记录键 `localStorage["ss.lastDay.<saveId>"]`）。数据 `store.loadDaySummary`；倒计时只经 `SS.clockModel.closeTimer`；“现在就开盘”= 恢复 + `skipClock()`，“先暂停”= `setPaused(true)`；z-index 30（高于 Dock、低于抽屉）；不响应遮罩点击 |
| `soon-card.js` | — | `SS.soonCardHtml({title, desc})` / `SS.soonCard(host, opts)`：“即将开放”占位卡（功能未上线或接口 404 时） |
| `sheet.js` | — | `SS.sheet.open({title, render, onClose})`（支持拖拽关闭）、`SS.toast`、`SS.segmented`、`SS.stepper` |
| `swipe-row.js` | — | `SS.swipeRows(container, {onAction})`：左滑露出买入/卖出，`peek()` 用于首次提示 |
| `order-sheet.js` | Stepper 的思路（单页内分步） | `SS.orderSheet.open({code, side, quantity?})`；提交错误（submitErr）持续显示到改输入/切买卖/再次提交，校验提示随 tick 实时刷新 |

## 规则
- 效果全部用原生 JS + CSS 复刻，不引入 React 或 motion。类名与 React Bits 一致，方便以后迁移。
- 动画先判断 `SS.reducedMotion()`。触屏没有 hover，SpotlightCard 在按下时点亮约 0.9 秒。
- 抽屉内的拖拽会避开 input、select、button、.stepper、.seg，避免误关。
