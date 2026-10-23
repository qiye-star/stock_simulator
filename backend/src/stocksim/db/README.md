# db

数据库层：SQLAlchemy 基类、自定义列类型、引擎与会话。

| 文件 | 内容 |
| --- | --- |
| `base.py` | 声明式 `Base`、约束命名规则、`utcnow()` |
| `types.py` | `Money`（整数分）、`UTCDateTime`（UTC 时间）、`json_column_type()` |
| `session.py` | `make_engine(url)`（sqlite pragma）、`make_session_factory`、`get_db` |

切换数据库只需改 `DATABASE_URL`，支持 sqlite、postgresql+psycopg、mysql+pymysql。
