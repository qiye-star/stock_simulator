# 前端（frontend）

股市模拟器 v2 的前端工程：Vite + 原生 ES 模块，无框架。页面结构与样式沿用原版，逻辑按功能模块逐步从 `legacy/game.js` 移植。

## 快速开始

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 代理到 http://localhost:8000
npm test           # vitest 单元测试
npm run build      # 产物输出到 dist/
```

后端默认地址 `http://localhost:8000`，可用环境变量覆盖：`VITE_BACKEND_URL=http://127.0.0.1:8001 npm run dev`。

## 目录

| 路径 | 说明 |
| --- | --- |
| `index.html` | 页面骨架（来自原版，入口为 `src/main.js`） |
| `public/` | 静态资源，原样拷贝到产物根目录（如封面图） |
| `src/main.js` | 应用入口 |
| `src/api/` | 与后端通信：fetch 封装、WebSocket 客户端、类型化端点 |
| `src/state/` | 发布订阅状态容器 |
| `src/i18n/` | 双语文案、错误码映射 |
| `src/ui/` | 通用 UI 工具：转义模板、DOM、通知、弹窗、格式化、主题、步进按钮 |
| `src/styles/` | 样式，按区块切分自原版 `styles.css` |
| `src/features/` | 功能模块注册表与模块约定（见其 README） |

## 关键约定

- 金额用整数分（`*_cents`），展示时用 `formatMoney` 转换。
- 写 HTML 一律用 ``html`...` `` 模板（默认转义）；不要直接 `innerHTML` 拼接数据。
- 新增文案需 zh-CN 与 en-US 同步，测试会校验两者 key 一致。
- 样式导入顺序即级联顺序，修改 `src/styles/index.css` 时需谨慎。

## 接口

- REST：`/api/v1/*`，Cookie 会话（`credentials: 'same-origin'`），错误体 `{code, params}` 转为 `ApiError`。
- WebSocket：`/api/v1/ws/saves/{id}`，断线自动指数退避重连。

详见 `../docs/CONTRACT.md`。
