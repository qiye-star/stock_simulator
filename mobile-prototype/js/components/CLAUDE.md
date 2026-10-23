# js/components/ — 可复用组件

| 文件 | 对应 React Bits | 导出 / 类名 |
| --- | --- | --- |
| `count-up.js` | CountUp | `SS.countUp(el, to, {format, duration, from})`，从上次的值滚动到新值 |
| `effects.js` | SpotlightCard / AnimatedList / BlurText（ShinyText、Aurora 只有 CSS） | `.spotlight-card`（全局委托）、`SS.animatedList(container)`、`SS.blurText(text)` |
| `dock.js` | Dock（触屏版） | `SS.dock.mount(el)` / `setActive(tab|null)` |
| `sheet.js` | — | `SS.sheet.open({title, render, onClose})`（支持拖拽关闭）、`SS.toast`、`SS.segmented`、`SS.stepper` |
| `swipe-row.js` | — | `SS.swipeRows(container, {onAction})`：左滑露出买入/卖出，`peek()` 用于首次提示 |
| `order-sheet.js` | Stepper 的思路（单页内分步） | `SS.orderSheet.open({code, side, quantity?})`；提交错误（submitErr）持续显示到改输入/切买卖/再次提交，校验提示随 tick 实时刷新 |

## 规则
- 效果全部用原生 JS + CSS 复刻，不引入 React 或 motion。类名与 React Bits 一致，方便以后迁移。
- 动画先判断 `SS.reducedMotion()`。触屏没有 hover，SpotlightCard 在按下时点亮约 0.9 秒。
- 抽屉内的拖拽会避开 input、select、button、.stepper、.seg，避免误关。
