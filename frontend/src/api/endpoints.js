/**
 * REST 端点的类型化封装：每个契约端点一个函数（见 docs/CONTRACT.md「REST API」）。
 *
 * 约定：
 *   - 金额字段为整数分，名称以 _cents 结尾；百分比为 float（2.5 表示 2.5%）
 *   - 请求/响应字段名保持服务端 snake_case，不在前端改名
 *   - 返回值即服务端 JSON（列表接口返回 {items, next_cursor} 的需调用方解包 items）
 *   - 失败时抛出 ApiError（./http.js），调用方用 errorMessage(err, t)（i18n/errors.js）翻译
 * 与后端 schemas 不一致时以 backend/src/stocksim/schemas 为准，并同步更新此处。
 */
import { del, get, patch, post, put } from './http.js';

/** @typedef {string} Uuid */
/** @typedef {'zh-CN' | 'en-US'} Lang */
/** @typedef {'dark' | 'light' | 'festival'} Theme */

/**
 * ---------- 响应类型（与 backend/src/stocksim/schemas 一一对应）----------
 */

/**
 * schemas/user.py UserOut
 * @typedef {Object} UserOut
 * @property {Uuid} id
 * @property {string} username
 * @property {Theme} theme
 * @property {Lang} lang
 * @property {number} refresh_rate_ms
 * @property {boolean} tutorial_completed
 * @property {'fast' | 'normal' | 'slow'} clock_speed v2 存档的节奏档（约 10/20/30 分钟一交易日）
 * @property {string} created_at ISO 8601 UTC
 */

/**
 * schemas/user.py MePatch（部分更新）
 * @typedef {Object} MePatch
 * @property {Theme} [theme]
 * @property {Lang} [lang]
 * @property {number} [refresh_rate_ms] 500-60000
 * @property {boolean} [tutorial_completed]
 * @property {'fast' | 'normal' | 'slow'} [clock_speed]
 */

/**
 * schemas/stocks.py StockOut（GET /stocks 数组项）
 * @typedef {Object} StockOut
 * @property {string} code
 * @property {string} name
 * @property {string} industry
 */

/**
 * schemas/saves.py SaveOut
 * @typedef {Object} SaveOut
 * @property {Uuid} id
 * @property {string} name
 * @property {string} mode
 * @property {number} initial_fund_cents
 * @property {number} cash_cents
 * @property {string} buy_fee_rate 十进制字符串，如 "0.0003"
 * @property {string} sell_fee_rate
 * @property {boolean} t0_mode
 * @property {1 | 100} trade_unit
 * @property {number} tick
 * @property {number} trading_day
 * @property {number} clock_minute 0-1439
 * @property {'v1' | 'v2'} clock_rules 时钟规则版本（只读；新建默认 v1）
 * @property {boolean} events_enabled 事件模式（只在创建时设置，默认 false，之后不可改）
 * @property {boolean} paused
 * @property {number} version
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * schemas/market.py ClockOut（时钟接口与市场快照共用的字段）
 * @typedef {Object} ClockOut
 * @property {boolean} paused
 * @property {number} tick
 * @property {number} trading_day
 * @property {number} clock_minute
 * @property {string} session
 * @property {number} skipped_ticks 跳过接口返回的推进 tick 数（0 = 无需跳过）
 * @property {'v1' | 'v2'} clock_rules
 * @property {'pre_open' | 'morning' | 'lunch' | 'afternoon' | 'closed'} phase
 * @property {boolean} trading 此刻能否下单（与暂停无关）
 * @property {{ kind: 'open' | 'lunch' | 'reopen' | 'close', minute: number, at: string | null } | null} next_event
 * @property {number | null} ms_per_minute 交易时段每游戏分钟的现实毫秒数
 * @property {string | null} next_tick_at 暂停或停留中为 null
 * @property {string | null} fast_forward_at 仅 v2、停在 11:30/15:00 时有值
 * @property {string | null} server_time 服务端生成响应的 UTC 时间（校正本机时钟偏差）
 */

/**
 * schemas/market.py QuoteOut
 * @typedef {Object} QuoteOut
 * @property {string} code
 * @property {string} name
 * @property {string} industry
 * @property {number} price_cents
 * @property {number} prev_close_cents
 * @property {number} open_cents
 * @property {number} high_cents
 * @property {number} low_cents
 * @property {number} volume
 * @property {number} change_bp
 * @property {number} limit_up_cents
 * @property {number} limit_down_cents
 * @property {boolean} circuit_breaker_active
 * @property {boolean} watchlisted
 */

/**
 * schemas/market.py MarketOut（GET /saves/{id}/market）
 * @typedef {ClockOut & {
 *   stocks: QuoteOut[],
 *   total: number,
 *   next_cursor: string | null,
 * }} MarketOut total 为按 q/watchlisted 过滤后的总数（不受 limit/cursor 影响）；next_cursor 为 null 表示末页（不分页时恒为 null）
 */

/**
 * getMarket 的可选查询参数（均可省略；全部不传时返回全部股票、股票池顺序）。
 * @typedef {Object} MarketQuery
 * @property {number} [limit] 1-500
 * @property {string | null} [cursor] 不透明串，取自上一页 next_cursor（绑定 sort/order）
 * @property {string} [q] 代码或名称子串，不区分大小写，<=32 字符
 * @property {'code' | 'price' | 'change' | 'volume'} [sort]
 * @property {'asc' | 'desc'} [order] 默认 code 升序，其余降序
 * @property {boolean} [watchlisted] 按自选过滤
 */

/**
 * schemas/market.py IntradayPointOut
 * @typedef {Object} IntradayPointOut
 * @property {number} minute 当日分钟数 0-1439（该 tick 完成后的游戏时钟）
 * @property {number} tick 全局 tick 序号，与 WebSocket tick 消息对齐
 * @property {number} price_cents
 * @property {number} volume 当日累计成交量（股）
 */

/**
 * schemas/market.py IntradayOut（GET /saves/{id}/market/{code}/intraday）
 * @typedef {Object} IntradayOut
 * @property {string} code
 * @property {number} trading_day
 * @property {string} date
 * @property {number} clock_minute
 * @property {number} tick
 * @property {number} prev_close_cents
 * @property {number} open_cents
 * @property {IntradayPointOut[]} points 按时间升序；开盘前为空；休市分钟无点
 * @property {boolean} exact false 表示无法精确重放（如调试改过时钟），points 退化为仅当前点
 */

/**
 * schemas/market.py StockMarketOut（GET /saves/{id}/market/{code}）
 * @typedef {QuoteOut & {
 *   candles: { trading_day: number, date: string, open_cents: number, high_cents: number, low_cents: number, close_cents: number, volume: number }[],
 *   order_book: { bids: { price_cents: number, volume: number }[], asks: { price_cents: number, volume: number }[] },
 *   suspended: boolean 复盘存档当前阶段停牌（普通存档恒 false）,
 * }} StockMarketOut
 */

/**
 * schemas/portfolio.py HoldingOut
 * @typedef {Object} HoldingOut
 * @property {string} code
 * @property {string} name
 * @property {number} quantity
 * @property {number} sellable_quantity T+1 已扣除当日买入
 * @property {number} avg_price_cents
 * @property {number} total_cost_cents
 * @property {number} market_price_cents
 * @property {number} market_value_cents
 * @property {number} pnl_cents
 * @property {number} pnl_bp
 */

/**
 * schemas/portfolio.py PortfolioOut
 * @typedef {Object} PortfolioOut
 * @property {number} tick
 * @property {number} trading_day
 * @property {number} cash_cents
 * @property {number} initial_fund_cents
 * @property {number} market_value_cents
 * @property {number} equity_cents
 * @property {number} net_pnl_cents
 * @property {HoldingOut[]} holdings
 * @property {number} prev_equity_cents 昨日收盘权益
 * @property {number} day_pnl_cents 当日盈亏 = 当前权益 - 昨日收盘权益
 * @property {number} day_pnl_bp
 */

/**
 * schemas/portfolio.py EquityPointOut
 * @typedef {Object} EquityPointOut
 * @property {number} trading_day 初始点为 -1
 * @property {number} equity_cents
 * @property {number} cash_cents
 * @property {number} market_value_cents
 * @property {'initial' | 'close' | 'live'} kind
 */

/**
 * schemas/portfolio.py EquityCurveOut（GET /saves/{id}/equity-curve）
 * @typedef {Object} EquityCurveOut
 * @property {'7d' | '30d' | 'all'} range
 * @property {EquityPointOut[]} items 按 trading_day 升序
 */

/**
 * schemas/orders.py OrderIn
 * @typedef {Object} OrderIn
 * @property {string} code 6 位代码
 * @property {'buy' | 'sell'} side
 * @property {number} quantity
 * @property {'market' | 'limit'} price_type
 * @property {number} [limit_price_cents]
 * @property {boolean} [confirm_deviation]
 */

/**
 * schemas/orders.py TradeOut
 * @typedef {Object} TradeOut
 * @property {Uuid} id
 * @property {number} seq
 * @property {string} code
 * @property {string} name
 * @property {'buy' | 'sell'} side
 * @property {string} source 'manual' | 'auto'
 * @property {'market' | 'limit'} price_type
 * @property {number | null} limit_price_cents
 * @property {number} price_cents
 * @property {number} quantity
 * @property {number} gross_cents
 * @property {number} fee_cents
 * @property {number} cash_delta_cents
 * @property {number} realized_pnl_cents
 * @property {number} prev_close_cents
 * @property {number} tick
 * @property {number} trading_day
 * @property {number} clock_minute
 * @property {Uuid | null} auto_config_id
 * @property {string} created_at
 */

/**
 * schemas/orders.py OrderOut（POST /orders 的 201；重放幂等键时为 200 且 replayed=true）
 * @typedef {Object} OrderOut
 * @property {TradeOut} trade
 * @property {string[]} unlocked_achievement_ids
 * @property {number} cash_cents
 * @property {boolean} replayed
 */

/**
 * schemas/orders.py TradePageOut
 * @typedef {Object} TradePageOut
 * @property {TradeOut[]} items
 * @property {string | null} next_cursor
 */

/**
 * schemas/achievements.py AchievementDefOut（GET /achievements/catalog）
 * @typedef {Object} AchievementDefOut
 * @property {string} id
 * @property {'bronze' | 'silver' | 'gold' | 'legend'} level
 * @property {string} category
 * @property {string} stat
 * @property {number} threshold
 * @property {boolean} hidden
 * @property {string} hidden_reason
 * @property {string} op
 */

/**
 * schemas/achievements.py SaveAchievementOut（GET /saves/{id}/achievements 数组项）
 * @typedef {Object} SaveAchievementOut
 * @property {string} achievement_id
 * @property {string} unlocked_at
 */

/**
 * schemas/auto_trade.py AutoConfigOut
 * @typedef {Object} AutoConfigOut
 * @property {string} id
 * @property {string} code
 * @property {string} name
 * @property {'buy' | 'sell'} direction
 * @property {'price' | 'percentage' | 'profit' | 'time'} condition_type
 * @property {'above' | 'below' | 'equal' | null} condition_operator 时间条件为 null
 * @property {number | null} condition_value_cents price / profit 条件的阈值（分）
 * @property {number | null} condition_percent percentage 条件的阈值（百分数）
 * @property {number} quantity
 * @property {'market' | 'limit'} price_type
 * @property {number | null} limit_price_cents
 * @property {number | null} stop_loss_percent 占持仓成本的百分比
 * @property {number | null} take_profit_percent 占持仓成本的百分比
 * @property {number} max_trades 0 = 不限
 * @property {number | null} max_amount_cents
 * @property {boolean} enabled
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * schemas/auto_trade.py AutoConfigIn（POST 创建 / PUT 全量替换；extra 字段会被 422 拒绝）
 * @typedef {Object} AutoConfigIn
 * @property {string} code 6 位代码
 * @property {'buy' | 'sell'} direction
 * @property {'price' | 'percentage' | 'profit' | 'time'} condition_type
 * @property {'above' | 'below' | 'equal'} [condition_operator] 时间条件必须省略或 null
 * @property {number | null} [condition_value_cents] price / profit
 * @property {number | null} [condition_percent] percentage，范围 0-1000
 * @property {number} quantity
 * @property {'market' | 'limit'} [price_type]
 * @property {number | null} [limit_price_cents] 仅 limit
 * @property {number | null} [stop_loss_percent] 0-100
 * @property {number | null} [take_profit_percent] 0-1000
 * @property {number} [max_trades]
 * @property {number | null} [max_amount_cents]
 * @property {boolean} [enabled]
 */

/**
 * schemas/auto_trade.py AutoConfigList
 * @typedef {{ items: AutoConfigOut[] }} AutoConfigList
 */

/**
 * schemas/auto_trade.py AutoStatusOut（GET /status 与 start/pause/resume/stop/reset 的返回）
 * @typedef {Object} AutoStatusOut
 * @property {boolean} enabled
 * @property {boolean} paused
 * @property {number} max_total_trades
 * @property {number} total_trades
 * @property {number} success_trades
 * @property {number} failed_trades
 * @property {number} total_pnl_cents
 */

/**
 * schemas/auto_trade.py AutoEventOut
 * reason_code 仅失败事件有值：AUTO_LIMIT_REACHED / AUTO_MAX_AMOUNT_EXCEEDED / 下单失败的交易错误码。
 * @typedef {Object} AutoEventOut
 * @property {string} id
 * @property {string | null} config_id
 * @property {string} stock_code
 * @property {'buy' | 'sell'} direction
 * @property {string} condition_type
 * @property {boolean} success
 * @property {string | null} reason_code
 * @property {number} amount_cents
 * @property {number} pnl_cents
 * @property {number | null} pnl_percent
 * @property {number | null} buy_price_cents
 * @property {number | null} sell_price_cents
 * @property {number} tick
 * @property {number} trading_day
 * @property {string} created_at
 */

/**
 * schemas/auto_trade.py AutoEventPage（GET /events?cursor=&limit=，默认 50，最大 200）
 * @typedef {Object} AutoEventPage
 * @property {AutoEventOut[]} items
 * @property {string | null} next_cursor
 */

/**
 * schemas/debug.py DebugResultOut
 * @typedef {Object} DebugResultOut
 * @property {string} action
 * @property {number} cash_cents
 * @property {number} clock_minute
 * @property {number} trading_day
 * @property {number} changed
 */

/**
 * schemas/legacy.py LegacyImportOut
 * @typedef {Object} LegacyImportOut
 * @property {{ save_id: string, name: string, cash_cents: number, holdings: number, trades: number, watchlist: number, achievements: number }[]} imported
 * @property {number} skipped_achievements
 */

/**
 * WebSocket 服务端消息（api/ws.py）。消息顺序：tick → phase → news → challenge → prediction → title → trade → achievement → auto_event。
 * tick 帧：`{t:'tick', tick, advanced, clock, full, q:[[code, price_cents, change_bp, volume], ...]}`，q 只含相对上一帧变化的股票（首帧 full=true 为全量）。
 * tick.clock 为 WS 子集（分钟字段叫 minute，不是 clock_minute），其余字段与 REST ClockOut 同源。
 * 未知 t 的消息必须忽略（features/market 的 normalizeTick 对非 tick 返回 null，不报错）。
 * @typedef {{ t: 'tick', tick: number, advanced: number, full: boolean, q: [string, number, number, number][],
 *     clock: WsClock }
 *   | { t: 'phase', from: string, to: string, trading_day: number, clock_minute: number }
 *   | { t: 'news', trading_tick: number, items: NewsOut[], truncated: boolean }
 *   | { t: 'challenge', challenge_id: string, status: ChallengeStatus, phase: ChallengePhase, round_index: number | null, next_change_at: string | null, public_trading_tick: number, resolved_qids: number }
 *   | { t: 'prediction', op: 'opened' | 'answered' | 'expired' | 'settled' | 'void', card_id: string, event_id: string, status: string, points: number | null, balance: number | null }
 *   | { t: 'title', ids: string[] }
 *   | { t: 'trade', seq: number, count: number }
 *   | { t: 'achievement', ids: string[] }
 *   | { t: 'auto_event', count: number, trades: number }
 *   | { t: 'subscribed' | 'unsubscribed', code: string }
 *   | { t: 'pong' }
 *   | { t: 'error', code: string }} WsServerMessage
 */

/**
 * WebSocket tick 帧的 clock 字段（api/ws.py WS_CLOCK_EXTRA）。
 * @typedef {{ minute: number, trading_day: number, paused: boolean, trading: boolean, clock_rules: 'v1' | 'v2', phase: string, next_event: { kind: string, minute: number, at: string | null } | null, ms_per_minute: number | null, next_tick_at: string | null, fast_forward_at: string | null, server_time: string | null }} WsClock
 */

/** ---------- 事件行情 / 产业链 / 收盘小结（schemas/events.py、schemas/market.py、schemas/day_summary）----------
 * 事件模式（01 §8.1）：关闭的存档返回 409 EVENTS_DISABLED。
 */

/** @typedef {'announcement' | 'news' | 'policy' | 'sudden' | 'rumor'} EventKind */
/** @typedef {'stock' | 'industry' | 'market'} EventScope */

/**
 * schemas/events.py NewsOut（GET /saves/{id}/news 与 WS news.items 共用）
 * @typedef {Object} NewsOut
 * @property {string} news_id `${event_id}:${stage}`
 * @property {string} event_id
 * @property {'precursor' | 'publish' | 'confirm' | 'deny'} stage
 * @property {EventKind} kind
 * @property {string | null} subtype 仅 announcement 有值
 * @property {EventScope} scope
 * @property {boolean} major
 * @property {1 | -1} sentiment
 * @property {string} title
 * @property {string | null} industry
 * @property {string | null} code
 * @property {string | null} stock_name
 * @property {number} trading_day
 * @property {number} trading_tick
 * @property {number} day_offset
 * @property {number | null} tick
 * @property {number | null} clock_minute
 */

/** @typedef {{ items: NewsOut[], next_cursor: string | null }} NewsPageOut */

/**
 * schemas/events.py EventOut
 * @typedef {Object} EventOut
 * @property {string} event_id
 * @property {number} trading_day
 * @property {number} slot
 * @property {EventKind} kind
 * @property {string | null} subtype
 * @property {EventScope} scope
 * @property {string | null} source_industry
 * @property {string | null} source_code
 * @property {boolean} major
 * @property {1 | -1} sentiment
 * @property {string} title
 * @property {number} first_seen_trading_tick
 * @property {number | null} publish_trading_tick
 * @property {'expected' | 'active' | 'settled'} phase
 * @property {'unresolved' | 'confirmed' | 'denied' | null} rumor_status
 * @property {number | null} resolved_trading_tick
 */

/** @typedef {{ items: EventOut[], next_cursor: string | null }} EventPageOut */

/**
 * schemas/events.py PropagationStepOut
 * @typedef {Object} PropagationStepOut
 * @property {string} industry
 * @property {number} hop
 * @property {string | null} via_industry
 * @property {'supply' | 'demand' | 'substitute' | 'same_theme' | null} relation
 * @property {number} arrived_trading_tick
 * @property {number} arrived_trading_day
 * @property {number | null} change_bp
 */

/**
 * schemas/events.py EventDetailOut（GET /saves/{id}/events/{event_id}）
 * @typedef {EventOut & { news: NewsOut[], propagation: PropagationStepOut[] }} EventDetailOut
 */

/**
 * schemas/events.py EventMarkOut / EventMarksOut（GET /saves/{id}/market/{code}/event-marks）
 * @typedef {Object} EventMarkOut
 * @property {string} event_id
 * @property {number} trading_day
 * @property {number} trading_tick
 * @property {'source' | 'propagated' | 'market'} role
 * @property {boolean} major
 * @property {EventKind} kind
 * @property {1 | -1} sentiment
 * @property {string} title
 */

/** @typedef {{ code: string, items: EventMarkOut[] }} EventMarksOut */

/**
 * schemas/events.py SupplyChainOut（GET /saves/{id}/supply-chain）
 * @typedef {Object} SupplyChainOut
 * @property {number} ruleset
 * @property {{ id: string, layer: number, stock_count: number, leaders: string[] }[]} nodes
 * @property {{ id: string, from_industry: string, to_industry: string, relation: 'supply' | 'demand' | 'substitute' | 'same_theme', sign: 1 | -1, strength: number | null, lag_days: number | null, revealed_level: 0 | 1 | 2 }[]} edges
 */

/**
 * schemas/events.py EdgeRevealOut / RumorHintOut（情报卡）
 * @typedef {Object} EdgeRevealOut
 * @property {string} edge_id
 * @property {string} from_industry
 * @property {string} to_industry
 * @property {'supply' | 'demand' | 'substitute' | 'same_theme'} relation
 * @property {1 | -1} sign
 * @property {number} strength
 * @property {number | null} lag_days
 * @property {1 | 2} level
 */

/**
 * @typedef {Object} RumorHintOut
 * @property {string} event_id
 * @property {'likely_true' | 'likely_false'} hint
 * @property {80 | 100} accuracy_pct
 */

/**
 * schemas/intel.py IntelStateOut（GET /saves/{id}/intel）
 * @typedef {Object} IntelStateOut
 * @property {EdgeRevealOut[]} edges
 * @property {RumorHintOut[]} rumor_hints
 * @property {{ edge_l1: number, edge_l2: number, rumor_hint: number }} prices
 * @property {number} daily_limit
 * @property {number} used_today
 * @property {number} balance
 */

/**
 * schemas/intel.py IntelPurchaseOut（POST .../intel/edges 与 .../intel/rumor-hints）
 * @typedef {Object} IntelPurchaseOut
 * @property {number} charged 0 表示已拥有、未扣费
 * @property {number} balance
 * @property {EdgeRevealOut | null} edge
 * @property {RumorHintOut | null} hint
 */

/**
 * schemas/market.py DaySummaryOut（GET /saves/{id}/day-summary，收盘小结）
 * @typedef {Object} DaySummaryOut
 * @property {number} trading_day
 * @property {string} date
 * @property {'v1' | 'v2'} clock_rules
 * @property {'trading' | 'closed'} status
 * @property {number | null} equity_cents
 * @property {number | null} prev_equity_cents
 * @property {number | null} day_pnl_cents
 * @property {number | null} day_pnl_bp
 * @property {number | null} cash_cents
 * @property {number | null} market_value_cents
 * @property {{ count: number, buy_count: number, sell_count: number, buy_amount_cents: number, sell_amount_cents: number, fee_cents: number, realized_pnl_cents: number }} trades
 * @property {{ total: number, up: number, down: number, flat: number, limit_up: number, limit_down: number, avg_change_bp: number }} market
 * @property {{ code: string, name: string, close_cents: number, change_bp: number, limit: 'up' | 'down' | null }[]} top_gainers
 * @property {{ code: string, name: string, close_cents: number, change_bp: number, limit: 'up' | 'down' | null }[]} top_losers
 * @property {{ code: string, name: string, quantity: number, close_cents: number, change_bp: number, market_value_cents: number }[] | null} holdings 仅当前交易日；过去的日为 null
 * @property {string | null} next_open_at
 */

/** ---------- 预测卡 / 积分 / 称号（schemas/predictions.py、schemas/points.py；02 §10）---------- */

/**
 * schemas/predictions.py 题目公开形态（kind 判别）
 * @typedef {{ qid: 'dir', kind: 'bucket', target_kind: 'industry' | 'stock' | 'market', target: string | null, target_name: string | null, edges_bp: number[], from_day: number, to_day: number }
 *   | { qid: 'rank', kind: 'rank', k: number, exclude: string, candidates: string[], at_day: number }
 *   | { qid: 'rumor', kind: 'binary' }} PredictionQuestionOut
 */

/**
 * schemas/predictions.py AnswerOut
 * @typedef {Object} PredictionAnswerRecordOut
 * @property {string} qid
 * @property {number[] | null} probs
 * @property {string[] | null} order
 * @property {number | null} pick
 * @property {number | null} claimed_pct
 */

/**
 * schemas/predictions.py QuestionResultOut（挑战题的 ChallengeQuestionResultOut 另加 peer / used）
 * @typedef {Object} PredictionQuestionResultOut
 * @property {string} qid
 * @property {boolean} resolved
 * @property {boolean} void
 * @property {number | null} outcome_bucket
 * @property {number | null} change_bp
 * @property {string[] | null} true_top
 * @property {Record<string, number> | null} relevance
 * @property {Record<string, number | null> | null} candidate_change_bp
 * @property {boolean | null} truth
 * @property {number | null} score
 * @property {number | null} uniform_score
 * @property {number | null} baseline
 * @property {number | null} points
 * @property {boolean | null} hit
 */

/**
 * schemas/predictions.py PredictionCardOut
 * @typedef {Object} PredictionCardOut
 * @property {string} id
 * @property {string} save_id
 * @property {string} event_id
 * @property {EventOut | null} event
 * @property {'open' | 'answered' | 'settled' | 'expired' | 'void'} status
 * @property {number} opened_trading_tick
 * @property {number} opened_trading_day
 * @property {number} deadline_trading_tick
 * @property {number} window_days
 * @property {PredictionQuestionOut[]} questions
 * @property {PredictionAnswerRecordOut[]} answers
 * @property {PredictionQuestionResultOut[]} results
 * @property {number | null} points
 * @property {boolean} points_capped
 * @property {string | null} answered_at
 * @property {string | null} settled_at
 * @property {string} created_at
 */

/** @typedef {{ items: PredictionCardOut[], next_cursor: string | null }} PredictionCardPageOut */

/**
 * schemas/predictions.py 作答体（dir / rank / rumor 缺省即未答该题）
 * @typedef {Object} PredictionAnswersIn
 * @property {{ probs: number[] }} [dir] 5 个 int，合计 100
 * @property {{ order: string[] }} [rank] 3 个候选
 * @property {{ probs: number[] }} [rumor] 2 个 int
 */

/** @typedef {{ answers: PredictionAnswersIn, resume?: boolean }} PredictionAnswerIn resume 缺省 true */
/** @typedef {{ resume?: boolean }} PredictionSkipIn */

/**
 * schemas/predictions.py PredictionAnswerOut：{card, clock}。
 * @typedef {{ card: PredictionCardOut, clock: ClockOut }} PredictionAnswerOut
 */

/** @typedef {{ mode: 'pause' | 'off' }} PredictionSettingsIn */
/** @typedef {{ mode: 'pause' | 'off', forced: boolean }} PredictionSettingsOut */

/**
 * schemas/points.py PointsOut（GET /points、PUT /points/title）
 * @typedef {Object} PointsOut
 * @property {number} balance
 * @property {number} lifetime_earned
 * @property {number} lifetime_spent
 * @property {string | null} equipped_title
 * @property {number} today_prediction_points
 * @property {number} daily_cap
 */

/**
 * schemas/points.py LedgerEntryOut / LedgerPageOut（GET /points/ledger）
 * @typedef {Object} LedgerEntryOut
 * @property {number} seq
 * @property {number} delta
 * @property {number} balance_after
 * @property {string} reason
 * @property {string} ref
 * @property {string | null} save_id
 * @property {Record<string, unknown> | null} meta
 * @property {string} created_at
 */

/** @typedef {{ items: LedgerEntryOut[], next_cursor: string | null }} LedgerPageOut */

/**
 * schemas/points.py PredictionStatsOut（GET /points/stats）
 * @typedef {Object} PredictionStatsOut
 * @property {number} cards_answered
 * @property {number} cards_settled
 * @property {number} cards_expired
 * @property {number} total_points
 * @property {Record<string, { answered: number, scored: number, avg_score: number | null, avg_baseline: number | null }>} by_kind
 * @property {{ lo_pct: number, hi_pct: number, n: number, hits: number, avg_claimed_pct: number | null, hit_rate_pct: number | null }[]} calibration 10 档
 * @property {number | null} calibration_error_bp
 * @property {{ card_id: string, event_id: string, settled_at: string | null, avg_score: number | null, avg_baseline: number | null, points: number | null }[]} recent
 */

/**
 * schemas/points.py TitlesOut（GET /points/titles）
 * @typedef {{ items: { id: string, level: 'bronze' | 'silver' | 'gold' | 'legend', unlocked_at: string | null }[], equipped: string | null }} TitlesOut
 */

/** ---------- 每日挑战（schemas/challenges.py；03 §10）---------- */

/** @typedef {'scheduled' | 'running' | 'settled' | 'void'} ChallengeStatus */
/** @typedef {'before' | 'burst' | 'hold' | 'final' | 'ended'} ChallengePhase */
/** @typedef {'pending' | 'burst' | 'open' | 'closed' | 'resolved'} ChallengeRoundState */

/**
 * schemas/challenges.py ChallengeOut（不含 end_tt / ends_at / seed / salt / commitment_input）
 * @typedef {Object} ChallengeOut
 * @property {string} id
 * @property {string} challenge_date YYYY-MM-DD
 * @property {ChallengeStatus} status
 * @property {ChallengePhase} phase
 * @property {number | null} round_index
 * @property {number} rounds_total
 * @property {'daily' | 'compact'} schedule_mode
 * @property {string} starts_at
 * @property {string} entry_closes_at
 * @property {string} settle_expected_at 结算时间上界（不是精确结算时刻）
 * @property {string | null} next_change_at
 * @property {string} server_time
 * @property {number} tick_ms
 * @property {'v2'} clock_rules
 * @property {number} events_ruleset
 * @property {string} seed_commitment
 * @property {string} commitment_scheme
 * @property {number} participant_count
 * @property {number} public_trading_tick
 * @property {{ round_index: number, state: ChallengeRoundState, resume_at: string, closes_at: string, hold_at: string | null, event_id: string | null }[]} rounds
 * @property {ChallengeEntryOut | null} my_entry
 */

/**
 * schemas/challenges.py ChallengeEntryOut / EntryResultOut
 * @typedef {Object} ChallengeEntryOut
 * @property {string} entry_id
 * @property {string} challenge_id
 * @property {string | null} save_id 玩家存档被清理后为 null
 * @property {boolean} eligible
 * @property {string} joined_at
 * @property {number} answered_rounds
 * @property {{ final_equity_cents: number | null, return_bp: number | null, forecast_score: number, trade_score: number, total_score: number, rank: number | null, eligible_count: number, points_awarded: number } | null} result
 */

/** @typedef {{ items: ChallengeOut[], next_cursor: string | null }} ChallengeListOut */

/**
 * schemas/challenges.py ChallengeRoundCardOut（作答卡；crowd 仅截止后出现）
 * @typedef {Object} ChallengeRoundCardOut
 * @property {number} round_index
 * @property {ChallengeRoundState} state
 * @property {EventOut | null} event
 * @property {string} closes_at
 * @property {PredictionQuestionOut[]} questions
 * @property {PredictionAnswerRecordOut[]} my_answers
 * @property {number} my_revision
 * @property {(PredictionQuestionResultOut & { peer: number | null, used: 'peer' | 'baseline' | null })[]} results
 * @property {number | null} my_round_score
 * @property {{ n: number, by_qid: Record<string, { mean_probs: number[] } | { top3_counts: Record<string, number> }> } | null} crowd
 */

/** @typedef {{ items: ChallengeRoundCardOut[] }} ChallengeRoundListOut */

/**
 * schemas/challenges.py LeaderboardOut / LeaderboardItemOut
 * @typedef {Object} LeaderboardItemOut
 * @property {number} rank
 * @property {string} username
 * @property {string | null} equipped_title
 * @property {number} total_score
 * @property {number} forecast_score
 * @property {number} trade_score
 * @property {number | null} return_bp 日榜才有
 * @property {number | null} answered_rounds 日榜才有
 * @property {number | null} days_played 周/总榜才有
 * @property {boolean} is_me
 */

/**
 * @typedef {Object} LeaderboardOut
 * @property {'day' | 'week' | 'all'} scope
 * @property {string} key
 * @property {string} board
 * @property {number} eligible_count
 * @property {LeaderboardItemOut[]} items
 * @property {LeaderboardItemOut | null} me
 * @property {string | null} next_cursor
 */

/**
 * schemas/challenges.py RevealOut（挑战揭示页，已结算后才可见真实日期与事件）
 * @typedef {Object} ChallengeRevealOut
 * @property {string} challenge_id
 * @property {string} challenge_date
 * @property {'settled' | 'void'} status
 * @property {string} market_seed 十进制字符串
 * @property {string} seed_salt
 * @property {string} seed_commitment
 * @property {string} commitment_input
 * @property {number} events_ruleset
 * @property {'v2'} clock_rules
 * @property {number} format_version
 * @property {number} start_minute
 * @property {number} tick_ms
 * @property {number | null} end_tt void 为 null
 * @property {{ round_index: number, event_id: string, hold_tt: number, resolve_tts: Record<string, number>, resume_at: string, hold_at: string, closes_at: string }[]} rounds
 * @property {boolean} review_available
 */

/**
 * schemas/challenges.py ReviewOut（GET /challenges/{id}/review）
 * @typedef {Object} ChallengeReviewOut
 * @property {ChallengeOut} challenge
 * @property {ChallengeEntryOut} entry
 * @property {ChallengeRoundCardOut[]} rounds
 * @property {boolean} save_available
 */

/**
 * schemas/challenges.py ChallengeAnswerIn（PUT .../rounds/{n}/answer，不含 resume）
 * @typedef {{ answers: PredictionAnswersIn }} ChallengeAnswerIn
 */

/** ---------- 预测市场（schemas/prediction_markets.py；04 §9）---------- */

/** @typedef {'buy' | 'sell'} PmSide */
/** @typedef {'open' | 'closed' | 'resolved' | 'voided'} PmMarketStatus */

/**
 * schemas/prediction_markets.py PmMarketOut
 * @typedef {Object} PmMarketOut
 * @property {string} id
 * @property {string} challenge_id
 * @property {string} event_id
 * @property {'bucket' | 'rumor'} kind
 * @property {PmMarketStatus} status
 * @property {{ scope: 'industry' | 'stock' | 'market' | null, industry: string | null, code: string | null, stock_name: string | null, from_day: number | null, to_day: number | null, edges_bp: number[] }} question
 * @property {{ event_id: string, kind: string, scope: string | null, major: boolean, sentiment: number | null, title: string, first_seen_trading_tick: number, rumor_status: string | null }} event
 * @property {{ idx: number, key: string, price_ppm: number }[]} outcomes
 * @property {number} open_tt
 * @property {number | null} close_tt
 * @property {number | null} resolve_tt
 * @property {string | null} opens_at
 * @property {string | null} closes_at
 * @property {string | null} resolves_at
 * @property {number} trade_seq
 * @property {number} volume_shares
 * @property {number} traders
 * @property {number} liquidity_b_milli
 * @property {number} subsidy_points
 * @property {number | null} winning_outcome
 * @property {number | null} resolution_value_bp
 * @property {string | null} void_reason
 * @property {number[] | null} my_shares
 */

/** @typedef {{ items: PmMarketOut[], next_cursor: string | null, public: { challenge_id: string, public_trading_tick: number, public_trading_day: number, server_time: string } }} PmMarketPageOut */

/**
 * schemas/prediction_markets.py PmMyPositionOut / PmLimitsOut / PmMarketDetailOut
 * @typedef {Object} PmMyPositionOut
 * @property {{ idx: number, shares: number, cost_points: number, value_points: number }[]} outcomes
 * @property {number} bought_points
 * @property {number} sold_points
 * @property {number} net_cost_points
 * @property {number} value_points
 * @property {number} pnl_points
 */

/**
 * @typedef {Object} PmLimitsOut
 * @property {number} market_net_cost_cap_points
 * @property {number} market_net_cost_used_points
 * @property {number} challenge_buy_cap_points
 * @property {number} challenge_buy_used_points
 * @property {boolean} locked_ahead
 * @property {boolean} eligible
 */

/** @typedef {PmMarketOut & { q_shares: number[], window_change_bp: number | null, my: PmMyPositionOut | null, limits: PmLimitsOut, balance_points: number }} PmMarketDetailOut */

/**
 * schemas/prediction_markets.py PmQuoteOut（GET .../quote）
 * @typedef {Object} PmQuoteOut
 * @property {string} market_id
 * @property {PmSide} side
 * @property {number} outcome
 * @property {number} shares
 * @property {number} points
 * @property {number} avg_price_ppm
 * @property {number} price_before_ppm
 * @property {number[]} prices_after_ppm
 * @property {number} trade_seq
 */

/**
 * schemas/prediction_markets.py PmTradeIn（买入二选一 shares / budget_points；卖出只给 shares 与 min_proceeds_points）
 * @typedef {Object} PmTradeIn
 * @property {PmSide} side
 * @property {number} outcome 0-7
 * @property {number} [shares] 1-200
 * @property {number} [budget_points]
 * @property {number} [max_cost_points]
 * @property {number} [min_proceeds_points]
 */

/**
 * schemas/prediction_markets.py PmTradeOut / PmTradeResultOut（POST .../trades；幂等键重放时 replayed=true）
 * @typedef {Object} PmTradeOut
 * @property {string} id
 * @property {string} market_id
 * @property {number} seq
 * @property {PmSide} side
 * @property {number} outcome
 * @property {number} shares
 * @property {number} points
 * @property {number} price_before_ppm
 * @property {number[]} prices_after_ppm
 * @property {number} public_tt
 * @property {string} created_at
 */

/** @typedef {{ trade: PmTradeOut, market: PmMarketOut, my: PmMyPositionOut | null, balance_points: number, replayed: boolean }} PmTradeResultOut */

/**
 * schemas/prediction_markets.py PmHistoryOut（GET .../history）
 * @typedef {{ market_id: string, items: { seq: number, public_tt: number, at: string, prices_ppm: number[] }[] }} PmHistoryOut
 */

/**
 * schemas/prediction_markets.py PmTapePageOut（匿名成交带，不含 user；GET .../trades）
 * @typedef {{ items: { seq: number, side: PmSide, outcome: number, shares: number, points: number, public_tt: number, at: string }[], next_cursor: string | null }} PmTapePageOut
 */

/**
 * schemas/prediction_markets.py PmPositionPageOut（GET /me/prediction-positions）
 * @typedef {{ items: { market: PmMarketOut, my: PmMyPositionOut | null }[], next_cursor: string | null }} PmPositionPageOut
 */

/**
 * schemas/prediction_markets.py PmSettlementPageOut（GET /me/prediction-settlements）
 * @typedef {{ items: { market_id: string, event_id: string, kind: 'resolved' | 'voided', question: PmMarketOut['question'], market_kind: 'bucket' | 'rumor', winning_outcome: number | null, winning_shares: number, payout_points: number, net_cost_points: number, pnl_points: number, created_at: string }[], next_cursor: string | null }} PmSettlementPageOut
 */

/** ---------- 真实复盘（schemas/replay.py；05 §5.8）---------- */

/** @typedef {'pre_open' | 'open' | 'close' | 'post_close'} ReplayPhase */

/**
 * schemas/replay.py ReplayLevelOut（不含真实代码/名称，除非 masked_allowed=false）
 * @typedef {Object} ReplayLevelOut
 * @property {string} slug
 * @property {number} version
 * @property {string} title 匿名关卡为 title_masked
 * @property {string} teaser
 * @property {string | null} title_real 仅 masked_allowed=false 时给真实标题
 * @property {string[]} tags
 * @property {number} difficulty 1-3
 * @property {'curated' | 'generated' | 'custom'} kind
 * @property {number} play_days
 * @property {number} stock_count
 * @property {boolean} masked_allowed
 * @property {{ sessions: number, settled: number, best_points: number | null, best_excess_bp: number | null } | null} my_best
 */

/** @typedef {{ items: ReplayLevelOut[], next_cursor: string | null }} ReplayLevelPageOut */

/**
 * schemas/replay.py ReplaySessionOut（实名前 date / date_label 为假日历日期）
 * @typedef {Object} ReplaySessionOut
 * @property {string} save_id
 * @property {string} name
 * @property {{ slug: string, version: number, title: string }} level
 * @property {boolean} masked
 * @property {'active' | 'settled'} status
 * @property {number} day_idx
 * @property {number} play_days
 * @property {ReplayPhase} phase
 * @property {number} tick
 * @property {string} date
 * @property {string} date_label
 * @property {number} cash_cents
 * @property {number} initial_fund_cents
 * @property {number} equity_cents
 * @property {string[]} pending_question_ids
 * @property {string[]} open_question_ids
 * @property {{ final_equity_cents: number | null, return_bp: number | null, benchmark_return_bp: number | null, excess_bp: number | null, points_total: number } | null} settled
 * @property {string} created_at
 */

/** @typedef {{ items: ReplaySessionOut[] }} ReplaySessionPageOut */
/**
 * schemas/replay.py ReplaySessionCreateIn
 * @typedef {{ level_slug: string, masked?: boolean, name?: string }} ReplaySessionCreateIn
 */
/**
 * schemas/replay.py AdvanceIn
 * @typedef {{ to?: 'next_phase' | 'next_day', expected_tick: number, skip_pending?: boolean }} ReplayAdvanceIn
 */

/**
 * schemas/replay.py ReplayFeedItemOut（与 NewsOut 同名字段，外加复盘字段）
 * @typedef {Object} ReplayFeedItemOut
 * @property {string} news_id
 * @property {string} event_id
 * @property {'publish'} stage
 * @property {'announcement' | 'news' | 'policy'} kind
 * @property {null} subtype
 * @property {'market' | 'industry' | 'stock'} scope
 * @property {boolean} major
 * @property {null} sentiment
 * @property {string} title
 * @property {string | null} industry
 * @property {string | null} code
 * @property {string | null} stock_name
 * @property {number} trading_day
 * @property {number} trading_tick
 * @property {number} day_offset
 * @property {number} tick
 * @property {number} clock_minute
 * @property {'pre_open' | 'intraday' | 'post_close'} slot
 * @property {string | null} time_label
 * @property {string} date_label
 * @property {string[]} targets
 * @property {number} importance
 * @property {string} body
 * @property {string} source
 * @property {string | null} url
 */

/** @typedef {{ items: ReplayFeedItemOut[], next_cursor: string | null }} ReplayFeedPageOut */

/**
 * schemas/replay.py AdvanceOut（POST .../advance）
 * @typedef {Object} ReplayAdvanceOut
 * @property {ReplaySessionOut} session
 * @property {boolean} stale
 * @property {'phase' | 'question_open' | 'question_due' | 'settled' | null} stopped_reason
 * @property {ReplayFeedItemOut[]} new_feed_items
 * @property {string[]} scored_question_ids
 */

/**
 * schemas/replay.py ReplayQuestionOut（PUT .../answer 返回同形）
 * @typedef {Object} ReplayQuestionOut
 * @property {string} id
 * @property {'direction_bucket' | 'rank'} kind
 * @property {string} prompt
 * @property {string[]} codes
 * @property {{ label: string, lo_bp: number | null, hi_bp: number | null }[] | null} buckets
 * @property {number | null} top_k
 * @property {{ day_idx: number, phase: ReplayPhase }} opens
 * @property {{ day_idx: number, phase: ReplayPhase }} closes
 * @property {{ day_idx: number, phase: ReplayPhase }} resolves
 * @property {'open' | 'answered' | 'closed' | 'skipped' | 'scored'} status
 * @property {Record<string, unknown> | null} my_answer
 * @property {{ outcome_bucket: number | null, return_bp: number | null, returns_bp: Record<string, number> | null, true_top: string[] | null, score: number, points: number } | null} result
 */

/** @typedef {{ items: ReplayQuestionOut[] }} ReplayQuestionPageOut */
/**
 * schemas/replay.py AnswerIn（PUT .../questions/{qid}/answer；probs 或 order 二选一）
 * @typedef {{ probs?: number[] | null, order?: string[] | null }} ReplayAnswerIn
 */
/**
 * schemas/replay.py ReplayBenchmarkOut（GET .../benchmark）
 * @typedef {{ name: string, points: { trading_day: number, date: string, close: number }[] }} ReplayBenchmarkOut
 */

/**
 * schemas/replay.py RevealOut（复盘揭示页：真实代码/名称/日期）
 * @typedef {Object} ReplayRevealOut
 * @property {ReplaySessionOut} session
 * @property {string} commentary
 * @property {{ code: string, real_code: string, real_name: string, industry: string, candles: { trading_day: number, date: string, open_cents: number, high_cents: number, low_cents: number, close_cents: number, volume: number }[], play_range: number[] }[]} stocks
 * @property {ReplayBenchmarkOut} benchmark
 * @property {(ReplayFeedItemOut & { impact: Record<string, number> | null, sentiment: Record<string, unknown> | null })[]} events
 * @property {ReplayQuestionOut[]} questions
 * @property {EquityPointOut[]} equity
 * @property {number} trades_count
 * @property {number} hold_all_return_bp
 * @property {number | null} benchmark_return_bp
 */


/** ---------- 请求体（调试接口，见 schemas/debug.py）---------- */
/** @typedef {{ cash_cents: number }} DebugFundIn */
/** @typedef {{ minute_of_day: number }} DebugTimeIn 0-1439 */
/** @typedef {{ action: 'unlock' | 'lock' | 'unlock_all' | 'clear_all', ids?: string[] }} DebugAchievementsIn */

/** ---------- 健康检查 ---------- */

/** @returns {Promise<{ status: string }>} */
export const getHealthz = () => get('/healthz');
/** @returns {Promise<{ status: string }>} */
export const getReadyz = () => get('/readyz');

/** ---------- 认证 ---------- */

/**
 * @param {{ username: string, password: string }} body
 * @returns {Promise<UserOut>}
 */
export const register = (body) => post('/auth/register', { body });

/**
 * @param {{ username: string, password: string }} body
 * @returns {Promise<UserOut>}
 */
export const login = (body) => post('/auth/login', { body });

/** @returns {Promise<null>} 204 */
export const logout = () => post('/auth/logout');

/**
 * @param {{ current_password: string, new_password: string }} body
 * @returns {Promise<null>} 204
 */
export const changePassword = (body) => put('/auth/password', { body });

/** ---------- 当前用户 ---------- */

/** @returns {Promise<UserOut>} */
export const getMe = () => get('/me');

/**
 * @param {MePatch} body
 * @returns {Promise<UserOut>}
 */
export const updateMe = (body) => patch('/me', { body });

/** 注销账号。 @returns {Promise<null>} 204 */
export const deleteMe = () => del('/me');

/** ---------- 目录 ---------- */

/** @returns {Promise<StockOut[]>} 股票池（代码、名称、行业） */
export const listStocks = () => get('/stocks');

/** @returns {Promise<AchievementDefOut[]>} */
export const getAchievementCatalog = () => get('/achievements/catalog');

/** ---------- 存档 ---------- */

/** @returns {Promise<SaveOut[]>} */
export const listSaves = () => get('/saves');

/**
 * 新建存档。clock_rules 缺省为 1（v1，网页版默认）；events_enabled 缺省为 false（事件关闭）。
 * @param {{ name?: string, clock_rules?: 1 | 2, events_enabled?: boolean, initial_fund_cents?: number, buy_fee_rate?: string | number, sell_fee_rate?: string | number, t0_mode?: boolean, trade_unit?: 1 | 100 }} body 开局参数
 * @returns {Promise<SaveOut>} 201
 */
export const createSave = (body) => post('/saves', { body });

/** @param {Uuid} saveId @returns {Promise<SaveOut>} */
export const getSave = (saveId) => get(`/saves/${saveId}`);

/**
 * @param {Uuid} saveId
 * @param {{ name: string }} body 仅支持改名
 * @returns {Promise<SaveOut>}
 */
export const updateSave = (saveId, body) => patch(`/saves/${saveId}`, { body });

/** @param {Uuid} saveId @returns {Promise<null>} 204 */
export const deleteSave = (saveId) => del(`/saves/${saveId}`);

/**
 * 导出存档（版本化 JSON：format / format_version / save / stats / holdings / trades ...）。
 * 注意：不是旧版文本格式，不能直接回灌 POST /import/legacy。
 * @param {Uuid} saveId
 * @returns {Promise<Record<string, unknown>>}
 */
export const exportSave = (saveId) => get(`/saves/${saveId}/export`);

/** ---------- 行情 ---------- */

/**
 * 全市场快照；可选查询参数用于分页/搜索/排序/自选过滤，不传则行为与旧版一致（返回全部）。
 * @param {Uuid} saveId
 * @param {MarketQuery} [query]
 * @returns {Promise<MarketOut>}
 */
export const getMarket = (saveId, query = {}) =>
  get(`/saves/${saveId}/market`, {
    query: {
      limit: query.limit ?? undefined,
      cursor: query.cursor ?? undefined,
      q: query.q ?? undefined,
      sort: query.sort ?? undefined,
      order: query.order ?? undefined,
      watchlisted: query.watchlisted ?? undefined,
    },
  });

/**
 * 单只股票：QuoteOut + 日 K（candles）+ 五档（order_book）。
 * @param {Uuid} saveId
 * @param {string} code
 * @returns {Promise<StockMarketOut>}
 */
export const getStockMarket = (saveId, code) => get(`/saves/${saveId}/market/${encodeURIComponent(code)}`);

/**
 * 当日分时：从开盘到当前时钟的逐 tick 价格（服务端确定性重放）。
 * @param {Uuid} saveId
 * @param {string} code
 * @returns {Promise<IntradayOut>}
 */
export const getIntraday = (saveId, code) => get(`/saves/${saveId}/market/${encodeURIComponent(code)}/intraday`);

/** ---------- 时钟 ---------- */

/** @param {Uuid} saveId @returns {Promise<ClockOut>} */
export const pauseClock = (saveId) => post(`/saves/${saveId}/clock/pause`);
/** @param {Uuid} saveId @returns {Promise<ClockOut>} */
export const resumeClock = (saveId) => post(`/saves/${saveId}/clock/resume`);
/** @param {Uuid} saveId @returns {Promise<ClockOut>} skipped_ticks 为 0 表示无需跳过 */
export const skipClock = (saveId) => post(`/saves/${saveId}/clock/skip`);

/** ---------- 交易 ---------- */

/**
 * @param {Uuid} saveId
 * @param {OrderIn} body
 * @returns {Promise<OrderOut>}
 */
export const placeOrder = (saveId, body) => post(`/saves/${saveId}/orders`, { body });

/**
 * @param {Uuid} saveId
 * @param {{ cursor?: string | null }} [query]
 * @returns {Promise<TradePageOut>} 分页成交记录（新在前）
 */
export const listTrades = (saveId, query = {}) =>
  get(`/saves/${saveId}/trades`, { query: { cursor: query.cursor ?? undefined } });

/** @param {Uuid} saveId @returns {Promise<PortfolioOut>} */
export const getPortfolio = (saveId) => get(`/saves/${saveId}/portfolio`);

/**
 * 资产曲线（initial 起点 + 各日 close + 当日 live）。
 * @param {Uuid} saveId
 * @param {'7d' | '30d' | 'all'} [range] 默认 30d
 * @returns {Promise<EquityCurveOut>}
 */
export const getEquityCurve = (saveId, range = '30d') => get(`/saves/${saveId}/equity-curve`, { query: { range } });

/** ---------- 自选 ---------- */

/** 幂等加入自选（无 GET 列表接口：自选状态来自行情快照的 QuoteOut.watchlisted）。 @param {Uuid} saveId @param {string} code @returns {Promise<null>} 204 */
export const addWatchlistItem = (saveId, code) => put(`/saves/${saveId}/watchlist/${encodeURIComponent(code)}`);
/** 幂等移除自选。 @param {Uuid} saveId @param {string} code @returns {Promise<null>} 204 */
export const removeWatchlistItem = (saveId, code) => del(`/saves/${saveId}/watchlist/${encodeURIComponent(code)}`);

/** ---------- 自动交易 ---------- */

/** @param {Uuid} saveId @returns {Promise<AutoConfigList>} */
export const listAutoTradeConfigs = (saveId) => get(`/saves/${saveId}/auto-trade/configs`);

/**
 * @param {Uuid} saveId
 * @param {AutoConfigIn} body
 * @returns {Promise<AutoConfigOut>} 201
 */
export const createAutoTradeConfig = (saveId, body) => post(`/saves/${saveId}/auto-trade/configs`, { body });

/**
 * 全量替换一条配置。
 * @param {Uuid} saveId
 * @param {Uuid} configId
 * @param {AutoConfigIn} body
 * @returns {Promise<AutoConfigOut>}
 */
export const updateAutoTradeConfig = (saveId, configId, body) =>
  put(`/saves/${saveId}/auto-trade/configs/${configId}`, { body });

/** @param {Uuid} saveId @param {Uuid} configId @returns {Promise<null>} 204 */
export const deleteAutoTradeConfig = (saveId, configId) => del(`/saves/${saveId}/auto-trade/configs/${configId}`);

/** @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const getAutoTradeStatus = (saveId) => get(`/saves/${saveId}/auto-trade/status`);

/** @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const startAutoTrade = (saveId) => post(`/saves/${saveId}/auto-trade/start`);
/** @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const pauseAutoTrade = (saveId) => post(`/saves/${saveId}/auto-trade/pause`);
/** @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const resumeAutoTrade = (saveId) => post(`/saves/${saveId}/auto-trade/resume`);
/** @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const stopAutoTrade = (saveId) => post(`/saves/${saveId}/auto-trade/stop`);
/** 清空配置、事件与统计并停止。 @param {Uuid} saveId @returns {Promise<AutoStatusOut>} */
export const resetAutoTrade = (saveId) => post(`/saves/${saveId}/auto-trade/reset`);

/**
 * 事件日志（倒序分页）。
 * @param {Uuid} saveId
 * @param {{ cursor?: string | null, limit?: number }} [query]
 * @returns {Promise<AutoEventPage>}
 */
export const listAutoTradeEvents = (saveId, query = {}) =>
  get(`/saves/${saveId}/auto-trade/events`, {
    query: { cursor: query.cursor ?? undefined, limit: query.limit ?? undefined },
  });

/** ---------- 成就 ---------- */

/** @param {Uuid} saveId @returns {Promise<SaveAchievementOut[]>} */
export const getSaveAchievements = (saveId) => get(`/saves/${saveId}/achievements`);

/** ---------- 导入 ---------- */

/**
 * 导入旧版（legacy）数据，服务端校验并挂到当前用户。
 * content 可以是单用户导出文本，也可以是整包 localStorage `stock_simulator_users`（用户映射，全部存档导入）。
 * @param {{ content: string }} body 旧版文本（base64+XOR 或明文 JSON）
 * @returns {Promise<LegacyImportOut>}
 */
export const importLegacy = (body) => post('/import/legacy', { body });

/** ---------- 调试（仅 ENABLE_DEBUG_API=true 时可用，否则 403 DEBUG_DISABLED） ---------- */

/** @param {Uuid} saveId @param {DebugFundIn} body @returns {Promise<DebugResultOut>} */
export const debugFund = (saveId, body) => post(`/saves/${saveId}/debug/fund`, { body });
/** @param {Uuid} saveId @param {DebugTimeIn} body @returns {Promise<DebugResultOut>} */
export const debugTime = (saveId, body) => post(`/saves/${saveId}/debug/time`, { body });
/** @param {Uuid} saveId @param {DebugAchievementsIn} body @returns {Promise<DebugResultOut>} */
export const debugAchievements = (saveId, body) => post(`/saves/${saveId}/debug/achievements`, { body });
/** @param {Uuid} saveId @returns {Promise<DebugResultOut>} */
export const debugResetMarket = (saveId) => post(`/saves/${saveId}/debug/reset-market`);
/** @param {Uuid} saveId @returns {Promise<DebugResultOut>} */
export const debugClear = (saveId) => post(`/saves/${saveId}/debug/clear`);

/** ---------- 事件行情（01 §8.1）---------- */

/**
 * 快讯流（倒序分页）。query 全可选：major / code / industry / watchlisted。
 * @param {Uuid} saveId
 * @param {{ limit?: number, cursor?: string | null, major?: boolean, code?: string, industry?: string, watchlisted?: boolean }} [query]
 * @returns {Promise<NewsPageOut>}
 */
export const getNews = (saveId, query = {}) => get(`/saves/${saveId}/news`, { query });

/**
 * 事件列表（倒序分页）。
 * @param {Uuid} saveId
 * @param {{ limit?: number, cursor?: string | null, major?: boolean, code?: string, industry?: string }} [query]
 * @returns {Promise<EventPageOut>}
 */
export const listEvents = (saveId, query = {}) => get(`/saves/${saveId}/events`, { query });

/** @param {Uuid} saveId @param {string} eventId @returns {Promise<EventDetailOut>} */
export const getEvent = (saveId, eventId) => get(`/saves/${saveId}/events/${encodeURIComponent(eventId)}`);

/** 某只股票的事件标记（K 线叠加用）。 @param {Uuid} saveId @param {string} code @returns {Promise<EventMarksOut>} */
export const getEventMarks = (saveId, code) => get(`/saves/${saveId}/market/${encodeURIComponent(code)}/event-marks`);

/** 产业链图（节点 + 关系边，含已揭示层级）。 @param {Uuid} saveId @returns {Promise<SupplyChainOut>} */
export const getSupplyChain = (saveId) => get(`/saves/${saveId}/supply-chain`);

/**
 * 收盘小结；缺省为当前交易日。
 * @param {Uuid} saveId
 * @param {number} [tradingDay]
 * @returns {Promise<DaySummaryOut>}
 */
export const getDaySummary = (saveId, tradingDay) =>
  get(`/saves/${saveId}/day-summary`, { query: { trading_day: tradingDay } });

/** ---------- 预测卡（02 §10.1）---------- */

/**
 * @param {Uuid} saveId
 * @param {{ status?: 'open' | 'answered' | 'settled' | 'expired' | 'void' | 'all', limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<PredictionCardPageOut>}
 */
export const listPredictions = (saveId, query = {}) => get(`/saves/${saveId}/predictions`, { query });

/** @param {Uuid} saveId @returns {Promise<PredictionSettingsOut>} */
export const getPredictionSettings = (saveId) => get(`/saves/${saveId}/predictions/settings`);

/** @param {Uuid} saveId @param {PredictionSettingsIn} body @returns {Promise<PredictionSettingsOut>} */
export const updatePredictionSettings = (saveId, body) => put(`/saves/${saveId}/predictions/settings`, { body });

/** @param {Uuid} saveId @param {Uuid} cardId @returns {Promise<PredictionCardOut>} */
export const getPrediction = (saveId, cardId) => get(`/saves/${saveId}/predictions/${cardId}`);

/** @param {Uuid} saveId @param {Uuid} cardId @param {PredictionAnswerIn} body @returns {Promise<PredictionAnswerOut>} */
export const answerPrediction = (saveId, cardId, body) => post(`/saves/${saveId}/predictions/${cardId}/answer`, { body });

/** 仅 open 卡可跳过（→ expired，不发积分）。 @param {Uuid} saveId @param {Uuid} cardId @param {PredictionSkipIn} [body] @returns {Promise<PredictionAnswerOut>} */
export const skipPrediction = (saveId, cardId, body) =>
  post(`/saves/${saveId}/predictions/${cardId}/skip`, body === undefined ? undefined : { body });

/** ---------- 情报卡（02 §10.1）---------- */

/** @param {Uuid} saveId @returns {Promise<IntelStateOut>} */
export const getIntel = (saveId) => get(`/saves/${saveId}/intel`);

/** @param {Uuid} saveId @param {{ edge_id: string, level: 1 | 2 }} body @returns {Promise<IntelPurchaseOut>} */
export const buyIntelEdge = (saveId, body) => post(`/saves/${saveId}/intel/edges`, { body });

/** @param {Uuid} saveId @param {{ event_id: string }} body @returns {Promise<IntelPurchaseOut>} */
export const buyRumorHint = (saveId, body) => post(`/saves/${saveId}/intel/rumor-hints`, { body });

/** ---------- 积分 / 称号（02 §10.1）---------- */

/** @returns {Promise<PointsOut>} */
export const getPoints = () => get('/points');

/**
 * @param {{ limit?: number, cursor?: string | null, reason?: string[] }} [query]
 * @returns {Promise<LedgerPageOut>}
 */
export const getPointsLedger = (query = {}) => get('/points/ledger', { query });

/**
 * 预测统计；传 save_id 时只统计该存档（他人存档 404）。
 * @param {Uuid} [saveId]
 * @returns {Promise<PredictionStatsOut>}
 */
export const getPredictionStats = (saveId) => get('/points/stats', { query: { save_id: saveId } });

/** @returns {Promise<TitlesOut>} */
export const getTitles = () => get('/points/titles');

/** @param {{ title_id: string | null }} body @returns {Promise<PointsOut>} */
export const setTitle = (body) => put('/points/title', { body });

/** ---------- 每日挑战（03 §10.1）---------- */

/** @returns {Promise<ChallengeOut>} */
export const getTodayChallenge = () => get('/challenges/today');

/**
 * @param {{ limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<ChallengeListOut>}
 */
export const listChallenges = (query = {}) => get('/challenges', { query });

/** @param {Uuid} challengeId @returns {Promise<ChallengeOut>} */
export const getChallenge = (challengeId) => get(`/challenges/${challengeId}`);

/** @param {Uuid} challengeId @returns {Promise<ChallengeRoundListOut>} */
export const listChallengeRounds = (challengeId) => get(`/challenges/${challengeId}/rounds`);

/** 报名（幂等）。 @param {Uuid} challengeId @returns {Promise<ChallengeEntryOut>} */
export const enterChallenge = (challengeId) => post(`/challenges/${challengeId}/entry`);

/**
 * 提交某回合作答（可多次修订，my_revision 递增）。
 * @param {Uuid} challengeId
 * @param {number} roundIndex 1-10
 * @param {ChallengeAnswerIn} body
 * @returns {Promise<ChallengeRoundCardOut>}
 */
export const answerChallengeRound = (challengeId, roundIndex, body) =>
  put(`/challenges/${challengeId}/rounds/${roundIndex}/answer`, { body });

/**
 * 当日榜。
 * @param {Uuid} challengeId
 * @param {{ board?: 'total' | 'forecast' | 'trade', limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<LeaderboardOut>}
 */
export const getChallengeLeaderboard = (challengeId, query = {}) =>
  get(`/challenges/${challengeId}/leaderboard`, { query });

/**
 * 周榜 / 总榜。
 * @param {{ scope?: 'week' | 'all', week?: string, sort?: 'sum' | 'avg', limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<LeaderboardOut>}
 */
export const getChallengePeriodLeaderboard = (query = {}) => get('/challenge-leaderboard', { query });

/** 揭示页（已结算后才有真实日期与事件）。 @param {Uuid} challengeId @returns {Promise<ChallengeRevealOut>} */
export const getChallengeReveal = (challengeId) => get(`/challenges/${challengeId}/reveal`);

/** 复盘页。 @param {Uuid} challengeId @returns {Promise<ChallengeReviewOut>} */
export const getChallengeReview = (challengeId) => get(`/challenges/${challengeId}/review`);

/** ---------- 预测市场（04 §9.2；全服，独立于存档）---------- */

/**
 * @param {{ challenge_id?: string, status?: 'all' | 'open' | 'closed' | 'resolved' | 'voided', limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<PmMarketPageOut>}
 */
export const listPredictionMarkets = (query = {}) => get('/prediction-markets', { query });

/** @param {Uuid} marketId @returns {Promise<PmMarketDetailOut>} */
export const getPredictionMarket = (marketId) => get(`/prediction-markets/${marketId}`);

/**
 * 报价（不成交）：买入给 shares 或 budget_points，卖出给 shares。
 * @param {Uuid} marketId
 * @param {{ side: PmSide, outcome: number, shares?: number, budget_points?: number }} query
 * @returns {Promise<PmQuoteOut>}
 */
export const quotePredictionMarket = (marketId, query) => get(`/prediction-markets/${marketId}/quote`, { query });

/**
 * 下单。Idempotency-Key 必填（≤64 字符），重放时返回 replayed=true。
 * @param {Uuid} marketId
 * @param {PmTradeIn} body
 * @param {string} idempotencyKey
 * @returns {Promise<PmTradeResultOut>}
 */
export const placePredictionTrade = (marketId, body, idempotencyKey) =>
  post(`/prediction-markets/${marketId}/trades`, { body, headers: { 'Idempotency-Key': idempotencyKey } });

/** @param {Uuid} marketId @param {{ max_points?: number }} [query] @returns {Promise<PmHistoryOut>} */
export const getPredictionMarketHistory = (marketId, query = {}) =>
  get(`/prediction-markets/${marketId}/history`, { query });

/** 匿名成交带。 @param {Uuid} marketId @param {{ cursor?: string | null }} [query] @returns {Promise<PmTapePageOut>} */
export const getPredictionMarketTape = (marketId, query = {}) => get(`/prediction-markets/${marketId}/trades`, { query });

/** 我的持仓。 @param {{ status?: 'active' | 'settled', cursor?: string | null }} [query] @returns {Promise<PmPositionPageOut>} */
export const listMyPredictionPositions = (query = {}) => get('/me/prediction-positions', { query });

/** 我的结算记录。 @param {{ cursor?: string | null }} [query] @returns {Promise<PmSettlementPageOut>} */
export const listMyPredictionSettlements = (query = {}) => get('/me/prediction-settlements', { query });

/** ---------- 真实复盘（05 §5.8；/api/v1/replay）---------- */

/**
 * @param {{ tag?: string, difficulty?: 1 | 2 | 3, limit?: number, cursor?: string | null }} [query]
 * @returns {Promise<ReplayLevelPageOut>}
 */
export const listReplayLevels = (query = {}) => get('/replay/levels', { query });

/** @param {string} slug @returns {Promise<ReplayLevelOut>} */
export const getReplayLevel = (slug) => get(`/replay/levels/${encodeURIComponent(slug)}`);

/** @param {ReplaySessionCreateIn} body @returns {Promise<ReplaySessionOut>} 201 */
export const createReplaySession = (body) => post('/replay/sessions', { body });

/** @returns {Promise<ReplaySessionPageOut>} */
export const listReplaySessions = () => get('/replay/sessions');

/** @param {Uuid} saveId @returns {Promise<ReplaySessionOut>} */
export const getReplaySession = (saveId) => get(`/replay/sessions/${saveId}`);

/**
 * 推进到下一阶段或下一日；expected_tick 用于并发保护。
 * @param {Uuid} saveId
 * @param {ReplayAdvanceIn} body
 * @returns {Promise<ReplayAdvanceOut>}
 */
export const advanceReplaySession = (saveId, body) => post(`/replay/sessions/${saveId}/advance`, { body });

/** @param {Uuid} saveId @returns {Promise<ReplaySessionOut>} */
export const finishReplaySession = (saveId) => post(`/replay/sessions/${saveId}/finish`);

/** @param {Uuid} saveId @param {{ cursor?: string | null, limit?: number }} [query] @returns {Promise<ReplayFeedPageOut>} */
export const getReplayFeed = (saveId, query = {}) => get(`/replay/sessions/${saveId}/feed`, { query });

/** @param {Uuid} saveId @returns {Promise<ReplayQuestionPageOut>} */
export const listReplayQuestions = (saveId) => get(`/replay/sessions/${saveId}/questions`);

/**
 * @param {Uuid} saveId
 * @param {string} questionId
 * @param {ReplayAnswerIn} body
 * @returns {Promise<ReplayQuestionOut>}
 */
export const answerReplayQuestion = (saveId, questionId, body) =>
  put(`/replay/sessions/${saveId}/questions/${encodeURIComponent(questionId)}/answer`, { body });

/** @param {Uuid} saveId @returns {Promise<ReplayBenchmarkOut>} */
export const getReplayBenchmark = (saveId) => get(`/replay/sessions/${saveId}/benchmark`);

/** 揭示页（结算后）。 @param {Uuid} saveId @returns {Promise<ReplayRevealOut>} */
export const getReplayReveal = (saveId) => get(`/replay/sessions/${saveId}/reveal`);
