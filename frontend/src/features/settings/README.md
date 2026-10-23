# 设置模块（settings）

设置面板（主题 / 行情刷新速度 / 语言 / 时间控制）与顶部主题切换按钮。

## 快速开始
登录后点击右上角 ⚙️ 打开设置。偏好会同步到服务端账号，换设备后保持一致。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)` |
| `controller.js` | 事件绑定与 `PATCH /me` 持久化 |
| `prefs.js` | 纯函数：差异计算、刷新速度解析 |
| `view.js` | 表单与按钮文本 |
| `prefs.test.js` | 单元测试 |

## 对外接口
- `savePreference(patch)`：增量写回 `/me`。
- `setTheme(theme)`：切换主题（本地 + 服务端）。
