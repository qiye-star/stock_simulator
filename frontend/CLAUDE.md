# frontend（给 agent 的工作说明）

Vite + 原生 ES 模块（无框架）。契约见 `../docs/CONTRACT.md`，原版 `../legacy/` 只读（对拍用）。

## 边界
- 只在 `frontend/` 内写文件。`Dockerfile`、`.dockerignore`、`nginx/` 由部署侧维护，不要改。
- 后端在 `../backend/`，API 变更以其 schemas / errors.py 为准，并同步 `src/api/endpoints.js`。
- `node_modules/`、`dist/` 不入库、不写文档。

## 不变量
- 金额一律整数分，字段名 `*_cents`；`formatMoney` 对非整数抛错。
- 禁止 `innerHTML` 拼接：用 `src/ui/html.js` 的 `html\`\`` 默认转义；`dom.js` 的 `setHtml/fragment` 只接受 SafeHtml。`raw()` 仅用于受控静态标记。
- i18n：zh-CN / en-US key 集合必须一致（`src/i18n/i18n.test.js` 校验）。新错误码：`src/i18n/errors.js` + 两个 locale 同时加 `error.<CODE>`。
- 样式顺序即级联顺序：`src/styles/index.css` 的 `@import` 顺序不可随意调换。
- 通知只用 `showNotification(msg, type)`，文本走 textContent。
- 功能模块只通过 `src/features/index.js` 的 `FEATURES` 登记，见 `src/features/CLAUDE.md`。

## 文件地图
- `index.html`：静态 DOM 骨架（复用 legacy，仅替换为 `/src/main.js` 模块入口）。所有 id/class/data-i18n 不可改名。
- `vite.config.js`：dev/preview 代理 `/api` 与 `/api/v1/ws`（ws:true）到 `localhost:8000`，可用 `VITE_BACKEND_URL` 覆盖。
- `jsconfig.json`：checkJs，编辑器类型检查。
- `src/main.js`：启动顺序 样式 → i18n → 主题 → 步进按钮 → features。
- `src/api/`：http（fetch + ApiError）、ws（重连）、endpoints（每个 REST 端点一个函数）。
- `src/state/store.js`：发布订阅 store，`appStore` 为全局状态。
- `src/ui/`：html/dom/notify/modal/format/theme/numberStepper。
- `src/i18n/`：i18n 核心、errors 映射、locales。
- `src/styles/`：由 legacy/styles.css 按段切分，见其 README。

## 常见任务
- 移植某功能：建 `src/features/<name>/`，实现 index.js(mount)、view.js、controller.js；在 `FEATURES` 登记。
- 新增接口：`src/api/endpoints.js` 加函数（JSDoc 标注类型），复用 `http.js`。
- 新增文案：zh-CN 与 en-US 同时加 key。

## 验证
- `cd frontend && npm run build`（必须通过）
- `cd frontend && npm test`（vitest，测试与源码同目录 `*.test.js`）
- Node 需 >=20.19；本机若用 Windows nvm，请用 WSL 内的 Linux node，否则 rollup/esbuild 原生包不匹配。
