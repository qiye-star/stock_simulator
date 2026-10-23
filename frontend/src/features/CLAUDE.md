# src/features（功能模块，给 agent）

## 约定（所有功能模块必须遵守）
- 目录 `features/<name>/`，入口 `index.js` 导出 `mount(ctx)`，返回可选的卸载函数。
- `view.js`：只负责渲染（返回 `html\`\`` 或更新已拥有的节点）。
- `controller.js`：事件与业务流程，调用 `api/endpoints.js`，状态放 `state/`。
- 模块只操作自己拥有的 DOM 根节点（id 写在 index.js 的常量里），不得修改他人节点。
- 禁止直接 innerHTML 拼接；只能用 `ui/html.js` 的 `html\`\`` 与 `ui/dom.js` 的 `setHtml`。
- 文案用 `i18n.t`，金额用整数分 + `formatMoney`。
- 在 `./index.js` 的 `FEATURES` 登记（懒加载 `import()`）。
- 原版参考：`legacy/game.js` 中对应行号（写在模块注释里）。

## 当前状态
- `FEATURES` 为空，尚无已移植功能；`index.js` 为注册表，不是功能本身。
