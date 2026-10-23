# features/auth（认证与账户，给 agent）

## 职责
登录、注册、登出、注销账户、修改密码；启动时 `GET /me` 恢复会话；绑定主导航 `bindMainNav`（应用入口）。
原版：`legacy/game.js` 998-1245（登录/注册/登出/注销）、2424-2513（改密）。

## 边界与不变量
- 会话只靠服务端 httpOnly Cookie，前端不存 token。登录/注册成功即已登录，直接进入存档选择页。
- 校验规则与后端 `services/auth.py` 一致（用户名 2-20、字符集、保留名；密码 6-20）。改后端规则时同步 `validators.js`。
- 错误一律 `ApiError.code` -> `errorI18nKey` -> i18n；不直接显示后端文本。
- 只操作 index.html 中的认证节点（login-*、reg-*、change-password-*、logout-*、delete-account-btn、profile 账户按钮）。
- 登录页的 tab 选择限定在 `.auth-tabs` 内（自动交易页也有 `data-tab`）。
- 注销 / 登出使用 `window.prompt` / `confirm`（与 legacy 一致）。

## 文件地图
- `index.js` mount：绑定 + `bindMainNav` + `restoreSession`
- `controller.js` 全部流程；导出 `enterApp`、`resetToAuth`、`applyUserPreferences`、`messageForError`
- `view.js` DOM 辅助（tab、错误文字、清空表单）
- `validators.js` 纯校验，返回 i18n key（测试：`validators.test.js`）

## 常见任务
- 改校验规则：`validators.js` + `validators.test.js`，并确认 `auth.regError.*` 文案存在。
- 新增账户操作：在 `controller.js` 的 `initAuthController` 绑定，流程函数放在同文件。

## 验证
- `cd frontend && npm run build && npx vitest run`
