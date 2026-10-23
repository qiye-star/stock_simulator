# src/ui（通用 UI 工具，给 agent）

## 边界与不变量
- 无业务逻辑、无 DOM 业务 id。纯函数优先（format、html 可直接单测）。
- `html.js`：`html\`\`` 默认转义；`raw()` 为唯一 opt-out。`dom.js` 的 `setHtml/fragment` 只接受 SafeHtml，所以不经模板的字符串无法写入 DOM。
- `format.js`：`formatMoney(cents, lang)` 只接受整数分；`formatPercent(ratio)` 入参为小数比例；`formatVolume(shares)` 为整数股数。阈值沿用 legacy（中文 万/亿，英文 K/M/B）。
- `notify.js`：`showNotification(message, type)`，type 为 info/success/warning/error，未知值回退 info；文本用 textContent。
- `modal.js`：仅切换 `.active` 类，不渲染内容。
- `theme.js`：增删 body 上的 `light-theme` / `festival-theme`，不清空其它类名。
- `numberStepper.js`：`initNumberStepper(root)` 返回解绑函数；按钮用原生 stepUp/stepDown 并派发 input/change。

## 文件地图
- html.js · dom.js · format.js · notify.js · modal.js · theme.js · numberStepper.js
- 对应测试：html.test.js · format.test.js

## 常见任务
- 新增格式化：在 format.js 增加函数并补 format.test.js。
- 新增通知类型：同时更新 `NOTIFY_TYPES` 与 `styles/components/notification-types.css`。
