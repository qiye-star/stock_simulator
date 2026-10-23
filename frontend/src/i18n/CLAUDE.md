# src/i18n（国际化，给 agent）

## 边界与不变量
- `i18n.js`：单例 `i18n`，`t(key, params)`、`setLanguage`、`onChange`、`applyToDOM`。语言偏好存 localStorage（key `stock_simulator_lang`，与原版一致）。
- `locales/zh-CN.js`、`locales/en-US.js`：扁平 key，**key 集合必须一致**（`i18n.test.js` 校验）。
- `errors.js`：ErrorCode -> `error.<CODE>`。ErrorCode 列表须与 `docs/CONTRACT.md` 一致（测试校验）。
- `data-i18n-html` 会写 innerHTML，只用于受控静态译文，不要传用户数据。

## 常见任务
- 加文案：两个 locale 同时加同名 key。
- 加错误码：`errors.js` 增加条目 + 两个 locale 加 `error.<CODE>`。
