# 持仓页（portfolio）

展示当前存档的资产摘要、持仓明细与成交记录，对应原版「持仓」标签页。

## 快速开始
- 进入任一存档后切到「持仓」标签即可看到数据；页面可见时每 3 秒自动刷新。
- 持仓行右键可打开菜单：去交易、去自动交易、查看行情详情。
- 成交记录默认显示最新一页，点击「加载更多」继续翻页。

## 目录
| 文件 | 作用 |
| --- | --- |
| `index.js` | 功能入口，导出 `mount`，由 `features/index.js` 自动发现 |
| `controller.js` | 拉取数据、轮询、分页、右键菜单与跨页跳转 |
| `view.js` | 行、页脚、菜单的 HTML 模板 |
| `model.js` | 盈亏与展示的纯函数（整数分计算） |
| `*.test.js` | 纯逻辑与转义的单元测试 |

## 接口
- `GET /api/v1/saves/{id}/portfolio`
- `GET /api/v1/saves/{id}/trades?cursor=`
- `GET /api/v1/stocks`（名称映射）
- 事件：派发 `stocksim:select-stock`，`detail = { code, target }`，供交易 / 自动交易 / 行情功能监听。
