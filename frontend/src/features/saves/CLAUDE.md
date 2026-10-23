# features/saves（存档选择与开局，给 agent）

## 职责
存档列表（`GET /saves`）、开局（`POST /saves`）、进入（`GET /saves/{id}`）、重命名（`PATCH`）、删除（`DELETE`）。
开局表单含初始资金、买/卖费率、T+0、交易单位（这些是存档创建参数，不在设置面板）。
原版：`legacy/game.js` 1248-1636。

## 边界与不变量
- 金额为整数分（`initial_fund_cents`、`cash_cents`）；费率以字符串 `"0.000300"` 传输，换算用整数（`percentToRateString`）。
- 费率输入为百分比（0.03 表示 0.03%），范围 0~1（与 legacy 一致）。
- 随机资金 50~199 万元；自定义 10~10000 万元，转分 = 万元 × 10^6。
- 存档名校验与 legacy 正则一致（`SAVE_NAME_PATTERN`），1-20 字符。
- 列表变化统一通过 `session.bumpSaves()` 驱动刷新；不要在别处直接改列表。
- 进入存档前必须 `GET /saves/{id}` 取最新数据，再 `setCurrentSave`。
- 列表用 `html\`\`` 渲染（`view.js`），存档名经转义。

## 文件地图
- `index.js` mount
- `controller.js` 列表、进入、重命名、删除、开局；导出 `refreshSaves`、`enterSave`
- `view.js` 存档卡片模板；`viewModel.js` 卡片数据（纯）；`validators.js` 纯校验与请求体构造

## 常见任务
- 开局新增参数：`validators.js` 的 `buildCreateSaveRequest` 与 `index.html` 表单、测试同步。
- 新增存档操作：在 `controller.js` 绑定，成功后 `bumpSaves()`。

## 验证
- `cd frontend && npm run build && npx vitest run`
