# 股市模拟器 · 手机端网页原型

深色、克制、数字优先的手机端网页，适配 375–430px 手机屏。纯静态（无构建），现已对接真实后端：所有请求走同源 `/api/v1`，行情用 WebSocket 实时推送（断线自动退化为轮询）。也保留假数据模式用于离线看样式。

## 快速开始

无需安装依赖，也不用构建。

```bash
# 1) 启动后端（端口 8000，详见 backend/README.md）
cd backend && uv run alembic upgrade head
uv run uvicorn --factory stocksim.main:create_app --host 0.0.0.0 --port 8000

# 2) 启动开发服务器：静态文件 + /api（含 WebSocket）反向代理
node mobile-prototype/dev-server.mjs
# 电脑：http://localhost:18765/   手机：http://<电脑IP>:18765/
# 可选环境变量：PORT=18765  HOST=0.0.0.0  BACKEND_URL=http://localhost:8000
```

首次打开进入登录页，可直接注册账号；没有存档时会自动创建「主存档」（100 万、每手 100 股、T+1）。会话是后端设置的 httpOnly Cookie，会话过期（401）会自动回到登录页。

**假数据模式**：在地址后加 `?mock=1`（会记在 localStorage，`?mock=0` 关闭），或直接双击 `index.html`（file:// 无后端，自动进入假数据模式）。

**生产部署**：`docker compose up -d --build mobile`（或整套 `docker compose up -d --build`），镜像见 `Dockerfile`，nginx 模板见 `deploy/nginx.conf.template`（静态 + `/api` 反代 + WebSocket 升级 + 安全响应头/CSP + gzip + `/healthz`）。默认监听宿主机 `MOBILE_PORT`（18001），对外域名 `https://m.a.com/`，网页版 `https://a.com/`（18000）；两者共用同一个后端与数据库，外层 HTTPS/域名分流见 `../deploy/host-nginx.example.conf`。HTTPS 下需在 `.env` 设 `COOKIE_SECURE=true`；两个域名的登录态相互独立（Cookie 不设 Domain），账号与存档共享。

**后端没有的部分**：语言/主题仍是占位。分时曲线由后端 `GET /saves/{id}/market/{code}/intraday` 提供当日历史，WebSocket 只追加增量（刷新页面不丢，也不再插值）。资产曲线与当日盈亏由后端提供（`GET /saves/{id}/equity-curve`、portfolio 的 `day_pnl_*`，换浏览器不丢）。

用桌面浏览器打开时，页面显示在居中的手机尺寸框里。也可以打开 DevTools 的设备模式（如 iPhone 14，390×844）查看。

## 页面

| 路由 | 页面 | 要点 |
| --- | --- | --- |
| `#/market` | 行情 / 自选 | 资产概览（数字滚动，可隐藏金额）；自选/全部切换、按涨幅排序、搜索（代码/名称）；「全部」走服务端分页，滚动到底自动加载更多；**左滑行情行出现「买入/卖出」**，直接弹出下单抽屉 |
| `#/stock/:code` | 个股详情 | 大字价格；分时/日 K 切换，按住图表显示十字线；五档盘口；我的持仓；底部固定「卖出/买入」 |
| `#/portfolio` | 持仓 | 总资产、资产曲线（7 日/30 日/全部）、仓位占比；持仓卡片带光晕，卡片内可直接「加仓/卖出」 |
| `#/auto` | 自动交易 | 运行/暂停/停止；规则卡片用一句话描述条件，带开关；新建/编辑规则在抽屉里完成 |
| `#/me` | 我的 | 账户与存档信息（可切换/新建存档）、交易统计、成交记录（可筛选、游标分页加载更多、查看明细）、设置（刷新频率、暂停行情、导出存档、退出登录可用） |

下单抽屉：可切换买入/卖出，支持市价或限价（价格按 0.01 步进，长按连续变化）。数量按每手 100 股步进，有 1/4、1/2、3/4、全仓快捷按钮。抽屉显示预估金额、手续费和可用资金，能实时校验资金不足、T+1 等情况。成交后显示结果，2.4 秒后自动关闭。抽屉可以下拉关闭，也能点遮罩或按 Esc 关闭。

## 目录

| 路径 | 说明 |
| --- | --- |
| `index.html` | 唯一入口 |
| `dev-server.mjs` | 零依赖开发服务器：静态文件 + `/api` 反代（含 WebSocket） |
| `deploy/` | 生产 nginx 模板 |
| `Dockerfile` | 手机版镜像（只含静态文件，不含 dev-server.mjs、文档） |
| `css/tokens.css` | 颜色、字号、间距、动效变量（唯一的颜色来源） |
| `css/base.css` `components.css` `pages.css` | 基础、组件、页面样式 |
| `js/lib/` | 工具：转义模板、金额格式化、API 客户端、store（真实/假数据两套）、SVG 图表、路由 |
| `js/mock/` | 假数据（`?mock=1` 时使用），字段与后端 schemas 一致 |
| `js/components/` | 复刻自 React Bits 的组件，以及抽屉、下单、左滑行 |
| `js/pages/` | 各页面 |

## 配色规则

- 背景分 3 层冷灰（`#0A0B0D` / `#111317` / `#181B20`），文字分 3 级白灰，边框用 6% 透明度的白色。
- 唯一的强调色是青绿 `#3DDBB0`，用于主按钮、选中态和光晕。
- 红涨（`#F6465D`）绿跌（`#2EBD85`）只用于行情数据。买卖按钮用强调色或中性色区分，不用红绿。

## React Bits 对照

| React Bits | 本原型 |
| --- | --- |
| CountUp | `js/components/count-up.js` → `SS.countUp` |
| SpotlightCard | `.spotlight-card`（`effects.js` + CSS） |
| AnimatedList | `.animated-list` / `SS.animatedList` |
| Dock | `js/components/dock.js` → `.dock` |
| ShinyText / BlurText | `.shiny-text` / `SS.blurText` |
| Aurora | `.aurora`（极淡强调色光晕） |

以上组件都用原生 JS/CSS 重新实现，参考的是 [reactbits.dev](https://www.reactbits.dev/)（DavidHDev/react-bits）的效果和参数，没有复制它的源码。
