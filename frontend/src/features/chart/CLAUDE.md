# features/chart（K 线与成交量，给 agent）

## 边界
- 只绘制 `#kline-canvas`、`#volume-canvas`，并处理 `#chart-zoom-in|out`、`#chart-reset`。
- 数据只来自 `../market/store.js` 的 `detail`（`history` 日 K、`price_cents` 现价）与 `selectedCode`。不发请求。

## 不变量
- HiDPI：绘制前 `setTransform(dpr,0,0,dpr,0,0)`，所有坐标用 CSS 像素，禁止用 `canvas.width/height` 参与布局。
- 视口数学全部在 `viewport.js`（纯函数），渲染与交互不得自行计算缩放/偏移。
- 缩放/平移的视口状态不写入 store；切换股票时重置为贴最新（`initialView()`）。
- 交互使用 Pointer Events（鼠标与触摸），canvas 设 `touch-action: none`；滚轮需 `passive:false`。
- 合并同一帧的重绘请求（`requestAnimationFrame`）。

## 文件地图
- `viewport.js` 视口与坐标数学（`viewport.test.js`）。
- `render.js` 绘制 K 线、十字线、框选、成交量（`prepareCanvas` 处理 DPR）。
- `interact.js` 滚轮、拖拽、双指缩放、右键/Shift 框选、悬停。
- `index.js` mount：订阅 store、按钮、ResizeObserver、语言切换重绘。

## 常见任务
- 调整缩放范围：改 `viewport.js` 的 MIN/MAX 常量并更新测试。
- 新增指标线：在 `render.js` 中用 `xOfIndex` / `yOfPrice` 映射，禁止硬编码像素。

## 验证
- `cd frontend && npx vitest run src/features/chart`
- `cd frontend && npm run build`
