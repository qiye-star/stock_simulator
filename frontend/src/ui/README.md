# src/ui

跨功能复用的界面工具。

| 文件 | 作用 |
| --- | --- |
| `html.js` | 默认转义的 `html` 模板标签，`raw()` 显式放行 |
| `dom.js` | `$` / `$$` 查询、`on` 绑定、`delegate` 委托、`setHtml` / `fragment` 安全写入 |
| `notify.js` | 顶部通知条 `showNotification(msg, type)` |
| `modal.js` | 弹窗打开 / 关闭 / 状态查询 |
| `format.js` | 金额（整数分）、百分比、成交量格式化 |
| `theme.js` | 主题切换（dark / light / festival） |
| `numberStepper.js` | 数字输入框的主题化步进按钮 |

示例：

```js
import { html } from './html.js';
import { setHtml } from './dom.js';
setHtml(container, html`<span>${userName}</span>`); // 自动转义
```
