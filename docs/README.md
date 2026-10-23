# 文档

| 文档 | 内容 |
| --- | --- |
| [CONTRACT.md](CONTRACT.md) | 重构契约：API、错误码、领域规则、数据库约定。所有模块必须遵守 |
| [architecture.md](architecture.md) | 架构：前后端划分、后端分层、确定性行情与补帧、数据流 |
| [deployment.md](deployment.md) | 部署：docker compose、切换数据库、备份、升级、安全配置 |
| [adr/](adr/README.md) | 架构决策记录 |

面向使用者的入门说明见根目录的 [README.md](../README.md)（中文）与 [README_EN.md](../README_EN.md)（English）。

## 维护约定

- 修改契约（`CONTRACT.md`）前先开 ADR 或在 PR 中说明理由。
- 改动目录职责或部署方式时同步更新本目录文档。
- 文档中的命令必须能在仓库根目录直接复制执行。
