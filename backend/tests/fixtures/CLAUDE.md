# tests/fixtures/ — 测试样例数据（给 agent）

## 边界
- 只放测试输入，不放业务代码。`legacy_export.txt` 必须由生成器产出，不要手改。

## 不变量
- `legacy_sample.json` 是旧版（legacy）存档结构的明文样例；`legacy_export.txt` 为其 XOR(`stock-simulator-2024`)+Base64 导出文本。
- `test_legacy_import.py::test_fixture_is_in_sync_with_generator` 校验二者一致；改样例后重新运行生成器。
- 金额在样例中为“元”（legacy 口径）。

## 文件地图
- `make_legacy_export.py` 生成器（`build_sample()` 与 `encode_legacy()`，编码与 legacy/crypto.js 等价）。
- `legacy_sample.json` 明文样例（用户 legacy_bob，含 1 个存档：买入 100、卖出 50、一条自选、两个成就与一个无效成就 id）。
- `legacy_export.txt` 导出文本样例（导入接口的 `content`）。
- `replay/` 复盘管道的合成夹具（自带 CLAUDE.md，由 `replay/make_replay_fixture.py` 生成）。

## 常见任务
- 重新生成：`cd backend && uv run python tests/fixtures/make_legacy_export.py`，再跑 `uv run pytest tests/integration/test_legacy_import.py -q`。

## 验证
`cd backend && uv run pytest tests/integration/test_legacy_import.py tests/integration/test_debug.py -q`
