/**
 * market 纯逻辑（无 DOM、无网络，可单测）。
 *
 * - 金额一律整数分（*_cents），change_bp 为整数基点（1bp = 0.01%）。
 * - 归一化函数把 REST / WebSocket 的原始数据收敛为本模块的内部形态，
 *   字段缺失时给出安全默认值，不抛异常。
 * - 时钟文案与交易时段移植自 legacy/game.js 1752-2007；列表过滤排序移植自 2187-2295。
 *
 * @typedef {Object} Quote
 * @property {string} code
 * @property {number} price_cents
 * @property {number} change_bp 相对昨收的涨跌（基点）
 * @property {number} volume 当日成交量（股）
 * @property {number | null} prev_close_cents 昨收（仅快照/详情提供时有值）
 * @property {string} [name]
 *
 * @typedef {Object} StockMeta 股票池条目（GET /stocks 的 StockOut）
 * @property {string} code
 * @property {string} name
 * @property {string} industry
 * @property {string} profile 后端不提供，恒为 'normal'（保留字段以兼容 UI 分支）
 *
 * @typedef {{ field: 'name' | 'price' | 'change' | null, order: 'asc' | 'desc' }} SortState
 */

export const DAY_MINUTES = 1440;
/** 上午盘 9:30-11:30、下午盘 13:00-15:00（含端点）。 */
export const MORNING_SESSION = Object.freeze([570, 690]);
export const AFTERNOON_SESSION = Object.freeze([780, 900]);
/** 早起的鸟儿 9:30-9:35、夜猫子 11:35-11:40、下午开盘 13:00-13:05（legacy 1798-1812 的分钟窗口）。 */
export const EARLY_BIRD_WINDOW = Object.freeze([570, 575]);
export const NIGHT_OWL_WINDOW = Object.freeze([695, 700]);
export const AFTERNOON_OPEN_WINDOW = Object.freeze([780, 785]);
/** 涨跌停幅度 10%（与 backend domain/rules.py 的 LIMIT_PCT_BP 一致）。 */
export const LIMIT_PCT_BP = 1000;
const BP_DENOMINATOR = 10000;

/** @param {unknown} v @returns {v is number} */
const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

/**
 * 整数除法四舍五入（半数向远离零方向），仅用于非负/负整数分与基点计算。
 * @param {number} n
 * @param {number} d 正整数
 */
export function roundHalfUpDiv(n, d) {
  const sign = n < 0 ? -1 : 1;
  return sign * Math.floor((Math.abs(n) * 2 + d) / (2 * d));
}

/**
 * @param {number | null | undefined} cents
 * @returns {string} 元，两位小数；缺失时 "--"
 */
export function centsText(cents) {
  return isInt(cents) ? (cents / 100).toFixed(2) : '--';
}

/**
 * 涨跌幅文本（基点 -> 百分数，两位小数，正数带 +）。
 * @param {number} bp
 */
export function changeText(bp) {
  const pct = (bp / 100).toFixed(2);
  return bp >= 0 ? `+${pct}%` : `${pct}%`;
}

/** @param {number} bp @returns {'up' | 'down'} */
export function changeDirection(bp) {
  return bp >= 0 ? 'up' : 'down';
}

/**
 * 涨停 / 跌停价（分），按昨收 ±10% 四舍五入到分。
 * @param {number} prevCloseCents
 * @returns {{ up: number, down: number }}
 */
export function limitPrices(prevCloseCents) {
  return {
    up: roundHalfUpDiv(prevCloseCents * (BP_DENOMINATOR + LIMIT_PCT_BP), BP_DENOMINATOR),
    down: roundHalfUpDiv(prevCloseCents * (BP_DENOMINATOR - LIMIT_PCT_BP), BP_DENOMINATOR),
  };
}

/**
 * 解析时钟：整数分钟（0-1439）或 "HH:MM"。无效返回 null。
 * @param {unknown} v
 * @returns {number | null}
 */
export function parseClock(v) {
  if (isInt(v)) return v >= 0 && v < DAY_MINUTES ? v : null;
  if (typeof v === 'string') {
    const m = /^(\d{1,2}):(\d{2})$/.exec(v.trim());
    if (m) {
      const minute = Number(m[1]) * 60 + Number(m[2]);
      return minute < DAY_MINUTES ? minute : null;
    }
  }
  return null;
}

/** @param {number} minute @returns {string} "HH:MM" */
export function clockLabel(minute) {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/** @param {number} minute */
export function isTradingMinute(minute) {
  const inRange = ([lo, hi]) => minute >= lo && minute <= hi;
  return inRange(MORNING_SESSION) || inRange(AFTERNOON_SESSION);
}

/**
 * 时钟状态文案 key 与 CSS class（优先级同 legacy：暂停 > 三个特殊窗口 > 非交易 > 正常）。
 * @param {number | null} minute
 * @param {boolean} paused
 * @returns {{ key: string, cls: string }}
 */
export function clockStatus(minute, paused) {
  if (minute === null) return { key: '', cls: 'status' };
  if (paused) return { key: 'marketStatus.paused', cls: 'status paused' };
  const inRange = ([lo, hi]) => minute >= lo && minute <= hi;
  if (inRange(EARLY_BIRD_WINDOW)) return { key: 'marketStatus.earlyBird', cls: 'status early' };
  if (inRange(NIGHT_OWL_WINDOW)) return { key: 'marketStatus.nightOwl', cls: 'status late' };
  if (inRange(AFTERNOON_OPEN_WINDOW)) return { key: 'marketStatus.afternoonOpen', cls: 'status afternoon' };
  if (!isTradingMinute(minute)) return { key: 'marketStatus.notTrading', cls: 'status' };
  return { key: 'marketStatus.normal', cls: 'status' };
}

/**
 * 把任意报价对象归一化为 Quote；缺失 code 或 price_cents 时返回 null。
 * @param {any} raw
 * @returns {Quote | null}
 */
export function normalizeQuote(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const code = typeof raw.code === 'string' ? raw.code : null;
  if (!code || !isInt(raw.price_cents)) return null;
  const prev = isInt(raw.prev_close_cents) && raw.prev_close_cents > 0 ? raw.prev_close_cents : null;
  let bp = isInt(raw.change_bp) ? raw.change_bp : null;
  if (bp === null) {
    bp = prev ? roundHalfUpDiv((raw.price_cents - prev) * BP_DENOMINATOR, prev) : 0;
  }
  return {
    code,
    price_cents: raw.price_cents,
    change_bp: bp,
    volume: isInt(raw.volume) ? raw.volume : 0,
    prev_close_cents: prev,
    ...(typeof raw.name === 'string' ? { name: raw.name } : {}),
  };
}

/**
 * 归一化 WebSocket 消息（api/ws.py）：
 * {"t":"tick","tick":n,"advanced":k,"clock":{"minute","trading_day","paused","trading"},"full":bool,
 *  "q":[[code, price_cents, change_bp, volume], ...]}。
 * 非 tick 消息或结构不合法返回 null。
 * @param {any} msg
 * @returns {{ tick: number | null, minuteOfDay: number | null, paused: boolean | null, quotes: Quote[] } | null}
 */
export function normalizeTick(msg) {
  if (!msg || msg.t !== 'tick' || !Array.isArray(msg.q)) return null;
  /** @type {Quote[]} */
  const quotes = [];
  for (const row of msg.q) {
    if (!Array.isArray(row)) continue;
    const [code, price, bp, volume] = row;
    if (typeof code !== 'string' || !isInt(price)) continue;
    quotes.push({
      code,
      price_cents: price,
      change_bp: isInt(bp) ? bp : 0,
      volume: isInt(volume) ? volume : 0,
      prev_close_cents: null,
    });
  }
  const clock = msg.clock && typeof msg.clock === 'object' ? msg.clock : {};
  return {
    tick: isInt(msg.tick) ? msg.tick : null,
    minuteOfDay: parseClock(clock.minute),
    paused: typeof clock.paused === 'boolean' ? clock.paused : null,
    quotes,
  };
}

/**
 * 归一化市场快照 GET /saves/{id}/market（MarketOut：时钟字段 + stocks: QuoteOut[]）。
 * 自选列表由各报价的 watchlisted 标记得出（后端无自选列表接口）。
 * @param {any} raw
 * @returns {{ tick: number | null, tradingDay: number | null, minuteOfDay: number | null, paused: boolean | null, quotes: Quote[], watchlist: string[] }}
 */
export function normalizeSnapshot(raw) {
  const list = Array.isArray(raw?.stocks) ? raw.stocks : [];
  const quotes = [];
  const watchlist = [];
  for (const item of list) {
    const q = normalizeQuote(item);
    if (!q) continue;
    quotes.push(q);
    if (item.watchlisted === true) watchlist.push(q.code);
  }
  return {
    tick: isInt(raw?.tick) ? raw.tick : null,
    tradingDay: isInt(raw?.trading_day) ? raw.trading_day : null,
    minuteOfDay: parseClock(raw?.clock_minute),
    paused: typeof raw?.paused === 'boolean' ? raw.paused : null,
    quotes,
    watchlist,
  };
}

/**
 * @param {any} raw 股票池条目（StockOut）
 * @returns {StockMeta | null}
 */
export function normalizeStockMeta(raw) {
  if (!raw || typeof raw.code !== 'string') return null;
  return {
    code: raw.code,
    name: typeof raw.name === 'string' ? raw.name : raw.code,
    industry: typeof raw.industry === 'string' ? raw.industry : '',
    profile: 'normal',
  };
}

/**
 * 把 Quote 合并进已有报价（保留之前拿到的 name、prev_close）。
 * @param {Quote | undefined} prev
 * @param {Quote} next
 * @returns {Quote}
 */
export function mergeQuote(prev, next) {
  if (!prev) return next;
  return {
    ...prev,
    price_cents: next.price_cents,
    change_bp: next.change_bp,
    volume: next.volume,
    prev_close_cents: next.prev_close_cents ?? prev.prev_close_cents,
  };
}

/** 三态排序切换（同 legacy handleSortClick）：升序 -> 降序 -> 取消。 @param {SortState} sort @param {'name'|'price'|'change'} field */
export function nextSort(sort, field) {
  if (sort.field !== field) return { field, order: 'asc' };
  if (sort.order === 'asc') return { field, order: 'desc' };
  return { field: null, order: 'asc' };
}

/**
 * 计算列表应显示的股票代码顺序：先过滤（搜索 / 仅自选），再排序。
 * @param {{
 *   stockList: StockMeta[],
 *   quotes: Map<string, Quote>,
 *   search: string,
 *   watchlist: string[],
 *   watchlistMode: boolean,
 *   sort: SortState,
 * }} input
 * @returns {string[]}
 */
export function visibleCodes(input) {
  const { stockList, quotes, search, watchlist, watchlistMode, sort } = input;
  const keyword = search.trim();
  const watched = new Set(watchlist);
  const base = stockList.length
    ? stockList
    : [...quotes.values()].map((q) => ({ code: q.code, name: q.name ?? q.code, industry: '', profile: '' }));

  let rows = base.filter((s) => {
    if (keyword && !s.code.includes(keyword) && !s.name.includes(keyword)) return false;
    if (watchlistMode && !watched.has(s.code)) return false;
    return true;
  });

  if (sort.field) {
    const dir = sort.order === 'asc' ? 1 : -1;
    /** @param {StockMeta} s */
    const value = (s) => {
      const q = quotes.get(s.code);
      if (sort.field === 'price') return q ? q.price_cents : 0;
      if (sort.field === 'change') return q ? q.change_bp : 0;
      return 0;
    };
    rows = [...rows];
    if (sort.field === 'name') {
      rows.sort((a, b) => dir * a.name.localeCompare(b.name));
    } else {
      rows.sort((a, b) => dir * (value(a) - value(b)));
    }
  }
  return rows.map((s) => s.code);
}

/**
 * 把 GET /saves/{id}/market/{code}（StockMarketOut）归一化为 Detail。
 * 盘口 order_book.bids/asks 按档位从近到远排列（bids[0] = 买一，asks[0] = 卖一）；
 * 日 K candles（trading_day/date/open_cents/high_cents/low_cents/close_cents/volume）映射为 history，最旧在前。
 * @param {any} raw
 * @returns {Detail | null}
 */
export function normalizeDetail(raw) {
  if (!raw || typeof raw.code !== 'string' || !isInt(raw.price_cents)) return null;
  const prev = isInt(raw.prev_close_cents) && raw.prev_close_cents > 0 ? raw.prev_close_cents : null;
  const limits = prev ? limitPrices(prev) : null;
  const levels = (list) =>
    (Array.isArray(list) ? list : [])
      .filter((l) => l && isInt(l.price_cents))
      .slice(0, 5)
      .map((l) => ({ price_cents: l.price_cents, volume: isInt(l.volume) ? l.volume : 0 }));
  const book = raw.order_book && typeof raw.order_book === 'object' ? raw.order_book : {};
  const history = (Array.isArray(raw.candles) ? raw.candles : [])
    .filter((c) => c && isInt(c.open_cents) && isInt(c.high_cents) && isInt(c.low_cents) && isInt(c.close_cents))
    .map((c) => ({
      date: typeof c.date === 'string' ? c.date : '',
      open: c.open_cents,
      high: c.high_cents,
      low: c.low_cents,
      close: c.close_cents,
      volume: isInt(c.volume) ? c.volume : 0,
    }));
  const quote = normalizeQuote(raw);
  return {
    code: raw.code,
    name: typeof raw.name === 'string' ? raw.name : raw.code,
    price_cents: raw.price_cents,
    change_bp: quote ? quote.change_bp : 0,
    volume: quote ? quote.volume : 0,
    prev_close_cents: prev,
    limit_up_cents: isInt(raw.limit_up_cents) ? raw.limit_up_cents : limits?.up ?? null,
    limit_down_cents: isInt(raw.limit_down_cents) ? raw.limit_down_cents : limits?.down ?? null,
    bids: levels(book.bids),
    asks: levels(book.asks),
    history,
  };
}

/**
 * 把一条 tick 报价应用到当前详情（只更新价格类字段，盘口等待下一次详情刷新）。
 * @param {Detail | null} detail
 * @param {Quote} q
 * @returns {Detail | null}
 */
export function applyQuoteToDetail(detail, q) {
  if (!detail || detail.code !== q.code) return detail;
  return { ...detail, price_cents: q.price_cents, change_bp: q.change_bp, volume: q.volume };
}

/**
 * @typedef {Object} Detail
 * @property {string} code
 * @property {string} name
 * @property {number} price_cents
 * @property {number} change_bp
 * @property {number} volume
 * @property {number | null} prev_close_cents
 * @property {number | null} limit_up_cents
 * @property {number | null} limit_down_cents
 * @property {{ price_cents: number, volume: number }[]} bids
 * @property {{ price_cents: number, volume: number }[]} asks
 * @property {{ date: string, open: number, high: number, low: number, close: number, volume: number }[]} history
 */
