/**
 * 真实后端版 store：对外方法/事件与 store.js（假数据版）保持一致，页面无需区分。
 * 仅在真实模式（!SS.isMock）下加载并覆盖 SS.store。
 *
 * 数据流：init() 拉取 /me、/saves、market、portfolio、trades、自动交易 → 内存 state（同步读）；
 *        行情经 WebSocket /api/v1/ws/saves/{id} 推送（"tick"），断线时退化为按 refresh_rate_ms 轮询 market；
 *        写操作（下单、自动交易、自选、暂停…）调用 REST 后更新 state 并 emit 事件。
 *
 * 与假数据版的差异：
 *   - placeOrder / autoSave / autoDelete / autoControl / setPaused / skipClock / setRefreshRate 返回 Promise；
 *   - toggleWatch / autoToggle 为乐观更新（同步返回新值，失败自动回滚并 toast）；
 *   - 新增 init / login / register / logout / saves 管理 / loadDetail / loadMoreTrades / exportSave。
 * 行情缓存：state.byCode 只缓存“已加载过”的股票（自选、持仓/规则涉及的、列表翻过的页、看过的详情）；
 *   「全部」列表走服务端分页 listQuotes（limit/cursor/q/sort），WS 推送只更新缓存内的股票。
 * 分时曲线：先 GET /market/{code}/intraday 取当日历史（loadSeries / loadDetail），再由 WS tick 追加增量；
 *   发现漏 tick（断线、跳过）时重新拉历史，不做插值。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  if (SS.isMock) return;
  const api = SS.api;
  const ApiError = SS.ApiError;

  // ---------- 事件 ----------
  const listeners = {};
  const on = (evt, fn) => {
    (listeners[evt] = listeners[evt] || new Set()).add(fn);
    return () => listeners[evt].delete(fn);
  };
  const emit = (evt, payload) => (listeners[evt] || []).forEach((fn) => fn(payload));

  // ---------- 本地存储（失败静默） ----------
  const ls = {
    get(k) {
      try {
        return localStorage.getItem(k);
      } catch (_) {
        return null;
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(k, v);
      } catch (_) {}
    },
  };

  const blankStatus = () => ({ enabled: false, paused: false, max_total_trades: 100, total_trades: 0, success_trades: 0, failed_trades: 0, total_pnl_cents: 0 });
  const state = {
    clock: { paused: false, tick: 0, trading_day: 0, clock_minute: 570, skipped_ticks: 0 },
    stocks: [],
    byCode: {},
    save: { id: null, name: "", mode: "normal", initial_fund_cents: 0, buy_fee_rate: "0.0003", sell_fee_rate: "0.0013", t0_mode: false, trade_unit: 100 },
    savesList: [],
    cash_cents: 0,
    holdings: [],
    trades: [],
    tradesCursor: null,
    auto: { configs: [], status: blankStatus(), events: [] },
    user: { username: "", refresh_rate_ms: 3000, clock_speed: "normal", created_at: "1970-01-01T00:00:00Z" },
  };
  // 资产曲线：来自 GET /saves/{id}/equity-curve（后端按交易日持久化收盘权益）；末点（live）由实时权益替换
  state._equity = [];
  state._prevEquity = null; // portfolio.prev_equity_cents：昨日收盘权益（当日盈亏基准）
  Object.defineProperty(state, "equity_history", { enumerable: true, get: () => equityHistory() });

  const base = () => `/saves/${state.save.id}`;
  const quote = (code) => state.byCode[code];
  const uuid = () =>
    globalThis.crypto && crypto.randomUUID
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          return (c === "x" ? r : (r & 3) | 8).toString(16);
        });

  // ---------- 时段（字段全部来自服务端 ClockOut / tick.clock，经 SS.clockModel 归一化；不在本地推导） ----------
  /** 当前存档的时钟规则（v1/v2）：clock 字段优先，缺省用 SaveOut.clock_rules */
  const rulesNow = () => state.clock.clock_rules || (state.save && state.save.clock_rules) || "v1";
  const clock2 = () => SS.clockModel.normalize(state.clock, { refresh_rate_ms: state.user.refresh_rate_ms, save_rules: state.save.clock_rules });
  /** 此刻能否下单（07 §1.2：与暂停无关；停留与盘后为 false） */
  const isTrading = () => clock2().trading;

  // ---------- 行情 ----------
  /** 分钟 → 分时图下标（与 pages/stock.js 的读数映射一致：9:30=0，午休折叠，15:00=240） */
  function minuteIdx(m) {
    if (m <= 570) return 0;
    if (m <= 690) return m - 570;
    if (m < 780) return 120;
    return Math.min(240, 121 + (m - 780));
  }

  /** 分钟是否为交易分钟（分时点只记录交易分钟；v2 的 11:30 / 15:00 不算） */
  const isTradingMinute = (m) => SS.clockModel.tradingOf(m, rulesNow());

  /**
   * 由 s._pts（后端分时点）重建：
   *   _series —— 按分钟下标（9:30=0 … 15:00=240）排列，供分时图；交易日（每 20 个交易 tick）开始前的位置以开盘价平铺；
   *   _spark  —— [开盘价, 当日每个 tick 的价格]，供列表迷你图（只看形态，铺满宽度）。
   */
  function rebuildSeries(s) {
    const pts = s._pts || [];
    const arr = [s.open_cents];
    for (const p of pts) {
      const i = minuteIdx(p.minute);
      if (i <= 0) continue; // 9:30 当拍与开盘点同槽
      while (arr.length < i) arr.push(arr[arr.length - 1]);
      arr[i] = p.price_cents;
    }
    s._series = arr;
    s._spark = [s.open_cents, ...pts.map((p) => p.price_cents)];
  }

  const seriesInflight = {};
  /** 拉取个股当日分时历史（GET /market/{code}/intraday），并发去重 */
  function loadIntraday(code) {
    const s = quote(code);
    if (!s) return Promise.resolve();
    if (seriesInflight[code]) return seriesInflight[code];
    seriesInflight[code] = api
      .get(`${base()}/market/${code}/intraday`)
      .then((d) => {
        s._pts = d.points;
        s._ptsDay = d.trading_day;
        rebuildSeries(s);
      })
      .finally(() => delete seriesInflight[code]);
    return seriesInflight[code];
  }

  /** 批量确保这些股票的当日分时已加载（并发 6）；完成后 emit("series", codes)。失败的静默跳过 */
  async function loadSeries(codes) {
    const todo = codes.filter((c) => quote(c) && quote(c)._ptsDay !== state.clock.trading_day);
    let i = 0;
    const worker = async () => {
      while (i < todo.length) {
        try {
          await loadIntraday(todo[i++]);
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 401)) console.warn("分时加载失败", e.code);
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(6, todo.length) }, worker));
    if (todo.length) emit("series", todo);
  }
  let seriesQ = new Set();
  function queueSeries(code) {
    if (!seriesQ.size) setTimeout(() => {
      const codes = [...seriesQ];
      seriesQ = new Set();
      loadSeries(codes);
    }, 0);
    seriesQ.add(code);
  }

  /** 推送/轮询到来时给已加载分时的股票追加一个点；跨日或漏 tick（断线、跳过）则重拉历史 */
  function seriesTick(s, tick, minute, day, advanced) {
    if (s._ptsDay == null) return; // 未加载过历史：不累积，需要时再按需拉取
    if (s._ptsDay !== day) {
      s._ptsDay = null;
      queueSeries(s.code);
      return;
    }
    if (!isTradingMinute(minute)) return;
    const last = s._pts[s._pts.length - 1];
    if (last && tick <= last.tick) return; // 同一 tick 的重复帧
    let ok;
    if (!last) ok = advanced === 1;
    else {
      let n = 0; // 自上一个点以来经过的交易分钟数：恰为 1 才是连续
      for (let k = 1; k <= Math.min(tick - last.tick, 1500); k++) if (isTradingMinute((last.minute + k) % 1440)) n++;
      ok = tick - last.tick <= 1500 && n === 1;
    }
    if (!ok) {
      s._ptsDay = null;
      queueSeries(s.code);
      return;
    }
    s._pts.push({ minute, tick, price_cents: s.price_cents, volume: s.volume });
    rebuildSeries(s);
  }

  // ---------- 行情缓存与分页 ----------
  /** 合并一条行情到缓存（新股票建缓存对象），返回缓存对象（页面持有引用，WS 就地更新） */
  function mergeQuote(q) {
    let s = state.byCode[q.code];
    const fresh = !s;
    if (fresh) {
      s = state.byCode[q.code] = { _series: [], _spark: [], _pts: null, _ptsDay: null, _candles: [], _book: null, _detailAt: 0 };
      state.stocks.push(s);
    }
    Object.assign(s, q);
    if (fresh) rebuildSeries(s);
    return s;
  }
  /** 时钟字段白名单（07 §1.2）：undefined 不覆盖，null 要覆盖（如 next_event.at 在暂停时为 null） */
  const CLOCK_KEYS = ["paused", "tick", "trading_day", "clock_minute", "skipped_ticks", "clock_rules", "phase", "trading", "next_event", "ms_per_minute", "next_tick_at", "fast_forward_at", "server_time"];
  function applyClock(c) {
    for (const k of CLOCK_KEYS) if (c[k] !== undefined) state.clock[k] = c[k];
    if (c.server_time) {
      // 本机时钟偏差：server_time − 收到响应时的 Date.now()（SS.clockModel.normalize 用它校正倒计时）
      const t = Date.parse(c.server_time);
      if (Number.isFinite(t)) state.clock._offset_ms = t - Date.now();
    }
  }

  /** GET /market（服务端分页/搜索/排序）：把结果并入缓存，返回 {items, next_cursor, total} */
  async function listQuotes({ q, sort, order, cursor, limit = 50, watchlisted } = {}) {
    const m = await api.get(`${base()}/market`, { query: { q, sort, order, cursor, limit, watchlisted } });
    applyClock(m);
    return { items: m.stocks.map(mergeQuote), next_cursor: m.next_cursor, total: m.total };
  }
  /** 一次取全（limit=500 ≥ 股票池）：仅用于需要完整股票池的场景（自动交易选股器） */
  const loadAllQuotes = () => listQuotes({ limit: 500 }).then((r) => r.items);

  function applyDetail(s, d) {
    // 后端 candles 末尾含“今日”那根，页面会用实时数据另补一根，这里剔除避免重复
    s._candles = d.candles.filter((c) => c.trading_day < state.clock.trading_day);
    s._book = d.order_book;
    s._detailAt = Date.now();
  }
  /** 按代码加载单只股票（缓存没有时）：GET /market/{code}；不存在返回 undefined */
  async function loadQuote(code) {
    if (quote(code)) return quote(code);
    try {
      const { candles, order_book, ...q } = await api.get(`${base()}/market/${code}`);
      const s = mergeQuote(q);
      applyDetail(s, { candles, order_book });
      return s;
    } catch (e) {
      if (e instanceof ApiError && e.code === "STOCK_NOT_FOUND") return undefined;
      throw e;
    }
  }
  /** 持仓、自动规则/事件里出现的股票必须在缓存里（页面同步读 quote(code)） */
  async function ensureAccountQuotes() {
    const codes = new Set([...state.holdings.map((h) => h.code), ...state.auto.configs.map((c) => c.code), ...state.auto.events.map((e) => e.stock_code)]);
    await Promise.all([...codes].filter((c) => c && !quote(c)).map((c) => loadQuote(c).catch(() => {})));
  }

  /** 刷新缓存内股票的行情与时钟（轮询兜底 / 回前台）。返回价格有变化的股票 */
  async function loadMarket() {
    const m = await api.get(`${base()}/market`, { query: { limit: 500 } });
    applyClock(m);
    const changed = [];
    for (const q of m.stocks) {
      const s = quote(q.code);
      if (!s) continue;
      const prev = s.price_cents;
      Object.assign(s, q);
      if (prev !== s.price_cents) changed.push({ code: s.code, dir: s.price_cents > prev ? 1 : -1 });
    }
    for (const s of state.stocks) seriesTick(s, state.clock.tick, state.clock.clock_minute, state.clock.trading_day, null);
    return changed;
  }

  async function loadAccount() {
    const [pf, tr, cfg, st, ev, eq] = await Promise.all([
      api.get(`${base()}/portfolio`),
      api.get(`${base()}/trades`),
      api.get(`${base()}/auto-trade/configs`),
      api.get(`${base()}/auto-trade/status`),
      api.get(`${base()}/auto-trade/events`, { query: { limit: 20 } }),
      api.get(`${base()}/equity-curve`, { query: { range: "all" } }),
    ]);
    applyPortfolio(pf);
    state._equity = eq.items;
    state.trades = tr.items;
    state.tradesCursor = tr.next_cursor;
    state.auto = { configs: cfg.items, status: st, events: ev.items };
  }
  function applyPortfolio(pf) {
    state.cash_cents = pf.cash_cents;
    state._prevEquity = pf.prev_equity_cents;
    state.holdings = pf.holdings;
  }
  async function refreshPortfolio() {
    applyPortfolio(await api.get(`${base()}/portfolio`));
  }

  // 由推送触发的账户刷新（自动交易成交 / 手动成交回执）：合并为一次请求
  let accT = null;
  function scheduleAccountRefresh() {
    clearTimeout(accT);
    accT = setTimeout(async () => {
      try {
        await loadAccount();
        await ensureAccountQuotes();
        emit("order", null);
        emit("auto", null);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) notifyError(e);
      }
    }, 250);
  }

  // ---------- 持仓（PortfolioOut，按实时价重算市值/盈亏） ----------
  function holdingOut(h) {
    const q = quote(h.code);
    const price = q ? q.price_cents : h.market_price_cents;
    const mv = price * h.quantity;
    const pnl = mv - h.total_cost_cents;
    return {
      code: h.code,
      name: q ? q.name : h.name,
      quantity: h.quantity,
      sellable_quantity: h.sellable_quantity,
      avg_price_cents: h.avg_price_cents,
      total_cost_cents: h.total_cost_cents,
      market_price_cents: price,
      market_value_cents: mv,
      pnl_cents: pnl,
      pnl_bp: h.total_cost_cents ? Math.round((pnl / h.total_cost_cents) * 10000) : 0,
    };
  }
  function portfolio() {
    const holdings = state.holdings.filter((h) => h.quantity > 0).map(holdingOut);
    const market_value_cents = holdings.reduce((a, h) => a + h.market_value_cents, 0);
    const equity_cents = state.cash_cents + market_value_cents;
    // 当日盈亏：后端权威口径（当前权益 - 昨日收盘权益），随推送按实时权益重算
    const prev_equity_cents = state._prevEquity ?? equity_cents;
    const day_pnl_cents = equity_cents - prev_equity_cents;
    return {
      tick: state.clock.tick,
      trading_day: state.clock.trading_day,
      cash_cents: state.cash_cents,
      initial_fund_cents: state.save.initial_fund_cents,
      market_value_cents,
      equity_cents,
      net_pnl_cents: equity_cents - state.save.initial_fund_cents,
      holdings,
      prev_equity_cents,
      day_pnl_cents,
      day_pnl_bp: prev_equity_cents > 0 ? Math.round((day_pnl_cents / prev_equity_cents) * 10000) : 0,
      _today_pnl_cents: day_pnl_cents, // 页面沿用的别名
    };
  }
  const holding = (code) => {
    const h = state.holdings.find((x) => x.code === code && x.quantity > 0);
    return h ? holdingOut(h) : null;
  };

  // ---------- 资产曲线（后端持久化；末点实时） ----------
  function equityHistory() {
    const pts = state._equity.map((p) => ({ trading_day: p.trading_day, equity_cents: p.equity_cents, kind: p.kind }));
    const last = pts[pts.length - 1];
    const cur = portfolio().equity_cents;
    if (last && last.kind === "live") last.equity_cents = cur;
    else pts.push({ trading_day: state.clock.trading_day, equity_cents: cur, kind: "live" });
    if (pts.length < 2) pts.unshift({ trading_day: -1, equity_cents: state.save.initial_fund_cents, kind: "initial" });
    return pts;
  }

  // ---------- 实时流：WebSocket，失败时轮询 ----------
  let ws = null;
  let running = false;
  let retryT = null;
  let pollT = null;
  let attempt = 0;
  let warned = false;

  function handleMsg(msg) {
    switch (msg.t) {
      case "tick": {
        const c = msg.clock || {};
        const dayChanged = c.trading_day != null && c.trading_day !== state.clock.trading_day;
        applyClock({ ...c, tick: msg.tick, clock_minute: c.minute, paused: c.paused != null ? !!c.paused : undefined });
        const changed = [];
        for (const [code, price, bp, vol] of msg.q || []) {
          const s = quote(code);
          if (!s) continue;
          const prev = s.price_cents;
          s.price_cents = price;
          s.change_bp = bp;
          s.volume = vol;
          s.high_cents = Math.max(s.high_cents, price);
          s.low_cents = Math.min(s.low_cents, price);
          if (price !== prev) changed.push({ code, dir: price > prev ? 1 : -1 });
        }
        for (const s of state.stocks) seriesTick(s, msg.tick, state.clock.clock_minute, state.clock.trading_day, msg.advanced);
        if (dayChanged) {
          // 新交易日：昨收/涨跌停价/开盘价都变了，整体重拉
          loadMarket().then(() => emit("tick", { clock: state.clock, changed: [] })).catch(notifyError);
          scheduleAccountRefresh();
        }
        emit("tick", { clock: state.clock, changed });
        break;
      }
      case "phase":
        emit("phase", msg); // { from, to, trading_day, clock_minute }：收盘小结等订阅
        break;
      case "trade":
      case "auto_event":
        scheduleAccountRefresh();
        break;
      case "error":
        if (msg.code === "AUTH_REQUIRED") api.onUnauthorized && api.onUnauthorized(new ApiError("AUTH_REQUIRED", 401));
        break;
      case "achievement":
      case "subscribed":
      case "pong":
        break; // 原型不展示
      default:
        emit("ws:" + msg.t, msg); // 透传给各玩法功能（ws:news / ws:prediction / ws:challenge …）
    }
  }

  function startPoll() {
    if (pollT || !running) return;
    pollT = setInterval(async () => {
      try {
        const changed = await loadMarket();
        emit("tick", { clock: state.clock, changed });
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) console.warn("轮询行情失败", e.code);
      }
    }, Math.max(500, state.user.refresh_rate_ms || 3000));
  }
  const stopPoll = () => {
    clearInterval(pollT);
    pollT = null;
  };

  function connect() {
    if (!running || !state.save.id) return;
    try {
      ws = new WebSocket(api.wsUrl(`/ws/saves/${state.save.id}`));
    } catch (_) {
      startPoll();
      return;
    }
    ws.onopen = () => {
      attempt = 0;
      stopPoll();
    };
    ws.onmessage = (ev) => {
      try {
        handleMsg(JSON.parse(ev.data));
      } catch (e) {
        console.warn("忽略无法解析的推送", e);
      }
    };
    ws.onclose = (ev) => {
      ws = null;
      if (!running) return;
      if (ev.code === 4401) return api.onUnauthorized && api.onUnauthorized(new ApiError("AUTH_REQUIRED", 401));
      if (!warned && attempt >= 1) {
        warned = true;
        SS.toast && SS.toast("实时连接中断，已改为定时刷新", { icon: null, duration: 2200 });
      }
      startPoll();
      retryT = setTimeout(connect, Math.min(10000, 1000 * 2 ** attempt++));
    };
  }

  function start() {
    stop();
    if (!state.save.id) return;
    running = true;
    // 回到前台先补一次最新行情，再接实时流
    loadMarket().then((changed) => emit("tick", { clock: state.clock, changed })).catch(() => {});
    connect();
  }
  function stop() {
    running = false;
    clearTimeout(retryT);
    stopPoll();
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
  }

  // ---------- 错误 ----------
  const ERROR_TEXT = {
    AUTH_INVALID_CREDENTIALS: "用户名或密码错误",
    AUTH_USERNAME_TAKEN: "用户名已被占用",
    AUTH_USERNAME_INVALID: "用户名不合法（3-20 位字母数字下划线）",
    AUTH_PASSWORD_WEAK: "密码太弱（至少 8 位，需含字母和数字）",
    AUTH_REQUIRED: "请先登录",
    SAVE_NOT_FOUND: "存档不存在",
    SAVE_LIMIT_REACHED: "存档数量已达上限",
    TRADE_INSUFFICIENT_FUNDS: "可用资金不足",
    TRADE_INSUFFICIENT_HOLDINGS: "持仓数量不足",
    TRADE_T1_SELL_BLOCKED: "T+1：今日买入部分明日才可卖出",
    TRADE_T1_BUY_BLOCKED: "T+1：当前不可买入",
    TRADE_INVALID_QUANTITY: "数量需为交易单位的整数倍",
    TRADE_PRICE_OUT_OF_LIMIT: "委托价超出涨跌停范围",
    TRADE_PRICE_DEVIATION_EXCEEDED: "委托价偏离市价过大",
    TRADE_PRICE_DEVIATION_CONFIRM: "委托价偏离市价较大，请确认",
    TRADE_CIRCUIT_BREAKER_ACTIVE: "该股票熔断中",
    ORDER_LIMIT_NOT_REACHED: "限价未达到当前市价，未成交",
    MARKET_CLOSED: "当前不在交易时段",
    STOCK_NOT_FOUND: "股票不存在",
    AUTO_CONFIG_DUPLICATE: "该股票同方向已有规则",
    AUTO_CONFIG_NOT_FOUND: "规则不存在",
    AUTO_LIMIT_REACHED: "已达自动交易次数上限",
    AUTO_MAX_AMOUNT_EXCEEDED: "超过单条规则最大金额",
    VALIDATION_ERROR: "参数不合法",
    INTERNAL_ERROR: "服务器开小差了，请稍后重试",
    NETWORK: "网络异常，请检查连接",
    BACKEND_UNAVAILABLE: "后端服务不可用",
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
  const errorText = (code) => ERROR_TEXT[code] || (code ? `操作失败（${code}）` : "操作失败");
  /** 统一的失败提示（toast） */
  function notifyError(err) {
    if (err instanceof ApiError && err.status === 401 && err.code === "AUTH_REQUIRED") return; // 已跳登录
    SS.toast && SS.toast(errorText(err && err.code), { icon: "close", duration: 2400 });
  }

  // ---------- 会话 / 存档 ----------
  async function init() {
    stop();
    state.user = await api.get("/me");
    let saves = await api.get("/saves");
    if (!saves.length) saves = [await api.post("/saves", { body: { name: "主存档", trade_unit: 100, clock_rules: 2, events_enabled: true } })];
    state.savesList = saves;
    const want = ls.get("ss.saveId");
    // 上次停在挑战存档（不在普通存档列表里）时，回到参加前的普通存档
    const back = ls.get("ss.returnSaveId");
    await openSave(saves.find((s) => s.id === want) || saves.find((s) => s.id === back) || saves[0]);
  }
  async function openSave(sv) {
    stop();
    state.save = sv;
    state.byCode = {};
    state.stocks = [];
    ls.set("ss.saveId", sv.id);
    await Promise.all([listQuotes({ watchlisted: true, limit: 500 }), loadAccount()]); // 先缓存自选，其余按需分页加载
    await ensureAccountQuotes();
    emit("save", state.save); // features 订阅它清空自己的缓存
  }
  async function login(username, password) {
    await api.post("/auth/login", { body: { username, password } });
  }
  async function register(username, password) {
    await api.post("/auth/register", { body: { username, password } });
  }
  async function logout() {
    stop();
    try {
      await api.post("/auth/logout");
    } catch (_) {}
    state.save.id = null;
  }
  async function listSaves() {
    state.savesList = await api.get("/saves");
    return state.savesList;
  }
  async function switchSave(id) {
    // 挑战存档不进 GET /saves（只列普通存档），按 id 直接取
    const sv =
      state.savesList.find((s) => s.id === id) ||
      (await listSaves()).find((s) => s.id === id) ||
      (await api.get(`/saves/${encodeURIComponent(id)}`).catch(() => null));
    if (!sv) throw new ApiError("SAVE_NOT_FOUND", 404);
    await openSave(sv);
    start();
  }
  /** opts.events_enabled：事件模式（01 §1.1，创建后不可改） */
  async function createSave(name, opts = {}) {
    const sv = await api.post("/saves", { body: { name: name || "", trade_unit: 100, clock_rules: 2, events_enabled: !!opts.events_enabled } });
    state.savesList.unshift(sv);
    await openSave(sv);
    start();
    return sv;
  }
  async function exportSave() {
    const blob = await api.blob(`${base()}/export`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `stocksim-save-${state.save.id}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  // ---------- 个股详情（日 K + 五档） ----------
  const inflight = {};
  /** 拉取 candles / order_book（并按需拉当日分时历史）写入 quote 对象；1.5 秒内重复调用直接跳过，并发去重 */
  function loadDetail(code) {
    const s = quote(code);
    if (!s) return Promise.resolve();
    if (inflight[code]) return inflight[code];
    const needSeries = s._ptsDay !== state.clock.trading_day; // 分时历史只在未加载/跨日时拉，之后由 WS 增量维护
    if (!needSeries && Date.now() - s._detailAt < 1500) return Promise.resolve();
    inflight[code] = Promise.all([
      api.get(`${base()}/market/${code}`).then((d) => applyDetail(s, d)),
      needSeries ? loadIntraday(code) : null,
    ])
      .then(() => {})
      .finally(() => delete inflight[code]);
    return inflight[code];
  }
  const orderBook = (code) => (quote(code) && quote(code)._book) || { asks: [], bids: [] };

  // ---------- 自选（乐观更新） ----------
  function toggleWatch(code) {
    const q = quote(code);
    const next = !q.watchlisted;
    q.watchlisted = next;
    emit("watchlist", { code, watchlisted: next });
    (next ? api.put : api.del)(`${base()}/watchlist/${code}`).catch((e) => {
      q.watchlisted = !next;
      emit("watchlist", { code, watchlisted: !next });
      notifyError(e);
    });
    return next;
  }

  // ---------- 下单 ----------
  const feeOf = (gross, side) => Math.round(gross * Number(side === "buy" ? state.save.buy_fee_rate : state.save.sell_fee_rate));
  function estimate({ code, side, quantity, price_type, limit_price_cents }) {
    const q = quote(code);
    const p = price_type === "limit" && limit_price_cents ? limit_price_cents : q.price_cents;
    const gross = p * (quantity || 0);
    const fee = feeOf(gross, side);
    return { price_cents: p, gross_cents: gross, fee_cents: fee, total_cents: side === "buy" ? gross + fee : gross - fee };
  }
  function maxBuy(code, price_cents) {
    const unit = state.save.trade_unit;
    const p = price_cents || quote(code).price_cents;
    let n = Math.floor(state.cash_cents / (p * (1 + Number(state.save.buy_fee_rate))) / unit) * unit;
    while (n > 0 && p * n + feeOf(p * n, "buy") > state.cash_cents) n -= unit;
    return Math.max(0, n);
  }

  async function placeOrder(body) {
    const payload = {
      code: body.code,
      side: body.side,
      quantity: body.quantity,
      price_type: body.price_type || "market",
      limit_price_cents: body.price_type === "limit" ? body.limit_price_cents : null,
      confirm_deviation: !!body.confirm_deviation,
    };
    const out = await api.post(`${base()}/orders`, { body: payload, headers: { "Idempotency-Key": uuid() } });
    state.cash_cents = out.cash_cents;
    if (!state.trades.some((t) => t.id === out.trade.id)) state.trades.unshift(out.trade);
    try {
      await refreshPortfolio();
    } catch (_) {
      /* 成交已生效；持仓稍后由下一次推送/刷新补齐 */
    }
    emit("order", out);
    return out;
  }

  // ---------- 自动交易 ----------
  const AUTO_KEYS = ["code", "direction", "condition_type", "condition_operator", "condition_value_cents", "condition_percent", "quantity", "price_type", "limit_price_cents", "stop_loss_percent", "take_profit_percent", "max_trades", "max_amount_cents", "enabled"];
  const autoBody = (c) => Object.fromEntries(AUTO_KEYS.filter((k) => c[k] !== undefined).map((k) => [k, c[k]]));

  async function autoSave(body, id) {
    const out = id ? await api.put(`${base()}/auto-trade/configs/${id}`, { body: autoBody(body) }) : await api.post(`${base()}/auto-trade/configs`, { body: autoBody(body) });
    const i = state.auto.configs.findIndex((c) => c.id === out.id);
    if (i >= 0) state.auto.configs[i] = out;
    else state.auto.configs.unshift(out);
    emit("auto", out);
    return out;
  }
  async function autoDelete(id) {
    await api.del(`${base()}/auto-trade/configs/${id}`);
    state.auto.configs = state.auto.configs.filter((c) => c.id !== id);
    emit("auto", null);
  }
  /** 乐观切换启停（PUT 为全量替换，带上原配置）；失败回滚 */
  function autoToggle(id) {
    const c = state.auto.configs.find((x) => x.id === id);
    const next = !c.enabled;
    c.enabled = next;
    emit("auto", c);
    api
      .put(`${base()}/auto-trade/configs/${id}`, { body: autoBody({ ...c, enabled: next }) })
      .then((out) => Object.assign(c, out))
      .catch((e) => {
        c.enabled = !next;
        emit("auto", c);
        notifyError(e);
      });
    return next;
  }
  /** start|pause|resume|stop —— 返回 AutoStatusOut */
  async function autoControl(action) {
    const st = await api.post(`${base()}/auto-trade/${action}`);
    state.auto.status = st;
    emit("auto", st);
    return st;
  }

  // ---------- 时钟 / 偏好 / 成交分页 ----------
  async function setPaused(paused) {
    const c = await api.post(`${base()}/clock/${paused ? "pause" : "resume"}`);
    applyClock(c);
    emit("tick", { clock: state.clock, changed: [] });
  }
  /**
   * POST /clock/skip：跳到下一个关键时点（v1 规则，07 的 v2 语义由后端决定，前端只应用返回的 ClockOut）。
   * 一次推进多个 tick，缓存内行情与时钟立即补拉；跨交易日时账户（T+1 可卖数量）一并刷新。
   */
  async function skipClock() {
    const dayBefore = state.clock.trading_day;
    const c = await api.post(`${base()}/clock/skip`);
    applyClock(c);
    let changed = [];
    try {
      changed = await loadMarket();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw e;
    }
    if (state.clock.trading_day !== dayBefore) scheduleAccountRefresh();
    emit("tick", { clock: state.clock, changed });
    return c;
  }
  async function setRefreshRate(ms) {
    state.user = await api.patch("/me", { body: { refresh_rate_ms: ms } });
    start(); // 推送间隔在连接建立时读取，需重连
  }
  /** 游戏速度（v2 存档）：PATCH /me {clock_speed}；服务端按新档重算 ms_per_minute 与推送节奏，需重连 */
  async function setClockSpeed(speed) {
    state.user = await api.patch("/me", { body: { clock_speed: speed } });
    start();
  }
  /** 收盘小结（07 §1.4）：tradingDay 缺省为当前交易日；越界 422 */
  const loadDaySummary = (tradingDay) => api.get(`${base()}/day-summary`, { query: { trading_day: tradingDay } });
  const tradesHasMore = () => !!state.tradesCursor;
  async function loadMoreTrades() {
    if (!state.tradesCursor) return;
    const page = await api.get(`${base()}/trades`, { query: { cursor: state.tradesCursor } });
    const seen = new Set(state.trades.map((t) => t.id));
    state.trades.push(...page.items.filter((t) => !seen.has(t.id)));
    state.tradesCursor = page.next_cursor;
  }

  SS.store = {
    mode: "real",
    state,
    on,
    ApiError,
    errorText,
    notifyError,
    market: () => ({ ...state.clock, stocks: state.stocks }),
    quote,
    orderBook,
    loadDetail,
    listQuotes,
    loadQuote,
    loadAllQuotes,
    loadSeries,
    isTrading,
    init,
    login,
    register,
    logout,
    listSaves,
    switchSave,
    createSave,
    exportSave,
    start,
    stop,
    setPaused,
    skipClock,
    applyClock,
    emitLocal: emit,
    setRefreshRate,
    setClockSpeed,
    loadDaySummary,
    toggleWatch,
    portfolio,
    holding,
    estimate,
    maxBuy,
    placeOrder,
    trades: () => state.trades,
    tradesHasMore,
    loadMoreTrades,
    autoSave,
    autoDelete,
    autoToggle,
    autoControl,
  };
})();
