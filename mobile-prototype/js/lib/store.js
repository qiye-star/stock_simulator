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
 *   skipClock()       ≈ POST /saves/{id}/clock/skip（v1 规则：逐分钟演化到目标分钟）
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

  const v2 = () => state.clock.clock_rules === "v2";
  const isTradingMinute = (m) => SS.clockModel.tradingOf(m, v2() ? "v2" : "v1");
  const normalizeNow = () => SS.clockModel.normalize(state.clock, { save_rules: state.save.clock_rules, refresh_rate_ms: state.user.refresh_rate_ms });
  const isTrading = () => normalizeNow().trading;
  const DWELL = SS.clockModel.DWELL_V2;

  /** 与后端 session_label 对齐（仅写入 clock.session，供 REST 形状一致；前端判断全部走 SS.clockModel） */
  function sessionLabel(m) {
    if ((m >= 570 && m <= 690) || (m >= 780 && m <= 900)) return "trading";
    return "closed";
  }

  /** 新交易日（v2：分钟到 9:30 的换日 tick）：昨收 = 上一日收盘，涨跌停/分时/日内高低重置，T+1 冻结解除，权益曲线新增 live 点 */
  function rollDay() {
    const c = state.clock;
    c.trading_day += 1;
    for (const s of state.stocks) {
      const p = s.price_cents;
      Object.assign(s, {
        prev_close_cents: p,
        open_cents: p,
        high_cents: p,
        low_cents: p,
        volume: 0,
        change_bp: 0,
        limit_up_cents: Math.round(p * 1.1),
        limit_down_cents: Math.round(p * 0.9),
        _series: [p],
        _spark: [p],
      });
    }
    for (const h of state.holdings) if (h.quantity > 0) h.sellable_quantity = h.quantity;
    state.equity_history.push({ trading_day: c.trading_day, equity_cents: portfolio().equity_cents, kind: "live" });
  }

  /** 收盘（进入 15:00 停留）：生成日 K（CandleOut）、权益曲线末点改为 close */
  function closeDay() {
    const c = state.clock;
    for (const s of state.stocks) {
      const last = s._candles[s._candles.length - 1];
      const date = last ? new Date(Date.parse(last.date) + 86400000).toISOString().slice(0, 10) : "";
      s._candles.push({ trading_day: c.trading_day, date, open_cents: s.open_cents, high_cents: s.high_cents, low_cents: s.low_cents, close_cents: s.price_cents, volume: s.volume });
    }
    const last = state.equity_history[state.equity_history.length - 1];
    if (last) last.kind = "close";
  }

  /**
   * 推进一个游戏分钟（逐分钟，含价格变动）。v1：时钟照走，交易分钟才变价，跨 24:00 换日（与后端 v1 一致）；
   * v2：只在交易分钟变价，到 9:30 换日（rollDay）。
   */
  function advanceOne() {
    const c = state.clock;
    c.tick += 1;
    if (v2()) {
      c.clock_minute = (c.clock_minute + 1) % 1440;
      if (c.clock_minute === 570) rollDay();
    } else {
      c.clock_minute += 1;
      if (c.clock_minute >= 1440) {
        c.clock_minute -= 1440;
        c.trading_day += 1;
      }
    }
    c.session = sessionLabel(c.clock_minute);
    if (!isTradingMinute(c.clock_minute)) return [];
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
    return changed;
  }
  function syncEquity() {
    state.equity_history[state.equity_history.length - 1].equity_cents = portfolio().equity_cents;
  }

  // ---------- v1 调度：固定 refresh_rate_ms 推进一分钟 ----------
  function step() {
    if (state.clock.paused) return;
    const changed = advanceOne();
    syncEquity();
    emit("tick", { clock: state.clock, changed });
  }

  // ---------- v2 调度（07 §5.2 的前端镜像）：锚点 + stepV2，停留点自动快进，并填充 ClockOut 的 v2 字段 ----------
  const v2t = { anchor: Date.now(), timer: null };
  let running = false;
  const iso = (t) => (t == null ? null : new Date(t).toISOString());

  /** 按当前状态重算 ClockOut 的 v2 字段（phase/trading/next_event/next_tick_at/fast_forward_at/server_time） */
  function publishV2() {
    const c = state.clock;
    const M = SS.clockModel;
    const now = Date.now();
    const ms = c.ms_per_minute;
    c.clock_rules = "v2";
    c.server_time = iso(now);
    c._offset_ms = 0; // 假数据：服务端即本机时钟（真实 store 在收到响应时写入偏差）
    c.phase = M.phaseOf(c.clock_minute, "v2");
    c.trading = M.tradingOf(c.clock_minute, "v2");
    const ne = M.nextEventOf(c.phase);
    if (c.paused) {
      c.next_event = { kind: ne.kind, minute: ne.minute, at: null };
      c.next_tick_at = null;
      c.fast_forward_at = null;
      return;
    }
    const st = M.stepV2(c.clock_minute, ms, DWELL);
    const toTarget = M.msUntilV2(c.clock_minute, ne.minute, ms, DWELL);
    c.next_event = { kind: ne.kind, minute: ne.minute, at: iso(toTarget == null ? null : v2t.anchor + toTarget) };
    c.next_tick_at = st.kind === "tick" ? iso(v2t.anchor + st.dur) : null;
    c.fast_forward_at = st.kind === "jump" && st.dur > 0 ? iso(v2t.anchor + st.dur) : null;
  }

  /** 排下一步（已 start 且未暂停时）；每次状态变化后调用 */
  function scheduleV2() {
    clearTimeout(v2t.timer);
    v2t.timer = null;
    publishV2();
    if (!running || state.clock.paused) return;
    const st = SS.clockModel.stepV2(state.clock.clock_minute, state.clock.ms_per_minute, DWELL);
    v2t.timer = setTimeout(fireV2, Math.max(0, v2t.anchor + st.dur - Date.now()));
  }

  /** 到点执行一步：tick（一分钟，含价格）或 jump（停留结束的快进，不变价） */
  function fireV2() {
    v2t.timer = null;
    const c = state.clock;
    const M = SS.clockModel;
    const before = M.phaseOf(c.clock_minute, "v2");
    const st = M.stepV2(c.clock_minute, c.ms_per_minute, DWELL);
    let changed = [];
    if (st.kind === "tick") changed = advanceOne();
    else {
      c.tick += st.minutes;
      c.clock_minute = st.to;
    }
    v2t.anchor += st.dur;
    settlePhase(before, changed);
  }

  /** 时段变化后的统一收尾：进入收盘时生成日 K；发 tick，再发 phase（与后端“tick 之后发 phase”一致） */
  function settlePhase(before, changed) {
    const c = state.clock;
    const after = SS.clockModel.phaseOf(c.clock_minute, "v2");
    if (after === "closed" && before !== "closed") closeDay();
    syncEquity();
    scheduleV2();
    emit("tick", { clock: c, changed: changed || [] });
    if (after !== before) emit("phase", { t: "phase", from: before, to: after, trading_day: c.trading_day, clock_minute: c.clock_minute });
  }

  /** POST /clock/skip：v1 逐分钟推进到 skipTargetOf；v2 到 skipTargetV2（07 §6.5），推进后锚点置为 now */
  function skipClock() {
    const c = state.clock;
    const M = SS.clockModel;
    const target = v2() ? M.skipTargetV2(c.clock_minute) : M.skipTargetOf(c.clock_minute);
    let n = target == null ? 0 : (target - c.clock_minute + 1440) % 1440;
    c.skipped_ticks = n;
    if (n) {
      const before = M.phaseOf(c.clock_minute, v2() ? "v2" : "v1");
      const prices = new Map(state.stocks.map((s) => [s.code, s.price_cents]));
      const total = n;
      while (n-- > 0) advanceOne();
      const changed = state.stocks
        .filter((s) => s.price_cents !== prices.get(s.code))
        .map((s) => ({ code: s.code, dir: s.price_cents > prices.get(s.code) ? 1 : -1 }));
      if (v2()) {
        v2t.anchor = Date.now();
        settlePhase(before, changed);
      } else {
        syncEquity();
        emit("tick", { clock: c, changed });
      }
      c.skipped_ticks = total;
    }
    return Promise.resolve(c);
  }

  /** 与 store.real.js 对齐：合并时钟字段并广播（features 的 mock 用它模拟服务端时钟） */
  function applyClock(c) {
    Object.assign(state.clock, c);
    emit("tick", { clock: state.clock, changed: [] });
  }

  let timer = null;
  let saveEmitted = false;
  function start() {
    stop();
    running = true;
    if (v2()) {
      v2t.anchor = Date.now(); // 与后端一致：从暂停/隐藏恢复后停留窗口重新计时
      scheduleV2();
    } else timer = setInterval(step, state.user.refresh_rate_ms);
    if (!saveEmitted) {
      saveEmitted = true;
      setTimeout(() => emit("save", state.save), 0); // features 在 init() 里订阅 save 清缓存
    }
  }
  function stop() {
    running = false;
    if (timer) clearInterval(timer);
    timer = null;
    clearTimeout(v2t.timer);
    v2t.timer = null;
  }
  function setPaused(paused) {
    state.clock.paused = paused;
    if (v2()) {
      if (!paused) v2t.anchor = Date.now(); // 恢复后停留窗口重新计时（后端 resume 同）
      scheduleV2();
    }
    emit("tick", { clock: state.clock, changed: [] });
    return Promise.resolve();
  }

  /** PATCH /me {clock_speed}：改每分钟毫秒数（mockspeed 参数可整体加速），锚点不变 */
  function setClockSpeed(speed) {
    if (!SS.clockModel.SPEED_IDS.includes(speed)) return Promise.reject(new ApiError("VALIDATION_ERROR", { field: "clock_speed" }));
    state.user.clock_speed = speed;
    state.clock.ms_per_minute = SS.clockModel.SPEEDS_V2[speed] / (M.speedScale || 1);
    scheduleV2();
    emit("tick", { clock: state.clock, changed: [] });
    return Promise.resolve(state.user);
  }

  /**
   * GET /saves/{id}/day-summary（07 §1.4 DaySummaryOut 的假数据形状）。
   * 当前日取实时权益；过去的日取权益曲线相邻两点；成交按 trading_day 过滤；历史日行情用当前股票池近似（假数据）。
   */
  function loadDaySummary(tradingDay) {
    const c = state.clock;
    const cur = c.trading_day;
    const d = tradingDay == null ? cur : Number(tradingDay);
    if (!Number.isInteger(d) || d < Math.max(0, cur - 30) || d > cur) return Promise.reject(new ApiError("VALIDATION_ERROR", { field: "trading_day" }));
    const isCur = d === cur;
    const pf = portfolio();
    const pt = (td) => state.equity_history.find((p) => p.trading_day === td);
    const equity = isCur ? pf.equity_cents : pt(d) ? pt(d).equity_cents : null;
    const prev = isCur ? pf.prev_equity_cents : pt(d - 1) ? pt(d - 1).equity_cents : null;
    const pnl = equity != null && prev != null ? equity - prev : null;
    const trs = state.trades.filter((t) => t.trading_day === d);
    const sum = (f) => trs.reduce((a, t) => a + f(t), 0);
    const quoteOut = (s) => ({
      code: s.code,
      name: s.name,
      close_cents: s.price_cents,
      change_bp: s.change_bp,
      limit: s.price_cents >= s.limit_up_cents ? "up" : s.price_cents <= s.limit_down_cents ? "down" : null,
    });
    const byChg = state.stocks.slice().sort((a, b) => b.change_bp - a.change_bp || Number(a.code) - Number(b.code));
    const candle = state.stocks[0] && state.stocks[0]._candles.find((k) => k.trading_day === d);
    const phase = SS.clockModel.phaseOf(c.clock_minute, "v2");
    const nowOpen = isCur && v2() && !c.paused && c.next_event && c.next_event.kind === "open";
    const n = state.stocks.length;
    const up = state.stocks.filter((s) => s.change_bp > 0).length;
    const down = state.stocks.filter((s) => s.change_bp < 0).length;
    return Promise.resolve({
      trading_day: d,
      date: isCur ? (candle && candle.date) || "" : (candle && candle.date) || "",
      clock_rules: c.clock_rules || "v2",
      status: !isCur || phase === "closed" ? "closed" : "trading",
      equity_cents: equity,
      prev_equity_cents: prev,
      day_pnl_cents: pnl,
      day_pnl_bp: pnl != null && prev > 0 ? Math.round((pnl / prev) * 10000) : null,
      cash_cents: isCur ? pf.cash_cents : null,
      market_value_cents: isCur ? pf.market_value_cents : null,
      trades: {
        count: trs.length,
        buy_count: trs.filter((t) => t.side === "buy").length,
        sell_count: trs.filter((t) => t.side === "sell").length,
        buy_amount_cents: sum((t) => (t.side === "buy" ? t.gross_cents : 0)),
        sell_amount_cents: sum((t) => (t.side === "sell" ? t.gross_cents : 0)),
        fee_cents: sum((t) => t.fee_cents),
        realized_pnl_cents: sum((t) => t.realized_pnl_cents),
      },
      market: {
        total: n,
        up,
        down,
        flat: n - up - down,
        limit_up: state.stocks.filter((s) => s.price_cents >= s.limit_up_cents).length,
        limit_down: state.stocks.filter((s) => s.price_cents <= s.limit_down_cents).length,
        avg_change_bp: Math.round(state.stocks.reduce((a, s) => a + s.change_bp, 0) / Math.max(1, n)),
      },
      top_gainers: byChg.slice(0, 5).map(quoteOut),
      top_losers: byChg.slice(-5).reverse().map(quoteOut),
      holdings: isCur ? pf.holdings.map((h) => ({ code: h.code, name: h.name, quantity: h.quantity, close_cents: h.market_price_cents, change_bp: quote(h.code).change_bp, market_value_cents: h.market_value_cents })) : null,
      next_open_at: nowOpen ? c.next_event.at : null,
    });
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
    EVENTS_DISABLED: "该存档未开启事件模式",
    EVENT_NOT_FOUND: "事件不存在或尚未发布",
    SUPPLY_EDGE_NOT_FOUND: "产业链关系不存在",
    FEATURE_UNAVAILABLE: "功能即将开放",
    PREDICTION_NOT_FOUND: "预测卡不存在",
    PREDICTION_CLOSED: "预测已截止",
    POINTS_INSUFFICIENT: "积分不足",
    INTEL_LIMIT_REACHED: "今日情报卡已达上限",
    INTEL_UNAVAILABLE: "该情报当前不可购买",
    TITLE_NOT_UNLOCKED: "称号尚未解锁",
    CHALLENGE_NOT_FOUND: "挑战不存在",
    CHALLENGE_NOT_STARTED: "挑战尚未开始",
    CHALLENGE_ENTRY_CLOSED: "今日挑战已停止报名",
    CHALLENGE_ENDED: "挑战已结束",
    CHALLENGE_NOT_ENTERED: "你还没有参加这场挑战",
    CHALLENGE_ROUND_NOT_FOUND: "该回合不存在或尚未开始",
    CHALLENGE_ROUND_CLOSED: "本回合已截止",
    CHALLENGE_ANSWER_LIMIT: "修改次数已用完",
    CHALLENGE_NOT_SETTLED: "挑战结算后才能查看",
    CHALLENGE_UNSUPPORTED: "挑战存档不支持该操作",
    REPLAY_LEVEL_NOT_FOUND: "关卡不存在或已下线",
    REPLAY_UNSUPPORTED: "复盘存档不支持该操作",
    REPLAY_STOCK_SUSPENDED: "该股票停牌，不能交易",
    REPLAY_LIMIT_LOCKED: "该股封板，当前价位无法成交",
    REPLAY_PREDICTION_PENDING: "还有预测题未作答，先作答再继续",
    REPLAY_QUESTION_CLOSED: "这道预测题已截止或尚未开放",
    REPLAY_SESSION_SETTLED: "本次复盘已结算",
    REPLAY_REVEAL_LOCKED: "复盘结束后才能查看揭示",
    PM_NOT_FOUND: "预测市场不存在",
    PM_NOT_OPEN: "该市场当前不可交易",
    PM_LOCKED_AHEAD: "你的挑战进度已超过公共进度，本场市场暂不对你开放",
    PM_NOT_ELIGIBLE: "暂不满足交易条件",
    PM_SLIPPAGE_EXCEEDED: "价格已变动，请重新报价",
    PM_INSUFFICIENT_SHARES: "持有份额不足",
    PM_TRADE_TOO_SMALL: "成交额过小",
    PM_POSITION_LIMIT: "已达本市场投入上限",
    PM_DAILY_LIMIT: "已达本场挑战的买入额度",
    PM_RATE_LIMITED: "操作过于频繁，请稍后再试",
    PM_BUSY: "市场繁忙，请重试",
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
    setClockSpeed,
    loadDaySummary,
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
    skipClock,
    applyClock,
    emitLocal: emit,
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
