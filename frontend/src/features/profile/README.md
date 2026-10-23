# 个人页模块（profile）

个人主页：账户信息、统计、成就墙（54 个成就，支持展开 / 收起），以及导出存档与存档切换入口。

## 快速开始
主界面点击导航「我的」。

## 目录
| 文件 | 说明 |
| --- | --- |
| `index.js` | `mount(ctx)` |
| `controller.js` | 数据加载、渲染、按钮绑定 |
| `view.js` | 成就卡片模板 |
| `viewModel.js` | 纯函数：成就合并、计数、统计 |
| `achievementsMeta.js` | 成就图标与等级（由 legacy 抽取） |
| `viewModel.test.js` | 单元测试 |

## 对外接口
- `renderProfile(doc)`：重新拉取并渲染个人页。
