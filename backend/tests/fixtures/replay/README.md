# tests/fixtures/replay

`replay_ingest` 测试用的合成夹具，生成与更新方法见 `CLAUDE.md`。

| 路径 | 内容 |
| --- | --- |
| `make_replay_fixture.py` | 生成器（标准库，确定性输出） |
| `spec_min.json` | 关卡规格：3 只股票、15 回看 + 6 游戏 + 4 揭示日 |
| `client/` | FakeClient 的响应，AKShare 原生列名 |
| `raw/` | 抓取层应写出的原始数据（构建器的输入） |
| `pack_min.json` | 构建器的 golden 输出：`UPDATE_GOLDEN=1 uv run pytest tests/ingest -k golden` |
