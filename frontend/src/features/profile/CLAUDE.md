# features/profile（个人页与成就墙，给 agent）

## 职责
个人页：用户名、注册时间、局数 / 交易数 / 成就进度、成就墙、导出存档（下载版本化 JSON，`stocksim-save` 格式，非旧版文本）、开局 / 切换存档按钮。
注意：SaveOut 不含 trade_count，「交易数」目前显示为 0，待后端在 SaveOut 暴露 save_stats.trade_count 后接入（已知缺口）。
数据：`GET /me`（session.user）、`GET /saves`、`GET /achievements/catalog`、`GET /saves/{id}/achievements`。
原版：`legacy/game.js` 3768-3864、4840-4849。

## 边界与不变量
- 名称与描述走 i18n `achievement.<id>.name/.desc`；图标与等级来自 `achievementsMeta.js`（从 legacy/achievements.js 抽取，54 条）。服务端 catalog 给出 level/icon 时以服务端为准。
- 隐藏成就未解锁时显示为锁定占位（`profile.hiddenName/hiddenDesc`），不泄露真实名称。
- 成就墙展开状态存 localStorage `achievements-expanded`（个人偏好，失败忽略）。
- 修改密码 / 退出 / 注销由 `features/auth` 绑定；「导入存档」由 `features/legacy-import` 绑定。
- 渲染只在 `screen=main-screen && tab=profile` 时发生。

## 文件地图
- `index.js` mount；`controller.js` 请求与绑定；`view.js` 成就卡片模板
- `viewModel.js` 纯函数（解锁 id 归一化、卡片合并、计数、统计）
- `achievementsMeta.js` 静态元数据（勿手改，若 legacy 变更则重新抽取）

## 常见任务
- 新增成就：先在 `legacy/achievements.js` 与 i18n 补 `achievement.<id>.*`，再重新生成 `achievementsMeta.js`。

## 验证
- `cd frontend && npm run build && npx vitest run`
