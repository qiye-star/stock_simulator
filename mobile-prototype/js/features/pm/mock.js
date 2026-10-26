/**
 * 预测市场的假数据与本地模拟（确定性；字段与 docs/10.26-plan/04-预测市场.md §9.2 一致；私有字段以 _ 开头）。
 *   SS.mockFeatures.pm = { list, detail, quote, trade, history, positions, settlements, nudge, reset }
 *   四个市场（均挂在今日挑战与昨日挑战上）：
 *     m1 bucket open（有色 3 日涨跌档，S=2000，持有 >5% 两份）、m2 rumor open（未揭晓）、
 *     m3 rumor resolved（被辟谣，我赚 +84）、m4 bucket resolved（昨日，我亏 −40）。
 *   报价与成交用 js/features/pm/model.js 的 LMSR（浮点），错误按 04 §9.3 抛 ApiError（与真实版同码）。
 *   模拟的“全服其它玩家”成交只改价格，不动我的持仓；nudge() 由 store.js 的 mock 定时调用（约 4 s）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.mockFeatures = SS.mockFeatures || {};
  const X = () => SS.pmModel;
  const CH = () => SS.mockFeatures.challenge;
  const TODAY = () => CH().TODAY_ID;
  const DAY = () => CH().DAY_ID;
  const BASE = Date.now();
  const iso = (ms) => new Date(ms).toISOString();
  const CHALLENGE_BUY_CAP = 3000; // 04 §5.5

  // 先验与目标价：m1 的 5 档与 04 §4.4 的 S=2000 档一致（b_milli = 12426）
  const DEFS = [
    {
      id: "3f7a1c2e-0000-4000-8000-00000000d001",
      challenge: "today",
      kind: "bucket",
      status: "open",
      b: 12426,
      S: 2000,
      event: { event_id: "e46-3", kind: "sudden", scope: "industry", major: true, sentiment: 1, title: "华中某锂矿区因环保督察全面停产整改，涉及国内锂盐供给约 8%", first_seen_trading_tick: 773, rumor_status: null },
      question: { scope: "industry", industry: "有色", code: null, stock_name: null, from_day: 3, to_day: 5, edges_bp: [-320, -110, 110, 320] },
      prices: [0.04, 0.06, 0.09, 0.19, 0.62],
      start: [0.25, 0.2, 0.2, 0.15, 0.2],
      traders: 312,
      seq: 11,
      volume: 1240,
      open_tt: 773,
      close_tt: 1210,
      resolve_tt: 1452,
      hold: { shares: [0, 0, 0, 0, 2], cost: [0, 0, 0, 0, 98], bought: 98, sold: 0 },
    },
    {
      id: "3f7a1c2e-0000-4000-8000-00000000d002",
      challenge: "today",
      kind: "rumor",
      status: "open",
      b: 8305,
      S: 1000,
      event: { event_id: "e47-2", kind: "rumor", scope: "industry", major: true, sentiment: -1, title: "新能源车企被曝暂停二期建设", first_seen_trading_tick: 1000, rumor_status: "unresolved" },
      question: { scope: "industry", industry: "新能源汽车", code: null, stock_name: null, from_day: null, to_day: null, edges_bp: [] },
      prices: [0.31, 0.69],
      start: [0.5, 0.5],
      traders: 128,
      seq: 4,
      volume: 310,
      open_tt: 1000,
      close_tt: null,
      resolve_tt: null,
      hold: null,
    },
    {
      id: "3f7a1c2e-0000-4000-8000-00000000d003",
      challenge: "today",
      kind: "rumor",
      status: "resolved",
      winning: 0,
      b: 8305,
      S: 1000,
      event: { event_id: "e44-1", kind: "rumor", scope: "industry", major: true, sentiment: 1, title: "锂矿区“一周内复产”传闻", first_seen_trading_tick: 520, rumor_status: "denied" },
      question: { scope: "industry", industry: "有色", code: null, stock_name: null, from_day: null, to_day: null, edges_bp: [] },
      prices: [0.3, 0.7],
      traders: 204,
      seq: 9,
      volume: 800,
      open_tt: 520,
      close_tt: null,
      resolve_tt: 760,
      hold: { shares: [8, 0], cost: [716, 0], bought: 716, sold: 0 },
      resolved_ms: BASE - 3600e3,
    },
    {
      id: "3f7a1c2e-0000-4000-8000-00000000d004",
      challenge: "day",
      kind: "bucket",
      status: "resolved",
      winning: 2,
      resolution_bp: 40,
      b: 6213,
      S: 1000,
      event: { event_id: "e42-2", kind: "policy", scope: "industry", major: true, sentiment: 1, title: "两部门发布新能源汽车下乡补贴细则", first_seen_trading_tick: 300, rumor_status: null },
      question: { scope: "industry", industry: "新能源汽车", code: null, stock_name: null, from_day: 36, to_day: 38, edges_bp: [-240, -80, 80, 240] },
      prices: [0.2, 0.2, 0.2, 0.2, 0.2],
      traders: 96,
      seq: 7,
      volume: 420,
      open_tt: 300,
      close_tt: 1210,
      resolve_tt: 1452,
      hold: { shares: [0, 1, 0, 0, 0], cost: [0, 40, 0, 0, 0], bought: 40, sold: 0 },
      resolved_ms: BASE - 26 * 3600e3,
    },
  ];

  const LABEL_KEYS = ["b0", "b1", "b2", "b3", "b4"];
  const DB = { balance: 1286, markets: [], settlements: [], inited: false, rnd: 7 };

  /** 概率数组 → 整数 ppm，和恰为 1e6 */
  function ppmOf(probs) {
    const base = probs.map((p) => Math.floor(p * 1e6));
    let rest = 1e6 - base.reduce((a, c) => a + c, 0);
    let best = 0;
    probs.forEach((p, i) => {
      if (p > probs[best]) best = i;
    });
    base[best] += rest;
    return base;
  }

  function build(def) {
    const chal = def.challenge === "day" ? DAY() : TODAY();
    const mk = {
      id: def.id,
      challenge_id: chal,
      kind: def.kind,
      status: def.status,
      winning: def.winning == null ? null : def.winning,
      resolution_bp: def.resolution_bp == null ? null : def.resolution_bp,
      b: def.b,
      S: def.S,
      event: def.event,
      question: def.question,
      traders: def.traders,
      seq: def.seq,
      volume: def.volume,
      open_tt: def.open_tt,
      close_tt: def.close_tt,
      resolve_tt: def.resolve_tt,
      hold: def.hold ? { shares: def.hold.shares.slice(), cost: def.hold.cost.slice(), bought: def.hold.bought, sold: def.hold.sold } : null,
      traded: !!def.hold,
      resolved_ms: def.resolved_ms || null,
      labels: def.kind === "rumor" ? X().RUMOR_LABELS.slice() : SS.predictMath.bucketLabels(def.question.edges_bp),
      q: null,
      hist: [],
    };
    const n = mk.labels.length;
    if (mk.status === "open") {
      // 开盘先验与成交：q_i = b·ln p_i（LMSR 中 p_i = exp(q_i/b)/Σ），目标价即当前价
      mk.q = def.prices.map((p) => (mk.b / 1000) * Math.log(p));
      const end = X().pricesPpm(mk.q, mk.b);
      const start = def.start.slice();
      for (let k = 0; k < 12; k++) {
        const t = k / 11;
        const probs = start.map((s, i) => s + (def.prices[i] - s) * t);
        mk.hist.push({ seq: k, public_tt: 388 - (11 - k) * 9, at: iso(BASE - (11 - k) * 60e3), prices_ppm: k === 11 ? end : ppmOf(probs) });
      }
    } else {
      // 已结算：价格为获胜选项 1、其余 0（与 PmMarketOut.outcomes 口径一致）
      mk.finalPpm = def.prices.map((_, i) => (i === def.winning ? 1e6 : 0));
    }
    return mk;
  }

  function ensure() {
    if (DB.inited) return;
    DB.inited = true;
    DB.markets = DEFS.map(build);
    DB.markets.forEach((mk) => {
      if (mk.status === "resolved" && mk.hold) {
        const ws = mk.hold.shares[mk.winning] || 0;
        const payout = ws * X().SHARE_POINTS;
        const net = mk.hold.bought - mk.hold.sold;
        DB.settlements.push({
          market_id: mk.id,
          event_id: mk.event.event_id,
          kind: "resolved",
          question: mk.question,
          market_kind: mk.kind,
          winning_outcome: mk.winning,
          winning_shares: ws,
          payout_points: payout,
          net_cost_points: net,
          pnl_points: payout - net,
          created_at: iso(mk.resolved_ms),
        });
      }
    });
  }

  const find = (id) => {
    ensure();
    const mk = DB.markets.find((m) => m.id === id);
    if (!mk) throw new SS.ApiError("PM_NOT_FOUND", 404, { market_id: id });
    return mk;
  };
  /** 当前价（ppm）：open/closed 按 LMSR；resolved 为获胜 1、其余 0 */
  function pricesOf(mk) {
    if (mk.status === "resolved") return mk.finalPpm.slice();
    return X().pricesPpm(mk.q, mk.b);
  }
  const keyOf = (kind, i) => (kind === "rumor" ? ["deny", "confirm"][i] : LABEL_KEYS[i]);

  function eventRef(mk) {
    return { ...mk.event };
  }

  function publicOf(mk) {
    const prices = pricesOf(mk);
    const rumorHidden = mk.kind === "rumor" && mk.status === "open";
    return {
      id: mk.id,
      challenge_id: mk.challenge_id,
      event_id: mk.event.event_id,
      kind: mk.kind,
      status: mk.status,
      question: mk.question,
      event: eventRef(mk),
      outcomes: mk.labels.map((_, i) => ({ idx: i, key: keyOf(mk.kind, i), price_ppm: prices[i] })),
      open_tt: mk.open_tt,
      close_tt: rumorHidden ? null : mk.close_tt,
      resolve_tt: rumorHidden ? null : mk.resolve_tt,
      opens_at: null,
      closes_at: null,
      resolves_at: null,
      trade_seq: mk.seq,
      volume_shares: mk.volume,
      traders: mk.traders,
      liquidity_b_milli: mk.b,
      subsidy_points: mk.S,
      winning_outcome: mk.winning,
      resolution_value_bp: mk.status === "resolved" && mk.kind === "bucket" ? mk.resolution_bp : null,
      void_reason: null,
      my_shares: mk.hold && mk.hold.shares.some((n) => n > 0) ? mk.hold.shares.slice() : null,
    };
  }

  const netUsed = (mk) => (mk.hold ? mk.hold.bought - mk.hold.sold : 0);
  function challengeBought(cid) {
    return DB.markets.filter((m) => m.challenge_id === cid).reduce((a, m) => a + (m.hold ? m.hold.bought : 0), 0);
  }

  function myOf(mk) {
    const h = mk.hold;
    if (!h || (h.bought === 0 && h.sold === 0)) return null;
    const prices = pricesOf(mk);
    // 与后端一致：只列出有过持仓的选项（稀疏，按 idx），卖光的选项保留一行（shares=0）
    const outcomes = mk.labels
      .map((_, i) => i)
      .filter((i) => (h.shares[i] || 0) > 0 || (h.cost[i] || 0) > 0)
      .map((i) => ({
        idx: i,
        shares: h.shares[i] || 0,
        cost_points: h.cost[i] || 0,
        value_points: X().holdingValue([h.shares[i] || 0], [prices[i]]),
      }));
    const value = X().holdingValue(h.shares, prices);
    return {
      outcomes,
      bought_points: h.bought,
      sold_points: h.sold,
      net_cost_points: h.bought - h.sold,
      value_points: value,
      pnl_points: value + h.sold - h.bought,
    };
  }

  function limitsOf(mk) {
    return {
      market_net_cost_cap_points: X().netCostCap(mk.S),
      market_net_cost_used_points: netUsed(mk),
      challenge_buy_cap_points: CHALLENGE_BUY_CAP,
      challenge_buy_used_points: challengeBought(mk.challenge_id),
      locked_ahead: false,
      eligible: true,
    };
  }

  function detailOf(mk) {
    return {
      ...publicOf(mk),
      q_shares: mk.q ? mk.q.map((x) => Math.round(x * 1000) / 1000) : mk.labels.map(() => 0),
      window_change_bp: null,
      my: myOf(mk),
      limits: limitsOf(mk),
      balance_points: DB.balance,
    };
  }

  /** 解析报价/交易参数：返回 { side, i, shares }（与 PmTradeIn 校验对齐；预算换算份额后再做范围与持仓检查） */
  function parseOrder(mk, body) {
    const side = body.side;
    if (side !== "buy" && side !== "sell") throw new SS.ApiError("VALIDATION_ERROR", 422, { field: "side" });
    const i = body.outcome;
    if (!Number.isInteger(i) || i < 0 || i >= mk.labels.length) throw new SS.ApiError("VALIDATION_ERROR", 422, { field: "outcome" });
    let shares = body.shares;
    if (side === "buy" && shares == null && body.budget_points != null) {
      const budget = body.budget_points;
      shares = X().maxSharesForBudget(mk.q, mk.b, i, budget, X().MAX_SHARES);
      if (shares < 1) throw new SS.ApiError("PM_TRADE_TOO_SMALL", 422, { points: budget });
    }
    if (!Number.isInteger(shares) || shares < 1 || shares > X().MAX_SHARES) {
      throw new SS.ApiError("VALIDATION_ERROR", 422, { field: "shares" });
    }
    if (side === "sell") {
      const held = mk.hold ? mk.hold.shares[i] || 0 : 0;
      if (shares > held) throw new SS.ApiError("PM_INSUFFICIENT_SHARES", 422, { held, requested: shares });
    }
    return { side, i, shares };
  }

  function requireOpen(mk) {
    if (mk.status !== "open") throw new SS.ApiError("PM_NOT_OPEN", 409, { market_id: mk.id, status: mk.status });
  }

  /** 公共时间线的当前 tick（与 challenge mock 的 public_trading_tick 一致，成交后随 seq 前进） */
  const publicTick = () => 388;

  const mock = {
    list({ challenge_id, status, limit = 20 } = {}) {
      ensure();
      const cid = challenge_id || TODAY();
      let items = DB.markets.filter((m) => m.challenge_id === cid);
      if (status && status !== "all") items = items.filter((m) => m.status === status);
      items = items.slice().sort((a, b) => b.open_tt - a.open_tt).slice(0, limit);
      return {
        items: items.map(publicOf),
        next_cursor: null,
        public: { challenge_id: cid, public_trading_tick: publicTick(), public_trading_day: Math.floor(publicTick() / 242), server_time: iso(Date.now()) },
      };
    },
    detail(id) {
      return detailOf(find(id));
    },
    quote(id, { side = "buy", outcome, shares, budget_points } = {}) {
      const mk = find(id);
      requireOpen(mk);
      const o = parseOrder(mk, { side, outcome, shares, budget_points });
      const q = X().quoteOf(mk.q, mk.b, o.side, o.i, o.shares);
      return { market_id: mk.id, ...q, trade_seq: mk.seq };
    },
    trade(id, body = {}) {
      const mk = find(id);
      requireOpen(mk);
      const o = parseOrder(mk, body);
      const pts = o.side === "buy" ? X().buyPoints(mk.q, mk.b, o.i, o.shares) : X().sellPoints(mk.q, mk.b, o.i, o.shares);
      if (o.side === "buy") {
        if (body.max_cost_points != null && pts > body.max_cost_points) {
          throw new SS.ApiError("PM_SLIPPAGE_EXCEEDED", 409, { quoted_points: pts, limit_points: body.max_cost_points });
        }
        if (pts > DB.balance) throw new SS.ApiError("POINTS_INSUFFICIENT", 422, { required: pts, balance: DB.balance });
        const cap = X().netCostCap(mk.S);
        const used = netUsed(mk);
        if (used + pts > cap) throw new SS.ApiError("PM_POSITION_LIMIT", 409, { limit_points: cap, used_points: used });
        const cUsed = challengeBought(mk.challenge_id);
        if (cUsed + pts > CHALLENGE_BUY_CAP) throw new SS.ApiError("PM_DAILY_LIMIT", 409, { limit_points: CHALLENGE_BUY_CAP, used_points: cUsed });
      } else {
        if (pts === 0) throw new SS.ApiError("PM_TRADE_TOO_SMALL", 422, { points: 0 });
        if (body.min_proceeds_points != null && pts < body.min_proceeds_points) {
          throw new SS.ApiError("PM_SLIPPAGE_EXCEEDED", 409, { quoted_points: pts, limit_points: body.min_proceeds_points });
        }
      }
      const before = X().pricesPpm(mk.q, mk.b)[o.i];
      if (!mk.hold) mk.hold = { shares: mk.labels.map(() => 0), cost: mk.labels.map(() => 0), bought: 0, sold: 0 };
      if (!mk.traded) {
        mk.traders += 1; // 我第一次在本市场成交
        mk.traded = true;
      }
      if (o.side === "buy") {
        mk.q = mk.q.map((x, i) => (i === o.i ? x + o.shares : x));
        mk.hold.shares[o.i] += o.shares;
        mk.hold.cost[o.i] += pts;
        mk.hold.bought += pts;
        DB.balance -= pts;
      } else {
        const held = mk.hold.shares[o.i];
        const out = Math.round((mk.hold.cost[o.i] * o.shares) / held);
        mk.q = mk.q.map((x, i) => (i === o.i ? x - o.shares : x));
        mk.hold.shares[o.i] -= o.shares;
        mk.hold.cost[o.i] -= out;
        mk.hold.sold += pts;
        DB.balance += pts;
      }
      mk.seq += 1;
      mk.volume += o.shares;
      const after = X().pricesPpm(mk.q, mk.b);
      const at = Date.now();
      mk.hist.push({ seq: mk.seq, public_tt: publicTick() + mk.seq, at: iso(at), prices_ppm: after });
      const trade = {
        id: `7c1d0e2a-0000-4000-8000-${String(mk.seq).padStart(12, "0")}`,
        market_id: mk.id,
        seq: mk.seq,
        side: o.side,
        outcome: o.i,
        shares: o.shares,
        points: pts,
        price_before_ppm: before,
        prices_after_ppm: after,
        public_tt: publicTick() + mk.seq,
        created_at: iso(at),
      };
      return { trade, market: publicOf(mk), my: myOf(mk), balance_points: DB.balance, replayed: false };
    },
    history(id) {
      const mk = find(id);
      return { market_id: mk.id, items: mk.hist.slice(-200) };
    },
    positions({ status = "active" } = {}) {
      ensure();
      const settled = (m) => m.status === "resolved" || m.status === "voided";
      const items = DB.markets
        .filter((m) => m.hold && (m.hold.bought > 0 || m.hold.sold > 0) && (status === "settled" ? settled(m) : !settled(m)))
        .map((m) => ({ market: publicOf(m), my: myOf(m) }));
      return { items, next_cursor: null };
    },
    settlements() {
      ensure();
      const items = DB.settlements.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
      return { items, next_cursor: null };
    },
    /** 模拟全服其它玩家的成交（只改价格，不动我的持仓）；返回本轮的 tick 载荷 */
    nudge() {
      ensure();
      const rnd = () => ((DB.rnd = (DB.rnd * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
      const out = [];
      for (const mk of DB.markets) {
        if (mk.status !== "open") continue;
        const i = Math.floor(rnd() * mk.labels.length);
        const n = 1 + Math.floor(rnd() * 3);
        mk.q = mk.q.map((x, k) => (k === i ? x + n : x));
        mk.seq += 1;
        mk.volume += n;
        const prices = X().pricesPpm(mk.q, mk.b);
        mk.hist.push({ seq: mk.seq, public_tt: publicTick() + mk.seq, at: iso(Date.now()), prices_ppm: prices });
        out.push({ id: mk.id, seq: mk.seq, status: mk.status, prices_ppm: prices, volume_shares: mk.volume, public_tt: publicTick() + mk.seq });
      }
      return out;
    },
  };

  SS.mockFeatures.pm = mock;
})();
