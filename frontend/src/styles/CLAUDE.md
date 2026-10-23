# src/styles（样式，给 agent）

## 边界与不变量
- 源自 `legacy/styles.css`（3411 行）按行段切分，多个文件合起来与原文件内容一致（仅 base 与 themes 的 :root/body 顺序对调，二者无属性冲突）。
- `index.css` 的 `@import` 顺序即原文件的级联顺序，**不得随意调换**。
- `components/notification-types.css` 为新增（通知类型色），不影响默认外观。
- 颜色统一用 `themes.css` 中的 CSS 变量（`--bg-*`、`--text-*`、`--primary-color` 等），不要硬编码新主题色。
- 修改视觉时对照 legacy 截图比对，避免连带影响其它段。

## 文件地图
- `index.css` 总入口（由 main.js 引入）
- `base.css` 重置与 body；`themes.css` 变量与 light/festival 主题
- `responsive.css`、`responsive-tail.css` 媒体查询（原文件分段）
- `components/*.css` 各页面与组件段

## 常见任务
- 新增组件样式：新建 `components/<name>.css` 并在 index.css 合适位置 @import。
