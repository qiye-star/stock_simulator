# src/i18n/locales（翻译资源，给 agent）

- `zh-CN.js` 与 `en-US.js` 各 default export 一个扁平对象，key 为 `模块.含义`。
- 两文件 key 集合必须完全一致；`i18n.test.js` 会失败并列出差异。
- 末尾 `error.*` 段为错误码文案，由 `../errors.js` 引用；新增码两边都要加。
- 不要在此写逻辑或 HTML 结构。
