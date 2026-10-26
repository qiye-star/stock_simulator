# services/ — 业务服务（给 agent）

## 边界
- 编排数据库读写与业务规则，抛 `AppError`。不依赖 FastAPI 对象（不接收 Request/Response）。
- 撮合、涨跌停、T+1、成就判定等纯计算在 `domain/`，服务层只组装输入并调用。
- 存档级入口统一经 `saves.open_save(db, user, id)`：归属校验（他人存档 → SAVE_NOT_FOUND）+ `market.advance_to_now`。

## 不变量
- 金额整数分；费率以 Decimal 存储并量化到 6 位，对外输出去掉尾零的字符串。
- 写操作在服务内 `commit`；失败 `rollback` 并转换为 AppError。
- 行情：`market_states.payload` 为 `{code: [9 项]}` + 保留键 `_meta`（trading_tick、as_of；v2 另有 `rules:2`，decode 时与 `saves.clock_rules` 不一致抛 RuntimeError）。history 不落 payload；收盘日 K 在交易日切换时追加到 candles；当日 K 由状态派生。
- 时钟规则只在服务层分支一次：`market.clock_ctx(db, save)` 取节奏参数，`timebase(save.clock_rules)` 取交易日 tick 数，`save.clock_rules` 传给 `advance`/`TradeSettings`/`compute_stats`。**禁止直接写 `save.clock_minute`**（v2 对齐不变量 `tt % 242 == v2_expected_offset(m)` 依赖此约束；`_run_ticks` 检查并告警）。
- 推进只在 `market.py` 的 `_run_ticks`（返回推进的分钟数，非交易分钟不调用 advance）中发生。`advance_to_now` 按 refresh_rate 补推（v1，上限 TICK_CATCHUP_MAX，暂停不推进）；v2 调用 `domain.clock.plan_catchup_v2` 按锚点与停留时长推演（11:30 停 5 s 跳 12:59，15:00 停 15 s 跳次日 9:29），锚点 `last_tick_at` 置为计划的到期时刻（截断时置为 now）。`advance_ticks(db, save, n)` 立即推进（跳过、调试），不看暂停。
- 乐观锁：`saves.version`。推进/下单冲突（StaleDataError）→ 回滚、刷新存档、重算。跨交易日并发补推时，收盘 candles / equity_snapshots 撞唯一约束（IntegrityError）同样由 `market._retrying` 回滚重算（重读后 last_tick_at 已被他人推进，通常无事可做）；不要改成 insert-or-ignore，否则会带着过期 payload 提交。
- 下单 `trading.place_order(...) -> Trade` 是手动与自动交易共用入口，签名固定；`place_order_detailed` 额外返回新解锁成就与幂等回放标记。
- 成交快照：trades 保存 prev_close、fund_before、tick、trading_day、clock_minute；统计只读快照。
- 每个存档最多 10 个（`MAX_SAVES_PER_USER`）。

## 文件地图
- `stocks.py` 股票池静态数据（data/*.json）与 stocks 表查询；`stock_pool()` 顺序即 stock_idx。
- `seed.py` 股票表幂等种子；`seed_on_startup` 由 main 的 lifespan 调用（失败只记日志）。
- `market.py` 行情编解码、advance_to_now / advance_ticks、`clock_view`（ClockOut 与 WS clock 同源，含 phase / next_event.at / next_tick_at / fast_forward_at / server_time）、暂停/继续/跳过（v2 跳过表见 domain）、新存档初始化。`market_overview` 支持 limit/cursor/q/sort/order/watchlisted（无参=全部，键集游标，全序为 (主键, 代码)）；`intraday` 不落库，由当日开盘价 + save.market_seed + 全局 tick 用 `domain.advance`（单只股票状态）逐 tick 重放，并校验终点与持久化价格/量一致，否则 `exact=false` 退化。
- `trading.py` 下单（place_order / place_order_detailed）、持仓同步、统计快照、成交分页、幂等键。
- `portfolio.py` 资产与持仓估值（可卖股数来自当日成交）。
- `equity.py` 收盘权益快照（`record_close_snapshot` 在 `market._run_ticks` 交易日切换时幂等 upsert）与 `equity_curve`（初始点+快照+实时点）。portfolio 的当日盈亏由当日成交倒推昨收权益。
- `achievements.py` 成就目录、已解锁列表、成交后判定落库（record_unlocks）。
- `saves.py` 存档 CRUD（`create_save(..., clock_rules=DEFAULT_CLOCK_RULES)`：v2 固定开局 570，v1 随机开局）、导出（JSON，save 节含 `clock_rules`）、自选增删、`open_save`。
- `day_summary.py` 收盘小结：当前日用实时行情与 portfolio 口径，过去的日用 candles 与 equity_snapshots（07 §1.4）。
- `legacy_import.py` 旧版导入固定 v1（v2 只在显式请求时启用），并显式关闭事件模式（`events_enabled=False, events_ruleset=0`）。
- `events.py` 事件行情服务（01 §1、§6、§8）：规则集缓存 `ruleset(version, clock_rules)`、`drift_for`（行情推进的漂移，关闭时空映射）、`news_for_tick`（钩子上下文）、`clock_of`（快讯展示的分钟倒推）、`news_list` / `events_list` / `event_detail` / `event_marks` / `supply_chain`、`ws_news`、`reveal_edge` / `rumor_hint` / `industry_change_bp` / `events_for_days`。所有公开函数先检查 `save.events_enabled`（否则 409 `EVENTS_DISABLED`），`supply_chain` 例外（静态结构，关闭同样返回；复盘存档经 `reject_replay` 拒绝，决策 16）。
- `event_hooks.py` 事件扩展点：发布暂停钩子（`_run_ticks` 的推进事务内运行，不得 commit，需幂等）、reset 钩子（`debug.reset_market` 换 seed 前）、揭示 provider（默认全部隐藏）。已由 `predictions.register_hooks()`（发布 + reset）与 `intel.register_hooks()`（揭示）在 `create_app` 中注册。
- `points.py` 积分账本（02 §1.1）：`open_account`（welcome 200，seq=1）、`credit/debit`（幂等、余额不得为负、乐观锁）、`find_entry`、`balance`、`ledger_page`、`totals_by_user`、`sum_since`、`count_debits_since`；`REASONS` 登记来源。**都不 commit**，`LedgerConflict` 为编程错误。
- `tx.py` `run_in_transaction(db, fn, *, refresh, attempts)`：执行后 commit；乐观锁/唯一约束冲突回滚、刷新后重做；`AppError` 回滚上抛。
- `predictions.py` 预测卡（02 §3、§10）：`CardPolicy` 与 `register_card_policy`（C/E 扩展点）、`on_publish`（发布钩子：重大事件第一条快讯 tick 出卡，返回 True 截停）、`on_reset`（未结算卡 void，删传闻提示）、`register_hooks()`（main 调用）、`answer_card` / `skip_card`（作答与不答，截止惰性过期，`resume` 时无其它未截止 open 卡才恢复行情）、`settle_due`（自己 commit，幂等：逐题结算、全部结算后 answered→settled 入账，`prediction:{card_id}` 幂等键，UTC 日上限 `PREDICTION_DAILY_POINTS_CAP`，超出 `points_capped`）、`structure_for(events_ruleset)`（缓存）、`change_bp_for`（方向题真值口径）、`answers_for_event`（C/D 用）、`stats`。所有交易日换算经 `timebase(save.clock_rules)`。
- `intel.py` 情报卡（02 §7）：边 L1 100、L2 200（已有 L1 补 100）、传闻提示 80；`buy_edge_reveal`、`buy_rumor_hint`、`state`；日限额 8（数 `intel_card` 扣账）；`reveal_levels_for_save`（揭示 provider，`register_hooks()` 注册）。
- `titles.py` 用户级称号（02 §8）：`user_stats`（从预测答案取数）、`evaluate_for_user`（新解锁落 `user_titles`）、`list_titles`、`equip`（未解锁 409，未知 id 422）。
- `events.py` 新增 `event_out(db, save, event_id, lang, *, at_tt=None)`（01 §1.10 ③，预测卡的事件简要形态）。
- `auth.py` 账号与会话（既有）。

## 验证
`cd backend && uv run pytest tests/integration/test_predictions.py tests/integration/test_intel.py tests/integration/test_points.py -q`
`cd backend && uv run pytest tests/integration/test_saves.py tests/integration/test_market.py tests/integration/test_orders.py tests/integration/test_portfolio.py -q`

### 自动交易 / 旧版导入 / 调试（auto_trade.py、legacy_import.py、debug.py）
- `auto_trade.run_auto_trade(db, save) -> list[Trade]`：每个刷新周期由 ws 循环在 advance 之后调用。决策用 `domain.auto_trade`（should_trigger / cooldown_ticks），下单只走 `trading.place_order(source="auto", confirm_deviation=True, auto_config_id=…)`。
- 运行时计数从 `auto_trade_events` 推导（每 key=code-direction 的最近尝试 tick、成功次数；全局成功数）。`reset` 清事件即清计数；`stop` 不清（与 legacy 不同，见下）。事件 `message` 列存错误码（成功为空串），API 以 `reason_code` 输出。
- 止损/止盈列为 `*_pct100`：按持仓成本百分比换算为分后交 domain 判断（legacy 为金额，此处以模型为准）。
- `legacy_import.decode_content`：base64→UTF-8→逐字符 XOR（key `stock-simulator-2024`），或明文 JSON；`parse_legacy` 严格校验（`schemas/legacy.py`），返回全部待导入存档：接受单用户 `{username, saves}`，也接受整包用户映射 `{username: userObj}`（localStorage `stock_simulator_users`，各用户存档合并导入）。旧成交 `trading_day=-1`、`tick=0`，不影响当日 T+1；旧记录手续费由金额反推，不自洽则 `record_mismatch`。密码哈希与用户级偏好忽略。
- `debug.py`：资金/时钟/成就/重置行情/清空；路由层以 `ENABLE_DEBUG_API` 守门。

## 每日挑战（模式 C，C3–C5）
- 行情来源：`market.market_key(save) = save.market_source_id or save.id`。**读 `market_states` / `candles` 一律经它**（A、B、day_summary、ws、auto_trade 已替换）。`tests/integration/test_challenge_isolation.py::test_no_direct_market_reads` 静态扫描 `services/`、`api/`：除 `market.py` 的白名单函数（`market_key/_market_row/_run_ticks/_prior_windows/_persist_closed_day/init_market_for_save`）与 `debug.py` 外，不得出现 `db.get(MarketState, save.id)` 或 `Candle.save_id == save.id`。
- 守卫：`market.reject_challenge(save, feature)` 对两类挑战 mode 抛 `CHALLENGE_UNSUPPORTED {feature}`。已接入：`advance_ticks`/`pause_clock`/`resume_clock`/`skip_clock`（feature=clock）、`saves.delete_save`（delete）、`auto_trade` 建/改配置与 start/resume（auto_trade）、`debug` 全部入口含 `reset_market`（debug）。
- 分发：`market._advance_to_now_once` 开头、先于 `paused` 判断，`mode ∈ CHALLENGE_MODES` 时延迟导入 `challenges.sync.sync_entry_save`（时间取 `challenges.timeutil.now()`）。
- 下单：`trading._place_once` 开头对玩家挑战调用 `sync.before_trade`；提交前复核 master tick 与镜像一致，不一致抛 `StaleDataError` 走既有重试。
- 列表与计数：`saves.list_saves` 与 `create_save` 的计数只看 `LISTED_MODES`；`export_save` 对挑战存档 `market_seed` 为 null 并附 `challenge` 块。
- 权益快照：master 跨日时 `market._run_ticks` 不写自身快照，改调 `equity.record_entries_close` 为全部玩家写当日收盘快照。
- 子包 `challenges/`：见其 `CLAUDE.md`（C6 起含结算 `settle.py`、排行 `boards.py`，C7 起 `registry.py` 含给 D 的 §1.7 函数）。`market.py` 与 `saves.py`、`trading.py`、`auto_trade.py` 对子包的导入均为函数内延迟导入，禁止改为顶层导入。

## 真实复盘（模式 E，05 分册）
- 行情来源：复盘存档（`saves.mode='replay'`）的行情由关卡包给出，**不读 `market_states` / `candles`**。分发点（`services/market.py`，均在函数开头、延迟导入 `services/replay`）：`load_market`、`stock_market`、`intraday`；`_advance_to_now_once` 直接返回 0；`advance_ticks`、`pause/resume/skip_clock` 与 `clock_view` 对复盘单独处理（`REPLAY_UNSUPPORTED {clock}` 或时间字段为 null）。
- 守卫：`market.reject_replay(save, feature)` 用于调试入口、自动交易配置与 start/resume、`day_summary`、`supply_chain`；`market.trade_guard(state, code, side)` 在 `trading._place_once` 撮合前执行（已结算、停牌、封板），普通存档恒为 None。
- 名称与代码：`stocks.stock_info_for(db, save, code)` 与 `stocks.info_lookup(db, save)` 是存档视角的查找，`trading` 的持仓、统计、`trade_to_dict(trade, info_lookup)`、`saves.export_save`、`saves.add_watchlist`、`portfolio` 均经它取名。普通存档等同 `get_stock_info`。
- 计分与积分：`services/replay/predictions.py` 只调用 `domain/scoring.py`；积分只走 `services/points.py::credit`，幂等键按 (用户, 关卡, 题)。非首次会话只记分数。
- 子包 `services/replay/` 的文件地图与不变量见其 `CLAUDE.md`。


## 预测市场（模式 D，04 分册，步骤 5–8）
- `pm_lifecycle.py`：生命周期。`materialize(db, info)` 是 `on_created` 钩子（挑战生成事务内，不 commit，幂等，按回合事件 + 合约规则物化 scheduled 市场与选项行）；`void_challenge(db, info, reason)` 是 `on_revoked` 钩子（非终态市场记 `challenge_revoked`）。`sync_market(db, id, now)` 自成事务两阶段：无锁阶段做 I/O 核对（`_verify`：事件指纹、规则集、`registry.reference_change_bp`，后者会推进 master 并 commit，故必须先于锁）；锁阶段 `lock_market`（FOR UPDATE，SQLite 忽略）后 `_advance_locked` 连跳 scheduled→open（`_open` 记补贴 S、定 b/q0）→closed→resolved（`_resolve`：按 user_id 升序兑付，剩余池写 `subsidy_returned_points`）或 voided（`_void`：每人退 max(0, 净投入)）。`sync_challenge`（列表前）、`sync_due(session_factory, now)`（后台 sweeper：live 挑战物化 + 全部非终态市场同步，每市场一个会话）、`void_market`（调试人工作废）。`fingerprint(ev)` = sha256(repr(GameEvent))，永不外发。
- 事件只经 master 的 `events_for_days(include_unpublished=True)` 取得，D 不读 seed；不调用 `registry.challenge_events`（它会先 commit）。`_info_for` 与 `registry.info_of` 构造 ChallengeInfo。挑战已结算时公共 tt 视为 last_tt+1（传闻可在挑战末结算）。
- `prediction_markets.py`：报价 `quote_market`（纯报价，只 sync）、下单 `trade(db, user, market_id, TradeOrder, idempotency_key=, now=)`（同键同市场重放 replayed=True，同键异市场 VALIDATION_ERROR；事务：sync → lock → 状态/超前锁定/账号年龄/频率 → shares 或预算反求 → `domain.check_trade` → 滑点 → `points.debit/credit`（reason `market_buy/market_sell`，幂等键 `market_buy:{mid}:{seq}`）→ 更新 q、池、持仓（卖出按比例扣减成本）、成交行，提交；`IntegrityError/StaleDataError` 整体回滚重试，`PM_MAX_ATTEMPTS`=5 后 `PM_BUSY`）。视图 `market_out` / `market_detail`（含 `window_change_bp`、`my`、`limits`、`balance_points`）/ `list_markets`（排序 open_tt 降序、id 升序，游标 `[open_tt, id]`，永不含 scheduled）/ `price_history`（首点先验，抽样保末点）/ `tape_page`（匿名、seq 降序）/ `my_positions` / `my_settlements` / `pnl_by_user`（给 C 排行榜）。`PmHub` 不在此处（见 `api/pm_ws.py`）。
- 账户年龄读 `challenges.config.current_settings().CHALLENGE_MIN_ACCOUNT_AGE_HOURS`；限额常量在 `domain/prediction_market/constants.py`。
- `core/errors.py` 登记 11 个 `PM_*` 码；`docs/CONTRACT.md` 同步。前端 i18n / 手机端 ERROR_TEXT 待前端阶段同步。
