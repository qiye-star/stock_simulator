/**
 * 内存状态 + 假 API（模拟后端行为，便于以后替换为真实请求）。
 *
 * 方法名与 REST 端点一一对应（见 docs/CONTRACT.md）：
 *   market()          ≈ GET  /saves/{id}/market
 *   quote(code)       ≈ GET  /saves/{id}/market/{code}（含 _series/_candles 与 order_book）
 *   portfolio()       ≈ GET  /saves/{id}/portfolio
 *   placeOrder(body)  ≈ POST /saves/{id}/orders，失败抛 {code, params}
 *   trades()          ≈ GET  /saves/{id}/trades
 *   toggleWatch(code) ≈ PUT|DELETE /saves/{id}/watchlist/{code}
 *   autoConfigs / autoSave / autoDelete / autoControl ≈ /auto-trade/*
 *   listQuotes(opts)  ≈ GET  /saves/{id}/market?limit&cursor&q&sort&order&watchlisted（假数据版：本地过滤/排序/偏移游标）
 * 行情每 refresh_rate_ms 推进一个 tick（≈ WebSocket "tick" 消息），触发 "tick" 事件。
 *
 * 本文件是“假数据模式”（?mock=1 / file://）的实现；真实模式由 store.real.js 覆盖 SS.store，方法签名一致。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const M = SS.mock;

  const listeners = {};
  const on = (evt, fn) => {
    (listeners[evt] = listeners[evt] || new Set()).add(fn);
    return () => listeners[evt].delete(fn);
  };
  const emit = (evt, payload) => (listeners[evt] || []).forEach((fn) => fn(payload));

  const state = {
    clock: M.clock,
    stocks: M.stocks,
    byCode: Object.fromEntries(M.stocks.map((s) => [s.code, s])),
    save: M.save,
    cash_cents: M.cash_cents,
    holdings: M.holdings,
    trades: M.trades,
    equity_history: M.equity_history,
    auto: { configs: M.auto_configs, status: M.auto_status, events: M.auto_events },
    user: M.user,
    seq: M.nextSeq,
    todayStartEquity: null,
  };

  class ApiError extends Error {
    constructor(code, params = {}) {
      super(code);
      this.code = code;
      this.params = params;
    }
  }

  // ---------- 行情 ----------
  const quote = (code) => state.byCode[code];

  function market() {
    const { stocks, clock } = state;
    return { ...clock, stocks };
  }

  /** 五档盘口（OrderBookOut），围绕现价生成 */
  function orderBook(code) {
    const q = quote(code);
    const step = Math.max(1, Math.round(q.price_cents * 0.0004));
    const lvl = (i, side) => ({
      price_cents: q.price_cents + (side === "ask" ? i : -(i - 1)) * step,
      volume: 100 * (((q.price_cents * (i + 3) * (side === "ask" ? 7 : 11)) % 97) + 3),
    });
    return {
      asks: [1, 2, 3, 4, 5].map((i) => lvl(i, "ask")),
      bids: [1, 2, 3, 4, 5].map((i) => lvl(i, "bid")),
    };
  }

  const isTrading = () => !state.clock.paused && state.clock.session !== "closed";

  /** 与后端 session_label 对齐 */
  function sessionLabel(m) {
    if (m >= 570 && m <= 575) return "early_bird";
    if (m >= 695 && m <= 700) return "night_owl";
    if (m >= 780 && m <= 785) return "afternoon_open";
    if ((m >= 570 && m <= 690) || (m >= 780 && m <= 900)) return "trading";
    return "closed";
  }

  /** 推进一个 tick：随机游走 ±0.35%，钳制在涨跌停内，午休直接跳到 13:00 */
  function step() {
    const c = state.clock;
    if (c.paused || c.session === "closed") return;
    c.tick += 1;
    c.clock_minute += 1;
    if (c.clock_minute > 690 && c.clock_minute < 780) c.clock_minute = 780;
    c.session = sessionLabel(c.clock_minute);
    const changed = [];
    for (const s of state.stocks) {
      const prev = s.price_cents;
      const bias = s.code === "999999" ? 0.0006 : 0; // 影视飓风：偏多头彩蛋（profile=bull_bias）
      let p = Math.round(prev * (1 + (Math.random() - 0.5) * 0.007 + bias));
      p = Math.min(s.limit_up_cents, Math.max(s.limit_down_cents, p));
      s.price_cents = p;
      s.high_cents = Math.max(s.high_cents, p);
      s.low_cents = Math.min(s.low_cents, p);
      s.volume += Math.round(Math.random() * 40000);
      s.change_bp = Math.round(((p - s.prev_close_cents) / s.prev_close_cents) * 10000);
      s._series.push(p);
      if (p !== prev) changed.push({ code: s.code, dir: p > prev ? 1 : -1 });
    }
    const eq = portfolio().equity_cents;
    state.equity_history[state.equity_history.length - 1].equity_cents = eq;
    emit("tick", { clock: c, changed });
  }

  let timer = null;
  function start() {
    stop();
    timer = setInterval(step, state.user.refresh_rate_ms);
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }
  function setPaused(paused) {
    state.clock.paused = paused;
    emit("tick", { clock: state.clock, changed: [] });
  }

  // ---------- 自选 ----------
  function toggleWatch(code) {
    const q = quote(code);
    q.watchlisted = !q.watchlisted;
    emit("watchlist", { code, watchlisted: q.watchlisted });
    return q.watchlisted;
  }

  // ---------- 持仓（PortfolioOut） ----------
  function holdingOut(h) {
    const q = quote(h.code);
    const mv = q.price_cents * h.quantity;
    const pnl = mv - h.total_cost_cents;
    return {
      code: h.code,
      name: q.name,
      quantity: h.quantity,
      sellable_quantity: h.sellable_quantity,
      avg_price_cents: h.avg_price_cents,
      total_cost_cents: h.total_cost_cents,
      market_price_cents: q.price_cents,
      market_value_cents: mv,
      pnl_cents: pnl,
      pnl_bp: h.total_cost_cents ? Math.round((pnl / h.total_cost_cents) * 10000) : 0,
      // 原型补充：当日盈亏（按昨收计算）
      _today_pnl_cents: (q.price_cents - q.prev_close_cents) * h.quantity,
    };
  }

  function portfolio() {
    const holdings = state.holdings.filter((h) => h.quantity > 0).map(holdingOut);
    const market_value_cents = holdings.reduce((a, h) => a + h.market_value_cents, 0);
    const equity_cents = state.cash_cents + market_value_cents;
    const todayPnl = holdings.reduce((a, h) => a + h._today_pnl_cents, 0);
    return {
      tick: state.clock.tick,
      trading_day: state.clock.trading_day,
      cash_cents: state.cash_cents,
      initial_fund_cents: state.save.initial_fund_cents,
      market_value_cents,
      equity_cents,
      net_pnl_cents: equity_cents - state.save.initial_fund_cents,
      holdings,
      // 当日盈亏（与后端 PortfolioOut 同名字段）：按昨收估算昨日权益
      prev_equity_cents: equity_cents - todayPnl,
      day_pnl_cents: todayPnl,
      day_pnl_bp: equity_cents - todayPnl > 0 ? Math.round((todayPnl / (equity_cents - todayPnl)) * 10000) : 0,
      _today_pnl_cents: todayPnl,
    };
  }

  const holding = (code) => state.holdings.find((h) => h.code === code && h.quantity > 0) || null;

  // ---------- 下单（OrderIn → OrderOut） ----------
  const feeOf = (gross, side) =>
    Math.round(gross * Number(side === "buy" ? state.save.buy_fee_rate : state.save.sell_fee_rate));

  /** 预估（供抽屉实时展示）：不改状态 */
  function estimate({ code, side, quantity, price_type, limit_price_cents }) {
    const q = quote(code);
    const p = price_type === "limit" && limit_price_cents ? limit_price_cents : q.price_cents;
    const gross = p * (quantity || 0);
    const fee = feeOf(gross, side);
    return { price_cents: p, gross_cents: gross, fee_cents: fee, total_cents: side === "buy" ? gross + fee : gross - fee };
  }

  /** 买入时最多可买股数（按交易单位取整，含手续费） */
  function maxBuy(code, price_cents) {
    const unit = state.save.trade_unit;
    const p = price_cents || quote(code).price_cents;
    let n = Math.floor(state.cash_cents / (p * (1 + Number(state.save.buy_fee_rate))) / unit) * unit;
    while (n > 0 && p * n + feeOf(p * n, "buy") > state.cash_cents) n -= unit;
    return Math.max(0, n);
  }

  function placeOrder(body) {
    const { code, side, quantity, price_type = "market", limit_price_cents = null } = body;
    const q = quote(code);
    if (!q) throw new ApiError("STOCK_NOT_FOUND", { code });
    if (!isTrading()) throw new ApiError("MARKET_CLOSED");
    const unit = state.save.trade_unit;
    const h = holding(code);
    const sellAll = side === "sell" && h && quantity === h.sellable_quantity;
    if (!Number.isInteger(quantity) || quantity <= 0 || (quantity % unit !== 0 && !sellAll))
      throw new ApiError("TRADE_INVALID_QUANTITY", { unit });

    let price = q.price_cents;
    if (price_type === "limit") {
      if (limit_price_cents > q.limit_up_cents || limit_price_cents < q.limit_down_cents)
        throw new ApiError("TRADE_PRICE_OUT_OF_LIMIT");
      // 契约：买单限价 ≥ 市价、卖单限价 ≤ 市价时按市价成交，否则拒绝
      if ((side === "buy" && limit_price_cents < price) || (side === "sell" && limit_price_cents > price))
        throw new ApiError("ORDER_LIMIT_NOT_REACHED");
    }

    const gross = price * quantity;
    const fee = feeOf(gross, side);
    const fund_before = state.cash_cents;
    let realized = 0;

    if (side === "buy") {
      if (gross + fee > state.cash_cents) throw new ApiError("TRADE_INSUFFICIENT_FUNDS");
      state.cash_cents -= gross + fee;
      if (h) {
        h.quantity += quantity;
        h.total_cost_cents += gross + fee;
        h.avg_price_cents = Math.round(h.total_cost_cents / h.quantity);
        if (state.save.t0_mode) h.sellable_quantity += quantity;
      } else {
        const old = state.holdings.find((x) => x.code === code);
        const rec = {
          code,
          quantity,
          sellable_quantity: state.save.t0_mode ? quantity : 0,
          avg_price_cents: Math.round((gross + fee) / quantity),
          total_cost_cents: gross + fee,
        };
        if (old) Object.assign(old, rec);
        else state.holdings.push(rec);
      }
    } else {
      if (!h || quantity > h.quantity) throw new ApiError("TRADE_INSUFFICIENT_HOLDINGS");
      if (quantity > h.sellable_quantity) throw new ApiError("TRADE_T1_SELL_BLOCKED", { sellable: h.sellable_quantity });
      const costPart = Math.round((h.total_cost_cents * quantity) / h.quantity);
      realized = gross - fee - costPart;
      state.cash_cents += gross - fee;
      h.quantity -= quantity;
      h.sellable_quantity -= quantity;
      h.total_cost_cents -= costPart;
    }

    const trade = {
      id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      seq: state.seq++,
      code,
      name: q.name,
      side,
      source: "manual",
      price_type,
      limit_price_cents: price_type === "limit" ? limit_price_cents : null,
      price_cents: price,
      quantity,
      gross_cents: gross,
      fee_cents: fee,
      cash_delta_cents: side === "buy" ? -(gross + fee) : gross - fee,
      realized_pnl_cents: realized,
      prev_close_cents: q.prev_close_cents,
      tick: state.clock.tick,
      trading_day: state.clock.trading_day,
      clock_minute: state.clock.clock_minute,
      auto_config_id: null,
      created_at: new Date().toISOString(),
      _fund_before_cents: fund_before,
    };
    state.trades.unshift(trade);
    const out = { trade, unlocked_achievement_ids: [], cash_cents: state.cash_cents, replayed: false };
    emit("order", out);
    return out;
  }

  // ---------- 自动交易 ----------
  function autoSave(body, id) {
    const q = quote(body.code);
    // 契约：同存档 code + direction 唯一
    const dup = state.auto.configs.find((c) => c.code === body.code && c.direction === body.direction && c.id !== id);
    if (dup) throw new ApiError("AUTO_CONFIG_DUPLICATE");
    const now = new Date().toISOString();
    if (id) {
      const c = state.auto.configs.find((x) => x.id === id);
      if (!c) throw new ApiError("AUTO_CONFIG_NOT_FOUND");
      Object.assign(c, body, { name: q.name, updated_at: now });
      emit("auto", c);
      return c;
    }
    const c = { id: "a" + Date.now(), name: q.name, created_at: now, updated_at: now, ...body };
    state.auto.configs.unshift(c);
    emit("auto", c);
    return c;
  }
  function autoDelete(id) {
    state.auto.configs = state.auto.configs.filter((c) => c.id !== id);
    emit("auto", null);
  }
  function autoToggle(id) {
    const c = state.auto.configs.find((x) => x.id === id);
    c.enabled = !c.enabled;
    emit("auto", c);
    return c.enabled;
  }
  /** start|pause|resume|stop —— 返回 AutoStatusOut */
  function autoControl(action) {
    const s = state.auto.status;
    if (action === "start") Object.assign(s, { enabled: true, paused: false });
    if (action === "pause") s.paused = true;
    if (action === "resume") s.paused = false;
    if (action === "stop") Object.assign(s, { enabled: false, paused: false });
    emit("auto", s);
    return s;
  }

  // ---------- 错误码文案（与 frontend/src/i18n/errors.js 的码一致） ----------
  const ERROR_TEXT = {
    TRADE_INSUFFICIENT_FUNDS: "可用资金不足",
    TRADE_INSUFFICIENT_HOLDINGS: "持仓数量不足",
    TRADE_T1_SELL_BLOCKED: "T+1：今日买入部分明日才可卖出",
    TRADE_INVALID_QUANTITY: "数量需为交易单位的整数倍",
    TRADE_PRICE_OUT_OF_LIMIT: "委托价超出涨跌停范围",
    ORDER_LIMIT_NOT_REACHED: "限价未达到当前市价，未成交",
    MARKET_CLOSED: "当前不在交易时段",
    STOCK_NOT_FOUND: "股票不存在",
    AUTO_CONFIG_DUPLICATE: "该股票同方向已有规则",
    AUTO_CONFIG_NOT_FOUND: "规则不存在",
    AUTO_LIMIT_REACHED: "已达自动交易次数上限",
    AUTO_MAX_AMOUNT_EXCEEDED: "超过单条规则最大金额",
    VALIDATION_ERROR: "参数不合法",
  };
  const errorText = (code) => ERROR_TEXT[code] || code;

  // 以下为与 store.real.js 对齐的接口（假数据版为空实现/同步实现），页面可无差别调用
  const noop = () => Promise.resolve();
  function setRefreshRate(ms) {
    state.user.refresh_rate_ms = ms;
    start();
  }
  const notifyError = (err) => SS.toast && SS.toast(errorText(err && err.code), { icon: "close", duration: 2400 });

  /** 假数据版的行情列表分页：与真实版 listQuotes 同形（{items,next_cursor,total}），游标为本地偏移量 */
  const SORT_KEY = { code: (x) => Number(x.code), price: (x) => x.price_cents, change: (x) => x.change_bp, volume: (x) => x.volume };
  function listQuotes({ q, sort, order, cursor, limit = 50, watchlisted } = {}) {
    let list = state.stocks.slice();
    const needle = (q || "").trim().toLowerCase();
    if (needle) list = list.filter((x) => x.code.includes(needle) || x.name.toLowerCase().includes(needle));
    if (watchlisted != null) list = list.filter((x) => !!x.watchlisted === watchlisted);
    const key = SORT_KEY[sort || "code"];
    const dir = (order || (sort && sort !== "code" ? "desc" : "asc")) === "asc" ? 1 : -1;
    list.sort((a, b) => (key(a) - key(b)) * dir || Number(a.code) - Number(b.code));
    const from = Number(cursor) || 0;
    const items = list.slice(from, from + limit);
    return new Promise((r) => setTimeout(() => r({ items, next_cursor: from + limit < list.length ? String(from + limit) : null, total: list.length }), 120));
  }

  SS.store = {
    mode: "mock",
    listQuotes,
    loadQuote: (code) => Promise.resolve(quote(code)),
    loadAllQuotes: () => Promise.resolve(state.stocks),
    loadSeries: noop,
    init: noop,
    loadDetail: noop,
    setRefreshRate,
    tradesHasMore: () => false,
    loadMoreTrades: noop,
    notifyError,
    state,
    on,
    ApiError,
    errorText,
    market,
    quote,
    orderBook,
    isTrading,
    start,
    stop,
    setPaused,
    toggleWatch,
    portfolio,
    holding,
    estimate,
    maxBuy,
    placeOrder,
    trades: () => state.trades,
    autoSave,
    autoDelete,
    autoToggle,
    autoControl,
  };

  // 资产曲线：线性校正整条假曲线，使终点与当前权益一致（避免末端断崖）
  {
    const h = state.equity_history;
    const fix = portfolio().equity_cents - h[h.length - 1].equity_cents;
    h.forEach((d, i) => (d.equity_cents += Math.round((fix * i) / (h.length - 1))));
  }
})();
