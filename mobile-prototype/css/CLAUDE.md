# css/ — 样式（四层，按顺序加载）

| 文件 | 职责 |
| --- | --- |
| `tokens.css` | **唯一颜色来源**：背景 3 层、文字 3 级、边框、`--accent`、`--up/--down`、字号、间距、安全区、动效时长 |
| `base.css` | 重置、`.app` 外框（手机铺满 / 桌面居中手机框）、`#view` 滚动容器、按钮、`.num/.up/.down`、骨架屏、reduced-motion 全局降级 |
| `components.css` | 卡片、分段、步进器、开关、Dock、抽屉、Toast、React Bits 复刻效果、左滑行、空状态 |
| `pages.css` | 各页面布局（按页面分段注释） |

## 规则
- 不得写死色值（`rgba(0,0,0,…)` 阴影/遮罩除外），新颜色先加到 tokens。
- `--up/--down` 只能用于行情数据相关的类（`.up .down .pill--* .flash-*` 与图表）。
- 新增动画须在 `prefers-reduced-motion: reduce` 下可接受（base.css 已全局缩短时长；无限循环动画需单独关闭）。
- 触控元素最小 44px（`--tap`）。
