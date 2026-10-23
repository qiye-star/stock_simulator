# alembic/ — 数据库迁移（给 agent）

## 边界
- 只改 `env.py`、`script.py.mako` 与 `versions/`（迁移脚本由 autogenerate 生成，不手写风格）。
- `alembic.ini` 位于 backend 根目录，`sqlalchemy.url` 留空。

## 不变量
- 连接串来自 `stocksim.core.config.get_settings().DATABASE_URL`；测试通过 `config.attributes["sqlalchemy.url"]` 覆盖。
- 所有迁移 `render_as_batch=True`、`compare_type=True`。引擎通过 `stocksim.db.session.make_engine` 创建，保证 sqlite pragma 一致。
- 迁移文件已在 `script.py.mako` 中导入 `stocksim.db.types`（Money、UTCDateTime）与 `Text`（JSONB 渲染）。
- 迁移一经合入不得改写；修正用新迁移。目前仅有 initial 迁移（尚未发布，允许重新生成）。
- `alembic/versions/` 不需要 CLAUDE.md/README.md，本目录需要。

## 常见任务
- 生成：`DATABASE_URL=sqlite:///./data/dev.db uv run alembic revision --autogenerate -m "说明"`
- 升级/回滚：`uv run alembic upgrade head` / `uv run alembic downgrade -1`
- 漂移检查：`uv run alembic check`

## 验证
```
DATABASE_URL=sqlite:////tmp/mig.db uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
DATABASE_URL="postgresql+psycopg://u:p@h/db" uv run alembic upgrade head --sql   # 离线渲染，不需要服务器
```
