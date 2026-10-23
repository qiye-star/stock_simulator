# src（前端源码，给 agent）

入口 `main.js` 只做装配：样式 → i18n → 主题 → 步进按钮 → features。

## 边界与不变量
- 子目录职责见各自 CLAUDE.md；跨目录依赖方向：features → ui/api/state/i18n；ui 不依赖 features。
- `api/` 与 `ui/` 不得依赖 DOM 业务 id；DOM 只在 features 与 index.html 中出现。
- 全部 ES 模块，JSDoc 类型标注（jsconfig checkJs）。
- 测试与源码同目录，命名 `*.test.js`，由 vitest 运行（`npm test`）。

## 文件地图
- `main.js`：启动入口
- `api/` `state/` `i18n/` `ui/` `styles/` `features/`

## 常见任务
- 改启动顺序：只改 `main.js`，保持样式最先导入。
- 新增全局 UI 工具：放 `ui/`，纯函数优先，便于测试。
