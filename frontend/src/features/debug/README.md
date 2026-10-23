# 调试面板（debug）

开发与测试用的隐藏面板，可修改资金、设置时间、解锁或取消解锁成就、重置行情、清空本局。

## 快速开始
- 在「我的」页头部连续点击 5 次打开面板（两次点击间隔不超过 2 秒）。
- 服务端需设置 `ENABLE_DEBUG_API=true`。未开启时面板顶部会提示「调试功能未启用」，所有动作不可用。
- 需先进入一个存档，否则动作不可用。

## 目录
| 文件 | 作用 |
| --- | --- |
| `index.js` | 功能入口，导出 `mount` |
| `controller.js` | 隐藏入口、各调试动作、提示与禁用状态 |
| `view.js` | 成就下拉、多选列表与提示的 HTML 模板 |
| `model.js` | 点击计数、时段判定、输入校验（纯函数） |
| `*.test.js` | 单元测试 |

## 接口（仅 `ENABLE_DEBUG_API=true`）
- `POST /api/v1/saves/{id}/debug/fund | time | achievements | reset-market | clear`
