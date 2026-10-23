# features/settings（设置与主题，给 agent）

## 职责
设置面板（主题、行情刷新速度、语言）、主题切换按钮（`#theme-toggle`）、时间暂停/跳过。
偏好写回 `PATCH /me`（仅登录时）；未登录只改本地。
原版：`legacy/game.js` 4428-4447（主题）、709-730（设置事件）、1890-2004（时间控制）。

## 边界与不变量
- 主题：写入 `appStore.theme`，由 `main.js` 的订阅调用 `applyTheme`，本模块不直接改 body 类名。
- 语言：`i18n.setLanguage` 后，`onChange` 把 `lang` 写回 `/me`（与用户记录不同才发请求）。
- 刷新速度：选项 1000/3000/5000；合法范围 500~60000（`parseRefreshRate`）。行情模块应读取 `session.user.refresh_rate_ms`。
- 时间控制：`POST /saves/{id}/clock/pause|resume|skip`，暂停状态存于 `currentSave.paused`。
- 手续费、T+0、交易单位不在此处（属于存档创建，见 features/saves）。

## 文件地图
- `index.js` mount；`controller.js` 全部事件与持久化
- `prefs.js` 纯函数（diff、刷新速度解析、按钮文案 key）；`view.js` 表单与按钮文本

## 常见任务
- 新增偏好项：`MePatch` 字段在 `api/endpoints.js` 已有 JSDoc；在 `controller.js` 绑定 `savePreference`。

## 验证
- `cd frontend && npm run build && npx vitest run`
