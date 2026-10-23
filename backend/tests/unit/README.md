# 单元测试（tests/unit）

覆盖领域层规则与静态数据的纯函数测试，运行快（秒级），不需要数据库。

```bash
cd backend
uv run pytest tests/unit -q
```

| 目录 | 内容 |
|---|---|
| `domain/` | 撮合、涨跌停、T+1、手续费、行情确定性、自动交易、成就、纯度守卫 |
| `data/` | 股票池与行业文件的完整性 |

更多约定见 [CLAUDE.md](CLAUDE.md)。
