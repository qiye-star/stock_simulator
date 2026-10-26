# services/replay — 真实复盘服务

模式 E（真实复盘）的后端服务：关卡包导入与列表、复盘会话（建、推进、作答、结算、揭示）、防剧透的行情与事件视图、预测计分与积分入账。

- 行情不走合成引擎：复盘存档的价格、K 线、分时、报价都来自关卡包，经 `state.py` 映射为与普通存档同形的行情状态，下单仍走 `trading.place_order`。
- 关卡包由离线管道（`stocksim.replay_ingest`）构建后进 git（`backend/replay/packs/`），启动时导入数据库。
- 详细职责、不变量与文件地图见 `CLAUDE.md`；接口契约见 `docs/CONTRACT.md` 的“真实复盘”一节；数据流见 `docs/architecture.md` 的“复盘数据流”。
