# features/debug（调试面板，给 agent）

移植 legacy/game.js 812-824（隐藏入口）与 4450-4830（动作）。挂载根：`#debug-modal`。

## 边界
- 入口：在 `.profile-header`（任意位置，事件委托）连续点击 5 次，两次点击间隔 ≤ 2s。不移植 legacy 对该头部的右键禁用。
- 只写 `#debug-modal` 内节点；顶部提示与“取消解锁”列表为本模块创建的宿主（`#debug-notice-host`、`#debug-clear-host`）。
- 只调用 `POST /saves/{id}/debug/*` 与读取类端点；成功后经 `setCurrentSave` 回读存档。

## 请求体契约（已与后端 schemas/debug.py 核对）
- `debug/fund` `{ cash_cents }`（整数分，0 ~ 1e13）
- `debug/time` `{ minute_of_day }`（0-1439；前端由 hour*60+minute 换算）
- `debug/achievements` `{ action: 'unlock' | 'lock' | 'unlock_all' | 'clear_all', ids: [] }`（`ids` 最多 200 个；unlock/lock 配合 ids 使用）
- `debug/reset-market`、`debug/clear`：无请求体。
- 辅助读取：`GET /achievements/catalog`（AchievementDefOut 数组）、`GET /saves/{id}/achievements`（SaveAchievementOut 数组 `{achievement_id, unlocked_at}`）；存档钟点来自 `save.clock_minute`。

## 不变量
- `DEBUG_DISABLED`：置 `state.disabled`，面板顶部显示明确提示并禁用所有动作；本页面生命周期内不再发请求。
- 无存档时动作禁用并提示 `debug.noSave`。
- 金额输入：元，最多两位小数，转整数分；时间：整数 0-23 / 0-59。
- 文案统一 `i18n.t`；错误经 `errorI18nKey`。

## 文件地图
- `index.js` mount · `controller.js` 点击计数、动作、提示 · `view.js` 下拉/多选/提示模板
- `model.js` 点击状态机、时段判定、输入校验、成就选项（纯函数）· `model.test.js` `view.test.js`

## 常见任务
- 新增调试动作：`controller.js` 增加处理函数，`run()` 包裹；按钮 id 沿用 index.html。
- 调整时段判定：`model.js` 的 `isTradingMinute` / `timeStatus`（与 legacy 行号对照）。

## 验证
`cd frontend && npm run build && npx vitest run src/features/debug`
