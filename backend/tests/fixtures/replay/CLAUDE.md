# tests/fixtures/replay/ — 复盘管道夹具（给 agent）

## 边界
- **全部是合成数据**（代码 600001/300001/000001、名称“测试甲/乙/丙”），不放真实行情与新闻原文（版权）。
- `raw/`、`client/`、`spec_min.json` 必须由 `make_replay_fixture.py` 生成，不要手改；`pack_min.json` 是 golden，只能由测试更新。

## 不变量
- 日历 40 个交易日（含周末与 3 天长假），窗口 = 15 回看 + 6 游戏 + 4 揭示，第 0 日为日历下标 20。
- 覆盖：除权（停牌后首日）、停牌、开盘一字涨停、收盘封跌停、创业板 +15%、巨潮 4 种时刻与非交易日与例行公告、无数据日、新闻联播命中/不命中、手写事件（含 `hide_in_masked`）、cls 含 1 条重复与空标题、残留年份 `2019Q3`。
- `client/` 是 FakeClient 的响应（AKShare 原生列名、全部 40 日；无文件即空结果）；`raw/` 是抓取层按规格应写出的结果（`cls/` 除外，E5 产物）。`fetched_at` 固定 `2024-01-01T00:00:00Z`，`akshare_version` 固定 `9.9.9-fixture`。

## 文件地图
- `make_replay_fixture.py` 生成器（仅标准库，确定性） · `spec_min.json` 规格 · `client/` · `raw/` · `pack_min.json` golden

## 常见任务
- 重新生成夹具：`cd backend && python3 tests/fixtures/replay/make_replay_fixture.py`，再 `UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden`，检查 diff 后一并提交。

## 验证
`cd backend && uv run pytest tests/ingest -q`（含 `test_fixture_sync_with_generator`）
