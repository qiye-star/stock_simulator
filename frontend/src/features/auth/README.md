# 认证模块（auth）

登录、注册、登出、注销账户、修改密码，以及启动时恢复会话。

## 快速开始
无需单独启动：`src/features/index.js` 自动发现并挂载本模块。后端需运行在 `localhost:8000`（见 `frontend/vite.config.js`）。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)`：绑定事件、主导航、恢复会话 |
| `controller.js` | 登录 / 注册 / 登出 / 注销 / 改密流程 |
| `view.js` | 认证页与弹窗的 DOM 辅助 |
| `validators.js` | 纯校验函数（返回 i18n key） |
| `validators.test.js` | 校验单元测试 |

## 对外接口
- `mount({ doc })`：返回卸载函数。
- `controller.js` 导出 `enterApp(user)`、`resetToAuth()`、`applyUserPreferences(user)`，供其它模块复用。
- 依赖 `state/session.js`：`setUser`、`showScreen`、`bindMainNav`。
