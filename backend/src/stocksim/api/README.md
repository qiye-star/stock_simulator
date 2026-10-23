# api

HTTP 接口层，负责依赖注入与路由。路由统一挂在 `/api/v1` 下。

| 路径 | 内容 |
| --- | --- |
| `deps.py` | `get_current_user`、会话与配置依赖 |
| `routers/` | 各资源路由，见该目录 README |
