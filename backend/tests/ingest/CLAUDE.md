# tests/ingest/ — replay_ingest 测试（给 agent）

## 边界
- 只测 `stocksim.replay_ingest`；**全部不联网**，不 sleep（`RateLimiter`/`RetryPolicy` 注入假时钟与 sleep）。
- 数据只用 `tests/fixtures/replay/` 的合成夹具；不放真实行情与新闻原文。
- 测试模块之间不互相 import（`--import-mode=importlib` 下也无法 import `conftest`）；共享的只有 `conftest.py` 的夹具。

## 不变量
- golden：`test_build.py::test_golden_byte_for_byte` 逐字节比较 `fixtures/replay/pack_min.json`。构建器行为变更后用 `UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden` 更新，并人工检查 diff。
- `test_fetch.py::test_fetch_spec_reproduces_fixture_raw`：FakeClient（AKShare 原生列名）经 `fetch` 落盘后必须与夹具 `raw/` 一致（`cls/` 与 `em_news/` 由 `collect` 产生，不在这里比较）。
- `test_build.py::test_fixture_sync_with_generator`：夹具必须与 `make_replay_fixture.py` 同步。
- `test_purity.py`：除 `client.py` 外不得导入 akshare 等第三方；不得依赖 stocksim 其它子包；导入 build/verify/fetch/cli 不会加载 akshare、pandas、sqlalchemy、fastapi。
- `test_collect.py`：全部注入假时钟、假睡眠与 `LiveFake`（队列式响应），不 sleep、不联网；数据为合成行，不放真实快讯原文。

## 文件地图
- `conftest.py` FakeClient、`make_gateway`（无等待）、`raw_store`/`empty_store`（临时目录）、`spec_min`、会话级 `pack_min`
- `test_rawstore.py` 原子写、坏行、路径安全 · `test_client.py` 限速、重试 2/4/8s、熔断、`AkshareClient`（假 akshare 模块）
- `test_fetch.py` 增量、季度分片、空结果、失败隔离、CLI 退出码 · `test_collect.py` 定时抓存：电报去重与分文件、重点标记、缺口告警、个股新闻轮转与游标、调度节奏（120s/10s）、20:30 补抓与重启不重跑、补抓失败隔离与熔断、客户端映射、`collect --once` CLI
- `test_limits.py` 涨跌幅分段与 flags
- `test_slots.py` 时间归属表 · `test_redact.py` 脱敏 · `test_questions.py` 档位/答案/并列 · `test_events.py` 影响计算
- `test_spec.py` 规格校验与窗口 · `test_build.py` golden、复权、除权、停牌、事件、脱敏、构建失败、CLI
- `test_verify.py` 篡改包必须报错 · `test_purity.py` 隔离

## 验证
`cd backend && uv run pytest tests/ingest -q`
