# 交易模块（trade）

行情页中的股票详情报价区（最新价、涨跌、涨跌停、买卖五档），以及买入 / 卖出表单。
表单支持代码查询、价格与数量步进、1/4、1/2、全仓快捷量，实时显示可用资金或可卖股数与预估金额（含手续费）。

## 快速开始
随前端加载。在行情页选中股票，点击“买入”或“卖出”即可跳转到交易页并带入代码。

## 目录
| 文件 | 说明 |
|---|---|
| `index.js` | 功能入口与快捷买卖 |
| `form.js` | 买卖表单 |
| `detailView.js` | 报价区渲染 |
| `controller.js` | 下单、偏离确认、错误提示 |
| `confirm.js` | 价格偏离确认弹窗 |
| `model.js` | 纯逻辑：金额、费用、校验、请求体 |

## 接口依赖
- `POST /saves/{id}/orders`：`{code, side, quantity, price_type, limit_price_cents?, confirm_deviation?}`
