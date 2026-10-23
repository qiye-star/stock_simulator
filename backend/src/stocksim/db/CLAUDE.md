# db/ — 数据库基础设施（给 agent）

## 边界
- 只提供引擎、会话、列类型、命名约定。不写具体表（表在 `models/`）。不依赖 `services/`、`api/`（`get_db` 仅依赖 fastapi.Request）。

## 不变量
- `Base.metadata` 使用 `NAMING_CONVENTION`，约束名必须稳定，迁移依赖它。
- `Money` 只接受 `int`（分），拒绝 bool/float/Decimal。
- `UTCDateTime` 写入必须带时区；读回统一 UTC。
- `json_column_type()` 通用 JSON，postgresql 变体 JSONB；每列调用一次。
- sqlite 引擎必须经 `make_engine`（设置 WAL、busy_timeout=5000、foreign_keys=ON、synchronous=NORMAL）。
- 会话由 `app.state.session_factory` 提供，测试可替换；不要用全局单例。

## 文件地图
- `base.py` Base、NAMING_CONVENTION、`utcnow()`。
- `types.py` Money、UTCDateTime、json_column_type。
- `session.py` make_engine、make_session_factory、get_db。

## 验证
`uv run pytest tests/integration -q`（迁移与引擎都会被覆盖）。
