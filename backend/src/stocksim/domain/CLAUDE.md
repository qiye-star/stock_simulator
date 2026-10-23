# domain（纯领域层）— 给 agent 的说明

## 边界与纯度（硬规则，`tests/unit/domain/test_purity.py` 会检查）
- 零 I/O：禁止 import sqlalchemy/fastapi/starlette/pydantic/random/time/os/sys/pathlib/io/json/logging/uuid 等；禁止 `now()`/`today()`/`open()`/`print()`。
- 只用 stdlib（dataclasses、decimal、datetime 仅限 `date`/`timedelta` 运算、typing、collections.abc）。Python 3.12 类型标注。
- 金额一律 `int` 分；费率只能是 `Decimal`（传 float 直接 TypeError）；涨跌幅用基点 bp（1bp=0.01%）。
- 不修改入参：所有函数返回新对象（`execute_order` 返回新 `Account`，`advance` 返回新 state）。
- 随机只能经 `rng.rand01/rand_below(seed, tick, stock_idx, k)`；同一 (seed, tick) 结果必须相同。
- 错误：抛 `DomainError(code, params)`，code 为契约 ErrorCode 字符串，API 层映射 HTTP。

## 文件地图
- `money.py` 分/元/手续费舍入 · `rng.py` splitmix64 · `errors.py` DomainError 与码常量
- `types.py` Account/Holding/Quote/TradeSettings/OrderRequest/OrderResult/TradeRecord
- `clock.py` 交易时段、分钟推进、跳过、TICKS_PER_TRADING_DAY=20
- `rules.py` 涨跌停、熔断、T+1（从成交推导）、数量校验
- `market_engine.py` init_market / advance / order_book / to_quote
- `matching.py` execute_order（买卖唯一入口，手动与自动共用）
- `auto_trade/` 条件 conditions.py、执行 executor.py · `achievements/` 目录、统计、判定

## 公共 API（services 直接调用）
| 函数 | 签名（摘要） | 说明 |
|---|---|---|
| `init_market` | `(seed, stocks, as_of: date, industry_ranges) -> state` | stocks=[{code,name,industry,profile}] |
| `advance` | `(state, seed, tick, minute_of_day) -> state` | 非交易时段返回副本不变 |
| `order_book` | `(price_cents, seed, tick, stock_idx) -> {bids,asks}` | 五档按需计算，不入状态 |
| `to_quote` | `(state, code) -> Quote \| None` | 撮合/自动交易用快照 |
| `execute_order` | `(req, *, account, quote, settings, trades, trading_day, minute_of_day, source="manual") -> OrderResult` | 失败抛 DomainError |
| `run_auto_trades` | `(configs, runtime, *, tick, trading_day, minute_of_day, quotes, account, settings, trades, max_total_trades=100) -> AutoTickResult` | 结果含新 runtime/account/new_trades/events |
| `should_trigger` | `(config, quote, holding) -> bool` | 条件判断（基础 + 止损止盈） |
| `compute_stats` | `(*, trades, holdings, prices, fund_cents, initial_fund_cents, watchlist_count=0) -> AchievementStats` | 全部由成交推导 |
| `evaluate` | `(stats, unlocked_ids, catalog=CATALOG) -> list[str]` | 仅返回新解锁 id |
| `limit_up_cents` / `limit_down_cents` | `(prev_close_cents) -> int` | 涨跌停价 |
| `rand01` / `rand_below` | `(seed, tick, stock_idx, k[, n])` | RNG |
| `round_half_up_div` / `fee_cents` / `yuan_to_cents` | 见 money.py | 舍入与金额 |
| `is_trading_time` / `session_label` / `advance_minute` | `(minute_of_day)` | 时钟 |
| `skip_target_minutes` / `skip_ticks` | `(minute_of_day[, target])` | 跳过时间 |

## 不变量
- 限价单：买限价 ≥ 市价或卖限价 ≤ 市价才成交，成交价=市价；否则 ORDER_LIMIT_NOT_REACHED。限价须在涨跌停内。
- 手续费单独四舍五入到分；均价 = round(total_cost_cents / qty)；卖出 pnl = (成交价-均价)*量 - 卖出手续费。
- T+1（非 T+0）：可卖 = 持仓 - 当日买入；当日卖出过则禁止买入。当日 = `trading_day`（行情 tick // 20）。
- 行情：每交易 tick ±2%（bull_bias 股票 70% 上涨 0.5%~3%），受涨跌停钳制；交易日切换在 tick % 20 == 0。
- 成交记录的 prev_close_cents / fund_before_cents 是 trade-time 快照，成就统计只读快照。

## 新增错误码（需同步 core/errors.py 与前端 i18n/errors.js）
TRADE_T1_BUY_BLOCKED · TRADE_PRICE_DEVIATION_EXCEEDED · TRADE_PRICE_DEVIATION_CONFIRM · TRADE_CIRCUIT_BREAKER_ACTIVE · AUTO_MAX_AMOUNT_EXCEEDED（自动交易事件码）

## 常见任务
- 改撮合规则：改 matching.py + 补 tests/unit/domain/test_matching.py。
- 改行情参数：改 market_engine.py 常量；注意金定值与确定性测试会变化（测试是行为契约，不要为过测试放宽）。
- 新成就：catalog.py 加一条，stat 字段需在 stats.py 中计算。

## 验证
`cd backend && uv run pytest tests/unit/domain -q`（若 tests/conftest.py 因其他模块失败，可加 `--noconftest`）
