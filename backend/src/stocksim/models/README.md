# models 目录说明

SQLAlchemy 2.0 ORM 模型，定义数据库的 15 张表。导入 `stocksim.models` 即把全部表注册到 `Base.metadata`，供 Alembic 与测试使用。

## 文件
| 文件 | 表 |
| --- | --- |
| `account.py` | `users`、`sessions`、`legacy_imports` |
| `market.py` | `stocks`、`market_states`、`candles` |
| `save.py` | `saves`、`save_stats`、`save_sectors`、`save_achievements` |
| `trading.py` | `holdings`、`trades`、`watchlist_items` |
| `auto_trade.py` | `auto_trade_configs`、`auto_trade_events` |

## 设计要点
- **金额整数分**：列类型 `Money`（BigInteger），写入非 int 直接报错。
- **费率**：`Numeric(8,6)`，Python 侧为 `Decimal`。
- **时间**：`UTCDateTime`，统一 UTC 并带时区；sqlite 读回时补齐时区。
- **主键**：`Uuid`。1:1 的统计与行情快照表以 `save_id` 为主键。
- **乐观锁**：`saves.version`，每次 UPDATE 自动递增，冲突抛 `StaleDataError`。
- **级联**：外键均声明 `ON DELETE`。删除用户会级联删除其全部存档，sqlite 需开启 `foreign_keys`（引擎已设置）。

完整列规格见 [CLAUDE.md](CLAUDE.md)。
