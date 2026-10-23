# services/ — 业务服务（给 agent）

## 边界
- 编排数据库读写与业务规则，抛 `AppError`。不依赖 FastAPI 对象（不接收 Request/Response）。
- 撮合、涨跌停、T+1、成就判定等纯计算在 `domain/`，服务层只组装输入并调用。
- 存档级入口统一经 `saves.open_save(db, user, id)`：归属校验（他人存档 → SAVE_NOT_FOUND）+ `market.advance_to_now`。

## 不变量
- 金额整数分；费率以 Decimal 存储并量化到 6 位，对外输出去掉尾零的字符串。
- 写操作在服务内 `commit`；失败 `rollback` 并转换为 AppError。
- 行情：`market_states.payload` 为 `{code: [9 项]}` + 保留键 `_meta`（trading_tick、as_of）。history 不落 payload；收盘日 K 在交易日切换时追加到 candles；当日 K 由状态派生。
- 推进只在 `market.py` 的 `_run_ticks` 中发生。`advance_to_now` 按 refresh_rate 补推（上限 TICK_CATCHUP_MAX，暂停不推进）；`advance_ticks(db, save, n)` 立即推进（跳过、调试）。
- 乐观锁：`saves.version`。推进/下单冲突（StaleDataError）→ 回滚、刷新存档、重算。跨交易日并发补推时，收盘 candles / equity_snapshots 撞唯一约束（IntegrityError）同样由 `market._retrying` 回滚重算（重读后 last_tick_at 已被他人推进，通常无事可做）；不要改成 insert-or-ignore，否则会带着过期 payload 提交。
- 下单 `trading.place_order(...) -> Trade` 是手动与自动交易共用入口，签名固定；`place_order_detailed` 额外返回新解锁成就与幂等回放标记。
- 成交快照：trades 保存 prev_close、fund_before、tick、trading_day、clock_minute；统计只读快照。
- 每个存档最多 10 个（`MAX_SAVES_PER_USER`）。

## 文件地图
- `stocks.py` 股票池静态数据（data/*.json）与 stocks 表查询；`stock_pool()` 顺序即 stock_idx。
- `seed.py` 股票表幂等种子；`seed_on_startup` 由 main 的 lifespan 调用（失败只记日志）。
- `market.py` 行情编解码、advance_to_now / advance_ticks、行情与个股视图、暂停/继续/跳过、新存档初始化。`market_overview` 支持 limit/cursor/q/sort/order/watchlisted（无参=全部，键集游标，全序为 (主键, 代码)）；`intraday` 不落库，由当日开盘价 + save.market_seed + 全局 tick 用 `domain.advance`（单只股票状态）逐 tick 重放，并校验终点与持久化价格/量一致，否则 `exact=false` 退化。
- `trading.py` 下单（place_order / place_order_detailed）、持仓同步、统计快照、成交分页、幂等键。
- `portfolio.py` 资产与持仓估值（可卖股数来自当日成交）。
- `equity.py` 收盘权益快照（`record_close_snapshot` 在 `market._run_ticks` 交易日切换时幂等 upsert）与 `equity_curve`（初始点+快照+实时点）。portfolio 的当日盈亏由当日成交倒推昨收权益。
- `achievements.py` 成就目录、已解锁列表、成交后判定落库（record_unlocks）。
- `saves.py` 存档 CRUD、导出（JSON）、自选增删、`open_save`。
- `auth.py` 账号与会话（既有）。

## 验证
`cd backend && uv run pytest tests/integration/test_saves.py tests/integration/test_market.py tests/integration/test_orders.py tests/integration/test_portfolio.py -q`

### 自动交易 / 旧版导入 / 调试（auto_trade.py、legacy_import.py、debug.py）
- `auto_trade.run_auto_trade(db, save) -> list[Trade]`：每个刷新周期由 ws 循环在 advance 之后调用。决策用 `domain.auto_trade`（should_trigger / cooldown_ticks），下单只走 `trading.place_order(source="auto", confirm_deviation=True, auto_config_id=…)`。
- 运行时计数从 `auto_trade_events` 推导（每 key=code-direction 的最近尝试 tick、成功次数；全局成功数）。`reset` 清事件即清计数；`stop` 不清（与 legacy 不同，见下）。事件 `message` 列存错误码（成功为空串），API 以 `reason_code` 输出。
- 止损/止盈列为 `*_pct100`：按持仓成本百分比换算为分后交 domain 判断（legacy 为金额，此处以模型为准）。
- `legacy_import.decode_content`：base64→UTF-8→逐字符 XOR（key `stock-simulator-2024`），或明文 JSON；`parse_legacy` 严格校验（`schemas/legacy.py`），返回全部待导入存档：接受单用户 `{username, saves}`，也接受整包用户映射 `{username: userObj}`（localStorage `stock_simulator_users`，各用户存档合并导入）。旧成交 `trading_day=-1`、`tick=0`，不影响当日 T+1；旧记录手续费由金额反推，不自洽则 `record_mismatch`。密码哈希与用户级偏好忽略。
- `debug.py`：资金/时钟/成就/重置行情/清空；路由层以 `ENABLE_DEBUG_API` 守门。
