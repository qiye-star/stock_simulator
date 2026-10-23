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
 * @property {string} created_at ISO 8601 UTC
 */

/**
 * schemas/user.py MePatch（部分更新）
 * @typedef {Object} MePatch
 * @property {Theme} [theme]
 * @property {Lang} [lang]
 * @property {number} [refresh_rate_ms] 500-60000
 * @property {boolean} [tutorial_completed]
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
 * WebSocket 服务端消息（api/ws.py）。tick 帧：
 * `{t:'tick', tick, advanced, clock:{minute, trading_day, paused, trading}, full, q:[[code, price_cents, change_bp, volume], ...]}`
 * q 只含相对上一帧变化的股票（首帧 full=true 为全量）。
 * @typedef {{ t: 'tick', tick: number, advanced: number, clock: { minute: number, trading_day: number, paused: boolean, trading: boolean }, full: boolean, q: [string, number, number, number][] }
 *   | { t: 'trade', seq: number, count: number }
 *   | { t: 'achievement', ids: string[] }
 *   | { t: 'auto_event', count: number, trades: number }
 *   | { t: 'subscribed' | 'unsubscribed', code: string }
 *   | { t: 'pong' }
 *   | { t: 'error', code: string }} WsServerMessage
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
 * @param {{ name?: string, initial_fund_cents?: number, buy_fee_rate?: string | number, sell_fee_rate?: string | number, t0_mode?: boolean, trade_unit?: 1 | 100 }} body 开局参数
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
