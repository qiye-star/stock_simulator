# 存档模块（saves）

存档选择页：列表、开新局（资金 / 费率 / T+0 / 交易单位）、进入、重命名、删除。

## 快速开始
登录后自动进入存档选择页（由 `auth` 模块触发）。也可在个人页点击「切换存档」或「开启新局」。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)` |
| `controller.js` | 列表与开局流程、重命名与删除 |
| `view.js` | 存档卡片的 html 模板 |
| `viewModel.js` | 卡片数据构造（纯函数） |
| `validators.js` | 存档名校验、开局表单转请求体（纯函数） |
| `*.test.js` | 单元测试 |

## 对外接口
- `refreshSaves(doc)`：重新拉取并渲染列表。
- `enterSave(id, doc)`：进入存档（设置 `session.currentSave` 并切到主界面）。
- 依赖 `state/session.js` 的 `session`、`setCurrentSave`、`bumpSaves`、`showScreen`。
