# src/i18n

双语（简体中文 / English）文案与语言切换。

```js
import { i18n, t } from './i18n.js';
i18n.init();                  // 读取偏好
i18n.applyToDOM();            // 刷新 data-i18n 节点
t('common.confirm');          // 翻译
t('notification.x', { n: 3 }); // 插值 {n}
```

- `locales/`：翻译资源，原版 `legacy/locales` 的 ES 模块版本，新增 `error.*`。
- `errors.js`：后端错误码到文案 key 的映射。
- `i18n.test.js`：key 对齐与错误码覆盖测试。
