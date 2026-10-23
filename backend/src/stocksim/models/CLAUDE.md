# models/ — ORM 模型与列规格（权威）

SQLAlchemy 2.0 typed 模型，共 15 张表。以下为定稿列规格；与代码不一致时以代码 + `alembic check` 为准并回填此表。

## 约定
- 类型缩写：`uuid`=Uuid；`str(n)`=String(n)；`int`/`big`=Integer/BigInteger；`money`=Money（整数分，允许负数）；`ts`=UTCDateTime（UTC）；`num(8,6)`=Numeric；`json`=JSON/JSONB。`?`=可空；`=x`=默认值。
- 主键一律 `id:uuid`，1:1 表例外（以 `save_id` 为主键）。`saves.version` 为乐观锁（version_id_col）。
- 枚举用 String + CHECK，不用原生 ENUM。
- `trades.seq` 与 `saves.trade_seq` 由服务层在存档乐观锁内分配，用于游标分页。
- `saves.version` 的乐观锁映射必须使用 Column 对象（`__mapper_args__ = {"version_id_col": version}`），字符串会在 flush 时报错。

## 表规格
| 表 (PK / UQ / FK / IX) | 列 |
| --- | --- |
| users (PK id; UQ username) | id:uuid, username:str20, password_hash:str255, theme:str16=dark∈{dark,light,festival}, lang:str8=zh-CN∈{zh-CN,en-US}, refresh_rate_ms:int=3000, tutorial_completed:bool=false, created_at:ts, updated_at:ts |
| sessions (PK id; UQ token_hash; FK user_id→users CASCADE; IX user_id, expires_at) | id:uuid, user_id:uuid, token_hash:str64, created_at:ts, expires_at:ts, last_seen_at:ts? |
| legacy_imports (PK id; FK user_id CASCADE, save_id→saves SET NULL; IX user_id) | id:uuid, user_id:uuid, save_id:uuid?, source_format:str16=legacy-xor, source_sha256:str64, status:str16∈{imported,failed}, created_at:ts |
| stocks (PK id; UQ code) | id:uuid, code:str6, name:str32, industry:str16 |
| saves (PK id; FK user_id CASCADE; IX user_id; version 乐观锁) | id:uuid, user_id:uuid, name:str20='', mode:str16=normal, initial_fund_cents:money, cash_cents:money, buy_fee_rate:num(8,6)=0.0003, sell_fee_rate:num(8,6)=0.0013, t0_mode:bool=false, trade_unit:int=1∈{1,100}, market_seed:big∈[0,2^63-1], tick:big=0, trade_seq:big=0, trading_day:int=1, clock_minute:int=570∈[0,1440), paused:bool=false, last_tick_at:ts?, auto_enabled:bool=false, auto_paused:bool=false, auto_max_total_trades:int=100, version:int=1, created_at:ts, updated_at:ts |
| save_stats (PK save_id, FK CASCADE) | save_id:uuid, trade_count, profit_count, loss_count, max_holdings, auto_total_trades, auto_success_trades, auto_failed_trades:int=0, auto_total_pnl_cents:money=0, updated_at:ts |
| save_sectors (PK id; UQ save_id+sector; FK save_id CASCADE; IX save_id) | id:uuid, save_id:uuid, sector:str16 |
| save_achievements (PK id; UQ save_id+achievement_id; FK CASCADE; IX save_id) | id:uuid, save_id:uuid, achievement_id:str64, unlocked_at:ts |
| holdings (PK id; UQ save_id+stock_code; CHECK quantity>=0; FK CASCADE; IX save_id) | id:uuid, save_id:uuid, stock_code:str6, quantity:int, avg_price_cents:money, total_cost_cents:money, updated_at:ts |
| trades (PK id; UQ save_id+seq; CHECK side∈{buy,sell}, source∈{manual,auto}, quantity>0; FK save_id CASCADE, auto_config_id→auto_trade_configs SET NULL) | id:uuid, save_id:uuid, seq:big, stock_code:str6, side:str4, source:str8, price_type:str8=market, limit_price_cents:money?, price_cents:money, quantity:int, gross_cents:money, fee_cents:money=0, cash_delta_cents:money（买负卖正，已扣费）, realized_pnl_cents:money=0, prev_close_cents:money, fund_before_cents:money=0（成交前资金快照）, idempotency_key:str64?（同存档唯一）, tick:big, trading_day:int, clock_minute:int, auto_config_id:uuid?, created_at:ts |
| watchlist_items (PK id; UQ save_id+stock_code; FK CASCADE; IX save_id) | id:uuid, save_id:uuid, stock_code:str6, created_at:ts |
| market_states (PK save_id, FK CASCADE) | save_id:uuid, payload:json（见下）, updated_at:ts |
| candles (PK id; UQ save_id+stock_code+trading_day; FK CASCADE; IX save_id) | id:uuid, save_id:uuid, stock_code:str6, trading_day:int, open_cents/high_cents/low_cents/close_cents:money, volume:big |
| auto_trade_configs (PK id; UQ save_id+stock_code+direction; CHECK 枚举见下; FK CASCADE; IX save_id) | id:uuid, save_id:uuid, stock_code:str6, direction:str4∈{buy,sell}, condition_type:str12∈{price,percentage,profit,time}, condition_operator:str8∈{above,below,equal}, condition_value_cents:money?（price/profit 阈值，分）, condition_pct100:int?（percentage 阈值×100）, quantity:int>0, price_type:str8=market, limit_price_cents:money?, stop_loss_pct100:int?, take_profit_pct100:int?, max_trades:int=0, max_amount_cents:money?, enabled:bool=true, created_at:ts, updated_at:ts |
| auto_trade_events (PK id; IX save_id+created_at; FK save_id CASCADE, config_id→auto_trade_configs SET NULL) | id:uuid, save_id:uuid, config_id:uuid?, stock_code:str6, direction:str4, condition_type:str12, success:bool, message:str255, amount_cents:money=0, pnl_cents:money=0, pnl_pct100:int?, buy_price_cents:money?, sell_price_cents:money?, tick:big, trading_day:int, created_at:ts |

## market_states.payload
`{code: [price, prev_close, open, high, low, daily_vol, prev_daily_vol, avg_vol, cb_cooldown], "_meta": {"trading_tick": int, "as_of": "YYYY-MM-DD"}}`：价格为整数分，成交量为股数，`cb_cooldown` 为剩余熔断冷却 tick 数。
- `_meta` 为保留键（股票代码都是 6 位数字）：`trading_tick` 为已推进的交易 tick，`as_of` 为交易日 0 的日期。WS 与快照遍历时必须跳过它（非 list 值即跳过）。

## auto_trade 字段名：DB 列 vs API（以代码为准）
- DB 列 `condition_pct100` / `stop_loss_pct100` / `take_profit_pct100` 存百分比×100 的整数；API（AutoConfigIn/Out）对应字段为 `condition_percent` / `stop_loss_percent` / `take_profit_percent`（float，%）。
- 没有 `condition_value_bp`、`stop_loss_cents`、`take_profit_cents` 这些名字；止盈止损是占持仓成本的百分比，不是金额。
- `stock_code` 在 DB 与事件中叫 `stock_code`，在 AutoConfigOut 中叫 `code`。
- 事件失败原因：`auto_trade_events.message` 在 API 中叫 `reason_code`（仅失败时非 null）。

## 注意
- 改任何列/约束后必须生成迁移，并跑 `uv run alembic check` 确认无漂移。
- 不要在模型里写业务逻辑；规则在 `domain/`，编排在 `services/`。
