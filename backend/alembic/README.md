# alembic

数据库迁移目录，使用 Alembic 管理 `models/` 对应的表结构。

| 路径 | 说明 |
| --- | --- |
| `env.py` | 从应用配置读取 `DATABASE_URL`，sqlite 批量模式，目标元数据为 `Base.metadata` |
| `script.py.mako` | 迁移模板 |
| `versions/` | 迁移脚本 |

常用命令（在 `backend/` 下执行）：

```bash
uv run alembic upgrade head        # 升级到最新
uv run alembic downgrade -1        # 回滚一步
uv run alembic revision --autogenerate -m "描述"   # 根据模型生成迁移
```

改动模型后必须生成并提交迁移。
