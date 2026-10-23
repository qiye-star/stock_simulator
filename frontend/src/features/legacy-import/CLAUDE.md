# features/legacy-import（旧版数据导入，给 agent）

## 职责
1. 已登录且 localStorage `stock_simulator_users` 存在时，在存档选择页显示横幅，一键上传。
2. 个人页「导入存档」按钮：选择 .txt 文件上传。
接口：`POST /import/legacy {content}`，content 为旧版原始文本（服务端校验 XOR 并挂到当前用户，忽略旧密码）。整包 localStorage `stock_simulator_users`（`{username: userData}` 用户映射）可直接上传，后端导入其中**全部用户的全部存档**（见 backend services/legacy_import.py `parse_legacy`）；单用户导出文本同样接受。
原版：`legacy/game.js` 4851-4935。

## 边界与不变量
- 上传前不解析内容；大小上限 5MB（`validateImportFile`）。
- 成功后：`bumpSaves()` 刷新列表，并在 localStorage 记录 `stock_simulator_legacy_import_done:<userId>` 以隐藏横幅。
- 关闭横幅仅本页面有效（内存标记）。
- 横幅插入在 `#save-select-screen .save-container` 内，位于 `#save-list` 之前，id `legacy-import-banner`。
- 不修改或删除 localStorage 中的旧数据。

## 文件地图
- `index.js` mount；`controller.js` 上传、横幅、文件选择；`view.js` 横幅模板
- `detect.js` 纯函数（读取、标记、大小校验、是否显示）；测试 `detect.test.js`

## 常见任务
- 调整横幅显示条件：改 `detect.js` 的 `shouldOfferBanner` 并补测试。

## 验证
- `cd frontend && npm run build && npx vitest run`
