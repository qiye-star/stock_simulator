# tests/fixtures

集成测试用的静态样例。

| 文件 | 内容 |
| --- | --- |
| `make_legacy_export.py` | 生成旧版导出样例（与 `legacy/crypto.js` 的 XOR+Base64 编码等价） |
| `legacy_sample.json` | 明文旧版存档（可直接作为 JSON 导入） |
| `legacy_export.txt` | 旧版导出文本（即游戏内“导出存档”得到的内容） |
| `replay/` | `replay_ingest` 的合成夹具（规格、FakeClient 响应、原始数据、golden 关卡包），见其 README |
