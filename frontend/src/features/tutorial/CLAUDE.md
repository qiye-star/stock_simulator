# features/tutorial（新手引导，给 agent）

## 职责
主界面首次进入（`tutorial_completed=false`）时显示 9 步引导浮层；完成或跳过后 `PATCH /me {tutorial_completed:true}`。
原版：`legacy/game.js` 4256-4425。

## 边界与不变量
- 每个用户在一次页面加载内只自动开始一次（`startedFor` 按 user.id）。
- 步骤切换到对应主页面通过 `showTab`（tab 名见 `state/session.js`）。
- 离开主界面只隐藏浮层，不标记完成。
- 高亮目标不存在或不可见时居中显示（`placeTooltip` 返回 centered）。
- 文案 `tutorial.step1..9`；浮层节点来自 index.html（`#tutorial-overlay` 等）。

## 文件地图
- `index.js` mount；`controller.js` 流程与持久化；`view.js` 浮层渲染
- `steps.js` 步骤表与定位（纯函数，测试：`steps.test.js`）

## 常见任务
- 增删步骤：改 `steps.js` 与两个 locale 的 `tutorial.stepN`。

## 验证
- `cd frontend && npm run build && npx vitest run`
