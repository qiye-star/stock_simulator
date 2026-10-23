/**
 * 本地假数据（确定性生成，每次刷新一致）。
 *
 * 字段命名与后端 backend/src/stocksim/schemas/*.py 保持一致：
 *   - 行情：QuoteOut / CandleOut / OrderBookOut（market.py）
 *   - 持仓：HoldingOut 的“原始部分”（portfolio.py；市值/盈亏由 store 实时计算）
 *   - 成交：TradeOut（orders.py，注意是 code 不是 stock_code）
 *   - 自动交易：AutoConfigOut / AutoStatusOut / AutoEventOut（auto_trade.py，事件里是 stock_code）
 *   - 用户：UserOut（user.py）
 * 金额全部为整数分（*_cents），涨跌幅为基点（change_bp，123 = 1.23%），
 * 自动交易百分比为 float（2.5 = 2.5%）。
 *
 * 非契约字段（仅原型使用）以 _ 开头：_series（分时价格数组）、_candles（日 K）。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  // mulberry32：小而确定的伪随机数
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rand = rng(20261023);

  // ---------- 时钟（ClockOut） ----------
  const clock = {
    paused: false,
    tick: 942,
    trading_day: 48,
    clock_minute: 10 * 60 + 35, // 10:35
    session: "trading",
    skipped_ticks: 0,
  };
  const AS_OF = new Date(Date.UTC(2026, 6, 1)); // 交易日 0 的日期（market_states._meta.as_of）

  // ---------- 股票池（取自 backend/src/stocksim/data/stock_pool.json） ----------
  // [code, name, industry, 昨收(分), 当前涨跌幅(%), 是否自选]
  const POOL = [
    ["600519", "贵州茅台", "白酒", 168800, 0.82, true],
    ["300750", "宁德时代", "新能源", 21530, 2.35, true],
    ["002594", "比亚迪", "新能源汽车", 26188, -1.46, true],
    ["600036", "招商银行", "银行", 3542, -0.31, true],
    ["688981", "中芯国际", "半导体", 8726, 4.12, true],
    ["999999", "影视飓风", "传媒", 4210, 6.8, true],
    ["002230", "科大讯飞", "人工智能", 5163, -2.73, true],
    ["000858", "五粮液", "白酒", 14290, -0.64, false],
    ["300059", "东方财富", "金融科技", 2318, 1.95, false],
    ["601012", "隆基绿能", "光伏", 1876, -3.88, false],
    ["000333", "美的集团", "家电", 7015, 0.12, false],
    ["002415", "海康威视", "安防", 3196, -0.95, false],
    ["603259", "药明康德", "医药服务", 5544, 1.07, false],
  ];

  const MORNING_OPEN = 570;
  const nowIdx = clock.clock_minute - MORNING_OPEN; // 已走过的分钟数

  /** 生成一段分时价格（分）：从 open 随机游走，再线性校正使终点落在 end（布朗桥） */
  function walk(start, end, n, vol) {
    const raw = [start];
    let p = start;
    for (let i = 1; i < n; i++) {
      p = p * (1 + (rand() - 0.5) * vol);
      raw.push(p);
    }
    const fix = end - raw[n - 1];
    return raw.map((v, i) => Math.max(1, Math.round(v + (fix * i) / (n - 1))));
  }

  /** 日 K（CandleOut[]），截止到昨天，收盘价最后对齐到昨收 */
  function makeCandles(prevClose, days) {
    const closes = [];
    let p = prevClose * (0.82 + rand() * 0.3);
    for (let i = 0; i < days; i++) {
      p = p * (1 + (rand() - 0.48) * 0.045);
      closes.push(p);
    }
    const k = prevClose / closes[closes.length - 1];
    const candles = [];
    let prev = closes[0] * k;
    for (let i = 0; i < days; i++) {
      const c = Math.round(closes[i] * k);
      const o = Math.round(prev * (1 + (rand() - 0.5) * 0.012));
      const hi = Math.round(Math.max(o, c) * (1 + rand() * 0.015));
      const lo = Math.round(Math.min(o, c) * (1 - rand() * 0.015));
      const td = clock.trading_day - days + i;
      const d = new Date(AS_OF.getTime() + td * 86400000);
      candles.push({
        trading_day: td,
        date: d.toISOString().slice(0, 10),
        open_cents: o,
        high_cents: hi,
        low_cents: lo,
        close_cents: c,
        volume: Math.round((2 + rand() * 6) * 1e6),
      });
      prev = c;
    }
    return candles;
  }

  const stocks = POOL.map(([code, name, industry, prev, chgPct, watch]) => {
    const open = Math.round(prev * (1 + (rand() - 0.5) * 0.01));
    const series = walk(open, Math.round(prev * (1 + chgPct / 100)), nowIdx + 1, 0.004);
    const price = series[series.length - 1];
    return {
      code,
      name,
      industry,
      price_cents: price,
      prev_close_cents: prev,
      open_cents: open,
      high_cents: Math.max(...series),
      low_cents: Math.min(...series),
      volume: Math.round((1 + rand() * 4) * 1e6),
      change_bp: Math.round(((price - prev) / prev) * 10000),
      limit_up_cents: Math.round(prev * 1.1),
      limit_down_cents: Math.round(prev * 0.9),
      circuit_breaker_active: false,
      watchlisted: watch,
      _series: series,
      _candles: makeCandles(prev, 60),
    };
  });

  // ---------- 存档（saves 表的原型子集） ----------
  const save = {
    id: "0b7c1d6e-2f43-4a8e-9a51-6d1c3f2a9e10",
    name: "主存档",
    mode: "normal",
    initial_fund_cents: 100000000, // 100 万元
    buy_fee_rate: "0.0003",
    sell_fee_rate: "0.0013",
    t0_mode: false,
    trade_unit: 100,
    created_at: "2026-07-01T01:30:00Z",
  };

  // ---------- 持仓（holdings 表；HoldingOut 的其余字段由 store 计算） ----------
  const holdings = [
    { code: "600519", quantity: 100, sellable_quantity: 100, avg_price_cents: 161250, total_cost_cents: 16125000 },
    { code: "300750", quantity: 400, sellable_quantity: 300, avg_price_cents: 22410, total_cost_cents: 8964000 },
    { code: "999999", quantity: 2000, sellable_quantity: 2000, avg_price_cents: 3680, total_cost_cents: 7360000 },
    { code: "002594", quantity: 200, sellable_quantity: 200, avg_price_cents: 27530, total_cost_cents: 5506000 },
  ];
  const cash_cents = 59870320; // 可用资金

  // ---------- 成交（TradeOut[]，新到旧） ----------
  const nameOf = Object.fromEntries(POOL.map((p) => [p[0], p[1]]));
  const TRADE_SPECS = [
    // [code, side, source, price, qty, day, minute, realized_pnl]
    ["300750", "buy", "manual", 21480, 100, 48, 600, 0],
    ["999999", "buy", "auto", 3655, 1000, 46, 845, 0],
    ["600036", "sell", "manual", 3608, 2000, 45, 610, 132400],
    ["300750", "buy", "manual", 22720, 300, 44, 575, 0],
    ["002594", "buy", "manual", 27530, 200, 41, 700, 0],
    ["601012", "sell", "auto", 1902, 3000, 39, 812, -48600],
    ["999999", "buy", "manual", 3705, 1000, 37, 640, 0],
    ["600036", "buy", "auto", 3536, 2000, 33, 790, 0],
    ["600519", "buy", "manual", 161250, 100, 30, 585, 0],
    ["601012", "buy", "manual", 2061, 3000, 28, 880, 0],
  ];
  let seq = TRADE_SPECS.length;
  const trades = TRADE_SPECS.map(([code, side, source, p, q, day, minute, pnl], i) => {
    const gross = p * q;
    const fee = Math.round(gross * (side === "buy" ? 0.0003 : 0.0013));
    const d = new Date(AS_OF.getTime() + day * 86400000 + (minute - 480) * 60000);
    return {
      id: `7f3a2c10-0000-4000-8000-${String(seq).padStart(12, "0")}`,
      seq: seq--,
      code,
      name: nameOf[code],
      side,
      source,
      price_type: "market",
      limit_price_cents: null,
      price_cents: p,
      quantity: q,
      gross_cents: gross,
      fee_cents: fee,
      cash_delta_cents: side === "buy" ? -(gross + fee) : gross - fee,
      realized_pnl_cents: pnl,
      prev_close_cents: Math.round(p * (1 + (i % 3 - 1) * 0.01)),
      tick: day * 20 + (i % 20),
      trading_day: day,
      clock_minute: minute,
      auto_config_id: source === "auto" ? "a1" : null,
      created_at: d.toISOString(),
    };
  });

  // ---------- 资产曲线（每个交易日的 equity_cents，最后一点由 store 实时替换） ----------
  const equity_history = [];
  {
    let e = save.initial_fund_cents;
    // 字段与后端 EquityPointOut 对齐：初始点 trading_day=-1，末点为 live（由 store 实时替换）
    equity_history.push({ trading_day: -1, equity_cents: e, kind: "initial" });
    for (let td = 1; td <= clock.trading_day; td++) {
      e = Math.round(e * (1 + (rand() - 0.45) * 0.018));
      equity_history.push({ trading_day: td, equity_cents: e, kind: td === clock.trading_day ? "live" : "close" });
    }
  }

  // ---------- 自动交易（AutoConfigOut / AutoStatusOut / AutoEventOut） ----------
  const auto_configs = [
    {
      id: "a1",
      code: "600036",
      name: "招商银行",
      direction: "buy",
      condition_type: "price",
      condition_operator: "below",
      condition_value_cents: 3450,
      condition_percent: null,
      quantity: 1000,
      price_type: "market",
      limit_price_cents: null,
      stop_loss_percent: null,
      take_profit_percent: null,
      max_trades: 3,
      max_amount_cents: 5000000,
      enabled: true,
      created_at: "2026-08-02T02:10:00Z",
      updated_at: "2026-08-02T02:10:00Z",
    },
    {
      id: "a2",
      code: "300750",
      name: "宁德时代",
      direction: "sell",
      condition_type: "profit",
      condition_operator: "above",
      condition_value_cents: 500000,
      condition_percent: null,
      quantity: 100,
      price_type: "market",
      limit_price_cents: null,
      stop_loss_percent: 8,
      take_profit_percent: 15,
      max_trades: 1,
      max_amount_cents: null,
      enabled: true,
      created_at: "2026-08-10T05:40:00Z",
      updated_at: "2026-08-12T01:00:00Z",
    },
    {
      id: "a3",
      code: "002594",
      name: "比亚迪",
      direction: "buy",
      condition_type: "percentage",
      condition_operator: "below",
      condition_value_cents: null,
      condition_percent: 3,
      quantity: 100,
      price_type: "limit",
      limit_price_cents: 25500,
      stop_loss_percent: null,
      take_profit_percent: null,
      max_trades: 0,
      max_amount_cents: null,
      enabled: false,
      created_at: "2026-08-15T06:00:00Z",
      updated_at: "2026-08-15T06:00:00Z",
    },
  ];
  const auto_status = {
    enabled: true,
    paused: false,
    max_total_trades: 100,
    total_trades: 7,
    success_trades: 6,
    failed_trades: 1,
    total_pnl_cents: 83800,
  };
  const auto_events = [
    { id: "e5", config_id: null, stock_code: "999999", direction: "buy", condition_type: "price", success: true, reason_code: null, amount_cents: 3655000, pnl_cents: 0, pnl_percent: null, buy_price_cents: 3655, sell_price_cents: null, tick: 935, trading_day: 46, created_at: "2026-08-16T06:05:00Z" },
    { id: "e4", config_id: "a2", stock_code: "300750", direction: "sell", condition_type: "profit", success: false, reason_code: "TRADE_T1_SELL_BLOCKED", amount_cents: 0, pnl_cents: 0, pnl_percent: null, buy_price_cents: null, sell_price_cents: null, tick: 902, trading_day: 45, created_at: "2026-08-15T02:15:00Z" },
    { id: "e3", config_id: null, stock_code: "601012", direction: "sell", condition_type: "price", success: true, reason_code: null, amount_cents: 5706000, pnl_cents: -48600, pnl_percent: -0.85, buy_price_cents: 2061, sell_price_cents: 1902, tick: 790, trading_day: 39, created_at: "2026-08-09T05:32:00Z" },
    { id: "e2", config_id: "a1", stock_code: "600036", direction: "buy", condition_type: "price", success: true, reason_code: null, amount_cents: 7072000, pnl_cents: 0, pnl_percent: null, buy_price_cents: 3536, sell_price_cents: null, tick: 668, trading_day: 33, created_at: "2026-08-03T05:10:00Z" },
  ];

  // ---------- 用户（UserOut） ----------
  const user = {
    id: "5d2b8f1e-9c0a-4b77-8e21-3a4f6c7d8e90",
    username: "owen",
    theme: "dark",
    lang: "zh-CN",
    refresh_rate_ms: 3000,
    tutorial_completed: true,
    created_at: "2026-06-28T12:00:00Z",
  };

  SS.mock = { clock, stocks, save, holdings, cash_cents, trades, equity_history, auto_configs, auto_status, auto_events, user, nextSeq: TRADE_SPECS.length + 1 };
})();
