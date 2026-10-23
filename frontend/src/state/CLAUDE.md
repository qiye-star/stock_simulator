# src/state（状态容器，给 agent）

- `store.js`：`createStore(initial)` 返回 `{get, set, subscribe}`。`set` 浅合并，仅字段变化时通知；`get()` 返回的对象不要修改。
- `appStore`：全局状态（user、lang、theme、currentSaveId）。
- 不做持久化：偏好存储由调用方决定（语言在 i18n 中、主题以服务端 /me 为准）。
- 监听器异常会被捕获并打印，不影响其它监听器。

新增全局状态字段：在 `AppState` typedef 与 `INITIAL_APP_STATE` 中同时添加。

## session.js（会话与导航，features/auth、saves 等共用）
- `session` store keys：`user`、`currentSave`、`screen`、`tab`、`savesRev`。
- `showScreen(name)`（未登录访问受保护屏幕回退登录页）、`showTab(name)`（`position` 别名映射为 `portfolio`）、`bindMainNav(doc)`（由 features/auth 挂载时绑定一次）。
- `setUser` / `setCurrentSave` 同步 `appStore.user` / `currentSaveId`；存档列表变化用 `bumpSaves()`。
