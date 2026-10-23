# docs/ — 给 agent 的说明

## 职责
架构、部署、契约与 ADR。这里是"为什么这样设计"的唯一来源，代码与文档冲突时以代码为准并修正文档。

## 边界与不变量
- `CONTRACT.md` 是跨模块契约，改动前必须确认所有 agent 的目录受影响范围。
- 修改技术选型或推翻既有决策：新增 `adr/NNNN-*.md`，并更新 `adr/README.md` 索引。
- 文档中的 API 路径、错误码、表名必须与 `CONTRACT.md` 及 `backend/src/stocksim/` 一致。
- 文档语言：中文撰写；`README_EN.md` 为根目录英文版，由根目录 README 派生。

## 文件地图
- `CONTRACT.md` 契约（只读，除非有明确变更需求）
- `architecture.md` 分层与数据流
- `deployment.md` compose 部署与运维
- `adr/` 决策记录，编号 0001 起
- `README.md` 本目录索引

## 常见任务
- 新增决策：复制 `adr/0001-*.md` 格式，编号递增，更新索引。
- 数据库或端口变化：同步 `deployment.md` 的表格与 `.env.example`。
- 新增 API：只在 `CONTRACT.md` 增补，不要在这里另起一份接口清单。

## 验证
- 文档中的命令在仓库根目录逐条执行一遍（如 `docker compose config -q`、`make help`）。
- 检查相对链接：`grep -o '](\.[^)]*' docs/*.md docs/adr/*.md`。
