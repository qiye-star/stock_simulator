# src/features

功能模块目录。每个功能一个子目录，由注册表统一挂载。

## 功能模块约定

```
features/<name>/
  index.js        导出 mount(ctx)，返回可选的卸载函数
  view.js         渲染（html`` 模板）
  controller.js   事件处理与业务流程（调用 api/，读写 state/）
```

- 模块只操作自己拥有的 DOM 根节点。
- 不使用 innerHTML 拼接，统一用 `ui/html.js`。
- 在 `index.js`（本目录）的 `FEATURES` 中登记。

`index.js` 本身是注册表：当前没有登记任何模块。
