# tests/integration/ — 接口集成测试（给 agent）

## 边界
- 只通过 HTTP（TestClient）与 ORM 查询验证行为，不 mock 数据库。
- 行情随机种子不可控：测试通过 `refresh_rate_ms=60000` 关闭挂钟补推（仅 v1；v2 存档由 `clock_speed` 决定，用回拨 `last_tick_at` 相对 now 触发补推），用 `app.state.session_factory` 设置 `clock_minute`、`last_tick_at`，或直接调用 `services.market.advance_ticks` 推进。

## 不变量
- 新接口必须有至少一个成功用例与一个失败用例（断言 `code`）。
- 断言错误体为 `{"code", "params"}`，不要断言 FastAPI 默认的 `detail`。
- 需要改库的场景用 `app.state.session_factory()` 直接操作。
- 每个文件一个资源；模块之间不互相 import，辅助函数各自定义。
- 他人存档访问必须断言 404 与 `SAVE_NOT_FOUND`。

## 文件地图
- `test_health.py` 存活/就绪。`test_errors.py` 错误契约。`test_auth.py` 认证。`test_me.py` 当前用户。
- `test_saves.py` 存档生命周期、归属、时钟、种子、成就目录。
- `test_market.py` 行情视图、补推、暂停、跨日、自选。
- `test_market_list_intraday.py` 行情列表分页/搜索/排序/自选过滤（含游标）与个股当日分时（逐 tick 对拍、跳过/午休/换日、降级）。
- `test_concurrent_rollover.py` 并发请求跨交易日补推（线程并发 + 确定性过期会话冲突）：无 500、K线/快照每日一行、与串行一致。
- `test_orders.py` 下单规则、T+1、幂等、分页、成就。
- `test_clock_v2.py` 时钟 v2 接口：创建与默认值、节奏档、墙钟补推、午休/收盘停留与撮合窗、收盘与次日换日、暂停、离线截断（300 交易 tick）、跳过表、收盘小结入口。
- `test_market_v2.py` v2 分时逐步精确重放（跨午休、收盘、换日）与墙钟补推和逐分钟推进的逐位等价。
- `test_day_summary.py` 收盘小结：当前日口径（成交/持仓）、涨跌家数与排序、过去日（candles + 快照）、v1 可用、他人 404。
- `test_clock_v2_debug_migration.py` v2 调试接口（time 只前进、reset-market 回到 570）与迁移（存量存档为 v1、子表数据不被级联删除）。
- `test_portfolio.py` 持仓与盈亏。
- `conftest.py`（本目录）每日挑战夹具：`challenge_app_factory`（按名字建独立的已迁移库，compact 调度、`CHALLENGE_MIN_ACCOUNT_AGE_HOURS=0`、`ENABLE_DEBUG_API=true`、固定 `CHALLENGE_SEED_KEY`）、`challenge_app`、`db`、`fake_clock`（monkeypatch `services.challenges.timeutil.now`）、`make_user`（账号创建时间设为很早）。
- `test_challenge_lifecycle.py` 挑战生成（`-k generate`）：master 字段、回合与时间线一致、幂等、日志不含 seed、作废、B 的 CardPolicy；compact 无调试开关与时段个数不符时 `create_app` 失败。
- `test_challenge_sync.py` 推进与镜像：v2 时钟开局 570、两人同刻行情一致、玩家永不超前且停顿段 paused、停顿期不推进、懒推进与逐秒推进的 payload/candles/outcomes 相同（两个独立库）、时钟操作 `CHALLENGE_UNSUPPORTED`、迟到者、停顿期可下单且结束后 `CHALLENGE_ENDED`、钩子各触发一次。
- `test_challenge_isolation.py` `test_no_direct_market_reads` 静态扫描（含自检）、`GET /saves` 不列挑战与 master、删除 409、导出 seed 为 null 且含 challenge 块、master 不可达、debug/auto_trade/情报拒绝、不计入存档上限。
- `test_challenge_isolation.py`（C11 增补）：静态扫描范围含 `services/day_summary.py` 与 `api/`；他人挑战存档经 HTTP 与 WS 均 404 `SAVE_NOT_FOUND`/4404；clock/debug/auto-trade 经 HTTP 返回 409 `CHALLENGE_UNSUPPORTED`；rumor-hints 409 `INTEL_UNAVAILABLE {reason:disabled}`；普通存档可建满 10 个（挑战存档不占额）。
- `test_challenge_secrecy.py`（C11）：running 阶段（快放段与停顿后）扫全部玩家可达 GET（响应文本不含 seed/盐/`commitment_input`，服务端专用键非空即违规；状态码只许 200/409），export `market_seed` 为 null；未到回合 `hold_at/event_id` 为 null、`rounds` 列表为空、作答 404、reveal 409；10 帧 WS 不泄露（中途拨到停顿）；生成与懒推进期间 `caplog` 不含秘密串。
- `test_ws.py` 末尾新增挑战存档用例（C10）：首帧 `challenge` 字段集与 `clock` 快放段规则、拨过停顿后 `paused`/`ms_per_minute=null`/`challenge` 变为 hold 且同相位不重推、跨 11:30 同一帧内顺序 tick → phase → challenge。既有用例未改动。
- `test_challenge_settle.py`（C6）：结算生命周期（到期前不结算、幂等、奖励账本恰一条、status 最后写）；`test_challenge_scoring_db.py`（C6）：同伴分、交易分、竞赛排名、日/周/总榜与 me，原始数据独立复算。
- `test_challenge_migration.py`：迁移 `f5aae30ea648` 在真实老库（`8ed22ae1e201`）上升降级，存量存档与子表保留。
- `test_challenge_d_contract.py`（C7）：03 §1.7 给 D 的契约函数边界与钩子调用。
- `test_challenge_runner.py`（C8）：`run_due` 幂等、两线程并发只生成/只结算一次、清理保留期（玩家存档先删、`save_id` 置空、再删 master）、`CHALLENGE_ENABLED=false` 空转、`/debug/challenges/{id}/shift` 推到结算、懒触发节流与失败吞没、CLI `show` 结算前不出 seed。
- `test_challenge_lifecycle.py` 的 HTTP 全流程（C9）：ensure → running → 报名 → 作答/修改/上限/截止 → 结算 → 排行/reveal 校验/复盘 → 账本一次性；另有作废后 reveal、列表游标、功能关闭 404。
- 挑战测试中服务层用例仍直接调用服务（C3–C7 的 sync/settle/isolation），HTTP 用例走 `TestClient`。

## 验证
`cd backend && uv run pytest tests/integration -q`（全量约 2 分钟，含每用例的 Alembic 迁移）
- `test_auto_trade.py` 条件单 CRUD、状态机、事件分页、run_auto_trade（触发/冷却/上限/失败码）。
- `test_legacy_import.py` 旧版导入（样例见 `../fixtures/`）、结构与一致性校验、审计。
- `test_debug.py` 调试开关与各动作。`test_ws.py` WebSocket 鉴权、首帧与增量、订阅/ping、推送事件，以及 `news` 帧（跨过发布 tick 时推送；关闭事件的存档不推）。
- `test_events.py` 事件行情（01 §12.2）：开关与 409 `EVENTS_DISABLED`、关闭时行情不进入 events 服务、v1/v2 漂移的逐位重放（含 drift 确实改变走势）、intraday 在事件开启后仍 exact、公开形态与保密（HIDDEN 键不出现）、快讯分页完整无重复、过滤与 422、产业链揭示 provider、`reveal_edge`/`rumor_hint` 服务层、event-marks、发布暂停钩子（停在发布 tick、墙钟不推进、续行不重复触发）、reset-market 调用 reset 钩子。`test_saves.py` 另含事件开关创建/PATCH 不变、事件存档导出 format_version=2 且 market_seed 为 null。
- `test_points.py` 积分账本服务：幂等与冲突、余额下限（POINTS_INSUFFICIENT 不改余额）、CHECK 兜底、两会话乐观锁下无丢失更新、`run_in_transaction` 重做、游标分页、删档 save_id 置空、删用户级联。
- `test_predictions.py` 预测卡接口：409 EVENTS_DISABLED、出卡暂停与公开题目白名单、作答校验 422、resume 行为、截止过期与 PREDICTION_CLOSED、结算入账（余额 = 200 + points，幂等）、称号解锁、日上限、mode=off 不出卡。v2 存档（`clock_rules=2`）。
- `test_intel.py` 情报卡：L1/L2 扣费与补差价、max_level、未知边 404 不扣费、余额不足 422、日限额 8、揭示按用户。
- `test_ws.py` 新增预测卡推送用例（opened → skip 后 expired）；`test_errors.py` 新增 6 个预测错误码的登记检查。
- 真实复盘（05 §8.2）：`replay_support.py` 为本组共用辅助（临时库迁移、把夹具关卡包放进 `REPLAY_PACKS_DIR`、登录与推进）；因 `--import-mode=importlib`，各模块以 `sys.path.insert` 引入它。`test_replay_levels.py`（导入幂等与版本不可变、包校验、列表与详情防剧透、退役关卡）、`test_replay_session.py`（建会话与隔离、逐阶段防剧透断言、截止与停止原因、结算后拒绝）、`test_replay_trading.py`（阶段成交价、T+1、停牌、封板、收盘可成交、名称口径、不支持功能与 WS 4409）、`test_replay_predictions.py`（作答校验、计分等于 `domain.scoring`、积分幂等、重开不入账、实名减半）、`test_replay_reveal.py`（揭示、与 NewsOut 同形、导出与删除）、`test_replay_supply_chain.py`（决策 16：复盘拒绝产业链与全部事件 / 情报接口，响应无真实代码；普通与事件存档不变）。

## 预测市场（模式 D）
- `test_prediction_markets.py` 物化与生命周期（回合过滤、时间表连跳、守恒式、幂等、作废退款、负 returned、事件指纹不符、规则集变化）。
- `test_prediction_trading.py` 报价与下单、幂等（含并发同键）、多线程打同一市场（PM_BUSY 或成功、seq 连续）、卖出不套利、卖超持仓、滑点、预算买入、单市场与单场额度、频率（第 13 笔）、关市、超前锁定（monkeypatch）、账号年龄、视图与分页、结算后查询、保密键名。
- `test_prediction_markets_api.py` HTTP 形状、201/200 重放、Idempotency-Key 缺失 422、extra 字段 422、结算与持仓接口、history/tape、调试守门与 sync/void。
- `test_prediction_markets_ws.py` WS 鉴权 4401、ping、watch/subscribe、pm_tick、未知市场 VALIDATION_ERROR、结算 pm_resolved。用例开启 `PM_BACKGROUND_ENABLED=true`（轮询 100 ms），WS 与 Hub 必须同一事件循环。
- 本目录夹具 `PM_BACKGROUND_ENABLED` 默认 false（`tests/conftest.py` 与 `challenge_settings_for`）。
