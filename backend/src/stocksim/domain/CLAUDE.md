# domain（纯领域层）— 给 agent 的说明

## 边界与纯度（硬规则，`tests/unit/domain/test_purity.py` 会检查）
- 零 I/O：禁止 import sqlalchemy/fastapi/starlette/pydantic/random/time/os/sys/pathlib/io/json/logging/uuid 等；禁止 `now()`/`today()`/`open()`/`print()`。
- 只用 stdlib（dataclasses、decimal、fractions、math（`isqrt`）、datetime 仅限 `date`/`timedelta` 运算、typing、collections.abc）。Python 3.12 类型标注。
- 金额一律 `int` 分；费率只能是 `Decimal`（传 float 直接 TypeError）；涨跌幅用基点 bp（1bp=0.01%）。
- 不修改入参：所有函数返回新对象（`execute_order` 返回新 `Account`，`advance` 返回新 state）。
- 随机只能经 `rng.rand01/rand_below(seed, tick, stock_idx, k)`；同一 (seed, tick) 结果必须相同。预测卡诱饵抽样用 `tick = PREDICTION_TICK_BASE − 排期日`（`rng.py` 文档字符串段表）。
- 错误：抛 `DomainError(code, params)`，code 为契约 ErrorCode 字符串，API 层映射 HTTP。

## 文件地图
- `money.py` 分/元/手续费舍入 · `rng.py` splitmix64 · `errors.py` DomainError 与码常量
- `types.py` Account/Holding/Quote/TradeSettings/OrderRequest/OrderResult/TradeRecord
- `clock.py` 时钟规则版本（v1=20 tick/日，v2=242 tick/日）、`TimeBase`、相位/撮合窗/文案、跳过表、v2 墙钟调度纯函数（`next_step_v2`、`plan_catchup_v2`）、对齐不变量
- `rules.py` 涨跌停、熔断、T+1（从成交推导）、数量校验
- `market_engine.py` init_market / advance / order_book / to_quote
- `events/` 事件行情纯函数包（事件生成、产业链传导、漂移计划、快讯文案；见 `events/CLAUDE.md`）
- `scoring.py` 计分纯函数（RPS、NDCG@k、档位、基线分、同伴分、校准表；见 `docs/10.26-plan/02-预测卡.md` §5）
- `predictions/` 预测卡题型、出题、答案校验与称号目录（见 `predictions/CLAUDE.md`）
- `prediction_market/` 预测市场纯函数：LMSR 定价与取整、回合事件合约生成与结算判定、下单限额（见 `prediction_market/CLAUDE.md`；契约 04 §4–§5）
- `matching.py` execute_order（买卖唯一入口，手动与自动共用）
- `auto_trade/` 条件 conditions.py、执行 executor.py · `achievements/` 目录、统计、判定

## 公共 API（services 直接调用）
| 函数 | 签名（摘要） | 说明 |
|---|---|---|
| `init_market` | `(seed, stocks, as_of: date, industry_ranges) -> state` | stocks=[{code,name,industry,profile}] |
| `advance` | `(state, seed, tick, minute_of_day, *, drift=None, rules=1) -> state` | `rules=1` 为 v1（函数体逐字保留）；`rules=2` 为 v2（`_advance_v2`，242 tick/日，换日在次日 9:30）。非交易时段返回副本不变；`drift={stock_idx: ppm}` 叠加到本 tick 随机涨跌幅（事件行情），None/空时与旧版逐位一致 |
| `events.build_ruleset` | `(*, supply_chain, exposure, templates, industries, stock_pool, version=1, clock_rules=1) -> EventRuleset` | 调用方 `json.load` 后传入，domain 不读文件；时间基由 `clock_rules` 取（`ticks_per_day` 不再单独传入）|
| `events.save_params` | `(seed, ruleset) -> SaveParams` | 存档级 β / 边系数抖动 |
| `events.generate_day` | `(seed, day, ruleset, params) -> tuple[GameEvent, ...]` | 某排期日的全部事件（重大 + 小快讯），不落库 |
| `events.build_day_plan` | `(day, events, ruleset, params) -> tuple[Mapping[int,int], ...]` | 窗口 `plan_window(day)` 内事件折算成当日每 tick 的 `{stock_idx: drift_ppm}`，下标 `tt % ticks_per_day` |
| `events.news_between` / `news_at` | `(events, lo_tick, hi_tick)` / `(events, tick)` | 发布 tick 在 (lo, hi] 的快讯 `[(GameEvent, NewsItem)]` |
| `events.render_news_title` | `(ruleset, event, news_item, lang) -> str` | en-US 缺失退回 zh-CN |
| `events.rumor_hint` / `rumor_status` / `event_phase` | 见 `events/reveal.py` | 情报提示、传闻揭晓状态、事件阶段 |
| `order_book` | `(price_cents, seed, tick, stock_idx) -> {bids,asks}` | 五档按需计算，不入状态 |
| `to_quote` | `(state, code) -> Quote \| None` | 撮合/自动交易用快照 |
| `execute_order` | `(req, *, account, quote, settings, trades, trading_day, minute_of_day, source="manual") -> OrderResult` | 失败抛 DomainError；撮合窗按 `settings.clock_rules` |
| `run_auto_trades` | `(configs, runtime, *, tick, trading_day, minute_of_day, quotes, account, settings, trades, max_total_trades=100) -> AutoTickResult` | 结果含新 runtime/account/new_trades/events |
| `should_trigger` | `(config, quote, holding) -> bool` | 条件判断（基础 + 止损止盈） |
| `compute_stats` | `(*, trades, holdings, prices, fund_cents, initial_fund_cents, watchlist_count=0, clock_rules=1) -> AchievementStats` | 全部由成交推导 |
| `evaluate` | `(stats, unlocked_ids, catalog=CATALOG) -> list[str]` | 仅返回新解锁 id |
| `limit_up_cents` / `limit_down_cents` | `(prev_close_cents) -> int` | 涨跌停价 |
| `rand01` / `rand_below` | `(seed, tick, stock_idx, k[, n])` | RNG |
| `round_half_up_div` / `fee_cents` / `yuan_to_cents` | 见 money.py | 舍入与金额 |
| `is_trading_time` / `session_label` / `advance_minute` | `(minute_of_day)` | 时钟（v1 文案） |
| `timebase` / `TimeBase` | `(clock_rules) -> TimeBase(ticks_per_day)` | `day_of / first_tt / offset_of / rolls_at`；services 与 events 据此取代硬编码的 20 |
| `is_order_time` / `phase_of` / `next_event_of` | `(minute_of_day, clock_rules=1)` | 撮合窗（v2 半开区间）、状态相位、下一时段变化 |
| `session_label_v2` / `is_night_owl_window` / `is_early_bird_window` | `(minute_of_day[, clock_rules])` | v2 文案与成就窗口（夜猫 895–899） |
| `skip_target_v2` / `v2_expected_offset` / `v2_minute_of_offset` / `v2_tick_of` | `(minute_of_day)` / `(day, offset)` | v2 跳过、对齐不变量与闭式 |
| `next_step_v2` / `plan_catchup_v2` / `ms_until_minute_v2` | `(minute, anchor_ms, now_ms, *, ms_per_minute, lunch_dwell_ms, close_dwell_ms[, max_trading_ticks])` | 墙钟调度：11:30 停留后跳 12:59，15:00 停留后跳次日 9:29；`plan` 返回 `CatchupPlan(minutes, trading_ticks, anchor_ms, truncated)` |
| `challenge.build_timeline` / `target_tt` / `reached_ms` / `phase_at` | `(*, hold_tts, end_tt, resume_ms, tick_ms, close_lead_ms, min_window_ms) -> Timeline`；`(tl, now_ms)`；`(tl, tt)`；`(tl, now_ms) -> PhaseInfo` | 每日挑战公共时间线（毫秒整数；v2）|
| `challenge.minutes_to_tt` | `(cur_minute, cur_tt, target) -> int` | 逐分钟前进到目标 tt，返回全局 tick 数（午休/隔夜瞬间跨过）|
| `challenge.plan_rounds` / `major_ref` / `holdable_v2` | `(majors, *, rounds, warmup, min_gap, max_burst, max_tt, holdable) -> RoundPlan \| None`；`(ev, questions, *, clock_rules) -> MajorRef`；`(tt) -> bool` | 剧本贪心挑回合（非回合重大事件允许）|
| `challenge.derive_seed` / `make_commitment` / `verify_commitment` | `(key: bytes, date_iso, attempt) -> int`；`(*, date_iso, events_ruleset, clock_rules, seed, salt_hex) -> str`；`(input, digest) -> bool` | HMAC 派生 seed；承诺 sha256 |
| `challenge.question_results` / `trade_scores` | `(S_list, U_list, eligible, *, peer_min)`；`(returns_bp, eligible, *, peer_min) -> list[int]` | 同伴分/基线分；交易同伴差（封顶 ±100）|
| `challenge.competition_ranks` / `reward_points` / `iso_week_key` | `(scores)`；`(rank \| None, eligible_count) -> int`；`(date)` | 竞赛排名（1,2,2,4）；奖励表（06 §4.3）；ISO 周键 |
| `prediction_market.buy_cost` / `sell_proceeds` / `prices_ppm` | `(q, b_milli, i, shares) -> int`；同左；`(q, b_milli) -> tuple[int,...]` | LMSR 整数花费：买入向上取整、卖出向下取整（先量化 1e-12）；价格和恰为 1e6（最大余数）|
| `prediction_market.quote` / `max_shares_for_budget` / `cost_points` | `(q, b_milli, side, i, shares) -> Quote`；`(q, b_milli, i, budget, cap) -> int`；`(q, b_milli) -> Decimal` | 报价；预算反求份额（精确）；100·Cs(q) 诊断用 |
| `prediction_market.b_for_subsidy` / `max_loss_points` / `subsidy_for` | `(S, prior_ppm) -> (b_milli, q0)`；`(b_milli, q0) -> Decimal`；`(expected_participants) -> int` | 由补贴上限反推 b 与虚拟先验 q0；最大亏损 ≤ S；S 三档 1000/2000/4000 |
| `prediction_market.contracts_for_challenge` / `contracts_for_event` | `(events, ctx, *, round_event_ids) -> tuple[ContractSpec,...]`；`(ev, ctx) -> tuple[ContractSpec,...]` | 只对回合事件开市；截断 8 个，顺序 (首次出现 tick, event_id, kind)；ctx=`ContractContext(clock_rules, first_tt, last_tt, structure)` |
| `prediction_market.resolve_rumor` / `resolve_bucket` / `bucket_prior` | `(ev) -> 0\|1`（deny/confirm）；`(spec, change_bp) -> int`；`(scope, sentiment) -> tuple` | 结算判定（左闭右开）；分档先验查表 |
| `prediction_market.check_trade` / `market_cap_points` | `(*, side, shares, amount_points, state: LimitState) -> None`（越限抛 DomainError）；`(S) -> int` | 下单限额：单市场净投入 max(200,S//4)、单场买入 3000、份额 1..200、卖出不超持仓、回款 0 拒绝 |
| `skip_target_minutes` / `skip_ticks` | `(minute_of_day[, target])` | 跳过时间 |

## 不变量
- 限价单：买限价 ≥ 市价或卖限价 ≤ 市价才成交，成交价=市价；否则 ORDER_LIMIT_NOT_REACHED。限价须在涨跌停内。
- 手续费单独四舍五入到分；均价 = round(total_cost_cents / qty)；卖出 pnl = (成交价-均价)*量 - 卖出手续费。
- T+1（非 T+0）：可卖 = 持仓 - 当日买入；当日卖出过则禁止买入。当日 = `trading_day`（行情 tick // N，N 由 `timebase(clock_rules)` 决定：v1=20、v2=242）。
- 行情随机数 k 段：见 `rng.py` 文档字符串（新功能必须另划不冲突的 k 段并更新 `test_events_rng_layout.py`）。
- 事件漂移：`advance(drift=)` 只改尝试价；熔断判断与涨跌停钳制照旧，被钳掉的部分直接丢弃。`market_engine` 不得 import `events`。
- 行情 v1：每交易 tick ±2%（bull_bias 股票 70% 上涨 0.5%~3%），受涨跌停钳制；交易日切换在 tick % 20 == 0。
- 行情 v2（07 §4）：日内 242 tick，换日在次日 9:30；单 tick 噪声 = 特质（档位 × σ≈924 ppm）+ 全市场共同因子（idx 400）+ 日趋势（1%/日，±[400,700] ppm/tick）+ bull 漂移 120 ppm；成交量为当日累计（单调）。常量 `V2_*` 发布后冻结，标定见 `scripts/clock_v2_sim_report.py`。
- v1 与 v2 的撮合窗不同：v1 闭区间含 11:30/15:00；v2 为 `[9:30,11:30)∪[13:00,15:00)`。
- 成交记录的 prev_close_cents / fund_before_cents 是 trade-time 快照，成就统计只读快照。

## 新增错误码（需同步 core/errors.py 与前端 i18n/errors.js）
TRADE_T1_BUY_BLOCKED · TRADE_PRICE_DEVIATION_EXCEEDED · TRADE_PRICE_DEVIATION_CONFIRM · TRADE_CIRCUIT_BREAKER_ACTIVE · AUTO_MAX_AMOUNT_EXCEEDED（自动交易事件码）

## 常见任务
- 改撮合规则：改 matching.py + 补 tests/unit/domain/test_matching.py。
- 调事件强度/频率：只改 `events/constants.py`，再跑 `python3 scripts/event_sim_report.py --seeds 20 --days 300`。
- 改行情参数：改 market_engine.py 常量；注意金定值与确定性测试会变化（测试是行为契约，不要为过测试放宽）。
- 新成就：catalog.py 加一条，stat 字段需在 stats.py 中计算。

## 验证
`cd backend && uv run pytest tests/unit/domain -q`（若 tests/conftest.py 因其他模块失败，可加 `--noconftest`）

## 真实复盘（模式 E，05 §5.4）
- `replay.py`（零 I/O，`test_purity` 覆盖）：阶段与位置（`PHASE_MINUTE` 540/570/900/960、`phase_tick = day*4+阶段序号`、`next_position`）、事件可见性（`event_visible`，`SLOT_VISIBLE_FROM` pre_open=0 / intraday=2 / post_close=3）、价格缩放与显示口径（`scale_price`、`display_bar`：先缩放再以显示前收按当日涨跌幅夹紧）、阶段报价（`visible_quote`）、标志位（`phase_flags`，`FLAG_*` 与关卡包 flags 位定义一致）、收益率（`return_bp`）。
- `rules.py` 的 `limit_up_cents / limit_down_cents / clamp_to_limits / is_within_limits / is_limit_*` 增加可选参数 `pct_bp=LIMIT_PCT_BP`（默认 10%，普通路径不变）；`types.Quote.limit_pct_bp=1000`；`market_engine.to_quote` 读取 `stock["limit_pct_bp"]`；`matching._check_limit_price` 按 `quote.limit_pct_bp` 校验。
- 金值常量未改：`test_market_engine_golden.py` 与 v2 金值保持不变。
