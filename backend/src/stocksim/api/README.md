# api

HTTP 接口层，负责依赖注入与路由。路由统一挂在 `/api/v1` 下。

| 路径 | 内容 |
| --- | --- |
| `deps.py` | `get_current_user`、会话与配置依赖 |
| `routers/` | 各资源路由，见该目录 README |

预测卡 / 情报卡 / 积分路由：`routers/predictions.py`、`routers/intel.py`、`routers/points.py`（见 `CLAUDE.md`）。

预测市场（模式 D）：`routers/prediction_markets.py`（公开市场与个人接口、调试 void/sync）、`routers/pm_ws.py` 与 `pm_ws.py`（全服 WS 通道与 `PmHub` 轮询扇出，04 §8）。
