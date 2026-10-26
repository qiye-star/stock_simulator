# tests/ingest

`stocksim.replay_ingest`（真实复盘离线数据管道）的测试，全部不联网。

| 文件 | 内容 |
| --- | --- |
| `conftest.py` | FakeClient、无等待的 Gateway、夹具副本、`spec_min`、`pack_min` |
| `test_rawstore.py` | 原子写、JSONL 追加与坏行、路径约定与安全 |
| `test_client.py` | 令牌桶限速、重试退避、熔断、`AkshareClient` 的参数映射与空结果处理 |
| `test_fetch.py` | 增量抓取、季度分片、失败隔离、归一化、CLI 退出码 |
| `test_collect.py` | 定时抓存（电报、个股新闻、调度、每日补抓），假时钟，不联网 |
| `test_limits.py` / `test_slots.py` / `test_redact.py` / `test_questions.py` / `test_events.py` | 构建器各模块的单元测试 |
| `test_spec.py` | 规格校验与窗口计算 |
| `test_build.py` | golden（逐字节）、复权锚定、除权连续、停牌补齐、事件归属、脱敏、构建失败 |
| `test_verify.py` | `verify` 对篡改包的检测 |
| `test_purity.py` | 依赖隔离 |

运行：`cd backend && uv run pytest tests/ingest -q`。更新 golden：`UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden`。
