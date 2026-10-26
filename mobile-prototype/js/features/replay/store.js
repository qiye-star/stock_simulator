/**
 * 真实复盘（⑨ E）的数据层：mock 与 real 两套同名方法，挂到 SS.store（SS.assertSameKeys 对照）。
 * 复盘不切换当前存档：所有方法显式带 saveId（复盘存档 id），状态不进 SS.store.state 的存档字段。
 *
 *   listReplayLevels({tag, difficulty, cursor, limit})     GET  /replay/levels            → {items: ReplayLevelOut[], next_cursor}
 *   createReplaySession(slug, {masked=true, name})         POST /replay/sessions          → ReplaySessionOut
 *   listReplaySessions()                                   GET  /replay/sessions          → {items: ReplaySessionOut[]}
 *   getReplaySession(saveId)                               GET  /replay/sessions/{id}
 *   advanceReplay(saveId, {to, expected_tick, skip_pending}) POST /replay/sessions/{id}/advance → AdvanceOut
 *   finishReplay(saveId)                                   POST /replay/sessions/{id}/finish → ReplaySessionOut
 *   getReplayFeed(saveId, {cursor, limit})                 GET  /replay/sessions/{id}/feed → {items, next_cursor}
 *   listReplayQuestions(saveId)                            GET  /replay/sessions/{id}/questions → {items}
 *   answerReplayQuestion(saveId, qid, {probs, order})      PUT  /replay/sessions/{id}/questions/{qid}/answer → ReplayQuestionOut
 *   getReplayBenchmark(saveId)                             GET  /replay/sessions/{id}/benchmark → {name, points}
 *   getReplayReveal(saveId)                                GET  /replay/sessions/{id}/reveal → RevealOut（结算后）
 *   loadReplayMarket(saveId)                               GET  /saves/{rid}/market → {stocks: QuoteOut[]}（只含关卡股票）
 *   loadReplayStock(saveId, code)                          GET  /saves/{rid}/market/{code} → StockMarketOut
 *   loadReplayPortfolio(saveId)                            GET  /saves/{rid}/portfolio
 *   replayOrder(saveId, {code, side, quantity})            POST /saves/{rid}/orders（市价，Idempotency-Key）→ OrderOut
 * 共用（不计入对照）：resetReplay()。
 * real 经 guarded()：后端没有复盘接口（HTTP_404/405/501）时抛 FEATURE_UNAVAILABLE 并记入 SS.api.missing，本会话不再请求；
 * 业务错误（REPLAY_*、VALIDATION_ERROR …）原样抛出，由页面处理。
 * mock：内存中的复盘会话（刷新即重置），规则与服务端同口径：只在开盘/收盘成交、T+1、封板、题目截止与计分（见 model.js）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { ApiError } = SS;
  const state = SS.store.state;
  const R = () => SS.replayModel;
  const MK = () => SS.mockFeatures;
  const blank = () => ({ sessions: null, error: null });
  state.replay = state.replay || blank();

  const resetReplay = () => Object.assign(state.replay, blank());
  const INITIAL_FUND = 100_000_000; // 100 万元（05 §1.2）
  const qs = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v != null && v !== ""));

  /** 复盘 store 的 mock 数据库（内存）：saveId → 会话状态；首次访问时写入一个进行中的演示会话 */
  let db = null;
  const uuid = () =>
    globalThis.crypto && crypto.randomUUID
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          return (c === "x" ? r : (r & 3) | 8).toString(16);
        });

  // ---------- mock 引擎 ----------
  const pack = (slug) => MK().replayPack(slug);
  const err = (code, status, params) => new ApiError(code, status, params);

  function sessionOf(saveId) {
    const s = db && db[saveId];
    if (!s) throw err("SAVE_NOT_FOUND", 404);
    return s;
  }
  const qst = (s, id) => (s.qs[id] = s.qs[id] || { answer: null, skipped: false, result: null });

  /** 持仓（按股票键聚合）：数量、可卖（上一日及更早买入）、成本 */
  function lotsByKey(s) {
    const out = {};
    for (const l of s.lots) {
      const o = (out[l.key] = out[l.key] || { key: l.key, qty: 0, sellable: 0, cost: 0 });
      o.qty += l.qty;
      o.cost += l.cost;
      if (l.day < R().dayOf(s.pos)) o.sellable += l.qty;
    }
    return Object.values(out).filter((h) => h.qty > 0);
  }
  function equityAt(s, pos) {
    const p = pack(s.slug);
    const mv = lotsByKey(s).reduce((a, h) => a + h.qty * R().quoteOf(p, h.key, pos, s.masked).price_cents, 0);
    return s.cash + mv;
  }
  const pointsOf = (s, score) => Math.round(score * (s.masked ? 1 : 0.5));

  /** 题目在推进检查中的输入 */
  function questionStates(s, p) {
    return p.questions.map((q) => {
      const pos = R().questionPositions(q);
      return { id: q.id, opens: pos.opens, closes: pos.closes, resolves: pos.resolves, answered: !!qst(s, q.id).answer };
    });
  }

  /** 题目计分（到达 resolves 时调用）：未答或跳过 → 无结果 */
  function scoreQuestion(s, p, q) {
    const rr = R();
    const st = qst(s, q.id);
    if (!st.answer || st.skipped) return null;
    const baseDay = q.opens.day - 1;
    const endDay = q.resolves.day;
    if (q.kind === "rank") {
      const ret = {};
      for (const k of q.stock_keys) {
        const base = rr.barAt(p, k, baseDay).c;
        const end = rr.barAt(p, k, endDay).c;
        ret[k] = Math.round(((end - base) * 10000) / base);
      }
      const top = q.stock_keys.slice().sort((a, b) => ret[b] - ret[a] || (a < b ? -1 : 1)).slice(0, q.top_k);
      const rel = {};
      top.forEach((k, i) => (rel[k] = q.top_k - i));
      const score = rr.ndcgScore(st.answer.order, rel, q.top_k);
      st.result = { returns_bp: ret, true_top: top, score, points: pointsOf(s, score) };
    } else {
      const base = rr.barAt(p, q.stock_key, baseDay).c;
      const end = rr.barAt(p, q.stock_key, endDay).c;
      const ret = Math.round(((end - base) * 10000) / base);
      const outcome = rr.bucketOf(ret, q.edges_bp);
      const score = rr.rpsScore(st.answer.probs, outcome);
      st.result = { outcome_bucket: outcome, return_bp: ret, score, points: pointsOf(s, score) };
    }
    return st.result;
  }

  /** 收盘快照（每个盘后位置经过时记一次，资产曲线用） */
  function snapshotsBetween(s, p, from, to) {
    for (let d = 0; d < p.play_days; d++) {
      const pos = R().posOf(d, "post_close");
      if (pos > from && pos <= to) {
        const eq = equityAt(s, pos);
        s.equity.push({ trading_day: d, equity_cents: eq, cash_cents: s.cash, market_value_cents: eq - s.cash, kind: "close" });
      }
    }
  }

  /** 结算（05 §1.6）：按最后可见价格估值，算收益、基准与超额；积分为已计分题之和 */
  function settle(s, p) {
    const rr = R();
    const last = rr.lastPos(p.play_days);
    const eq = equityAt(s, last);
    const ret = Math.round(((eq - s.initial) * 10000) / s.initial);
    const lastDay = p.play_days - 1;
    const b0 = p.benchmark.closes[p.lookback_days - 1];
    const b1 = p.benchmark.closes[p.lookback_days + lastDay];
    const benchRet = Math.round(((b1 - b0) * 10000) / b0);
    const holdRets = p.stocks.map((st) => {
      const base = rr.barAt(p, st.key, -1).c;
      const end = rr.barAt(p, st.key, lastDay).c;
      return ((end - base) * 10000) / base;
    });
    s.holdAllBp = Math.round(holdRets.reduce((a, b) => a + b, 0) / holdRets.length);
    // 结算时对剩余（已答但未到结算点）的题目按真实结果计分（05 §1.6 第 2 步）；未答的记 0 分
    for (const q of p.questions) {
      const st = qst(s, q.id);
      if (st.answer && !st.skipped && !st.result) scoreQuestion(s, p, q);
    }
    const points = p.questions.reduce((a, q) => a + ((qst(s, q.id).result && qst(s, q.id).result.points) || 0), 0);
    s.settled = { final_equity_cents: eq, return_bp: ret, benchmark_return_bp: benchRet, excess_bp: ret - benchRet, points_total: points };
  }

  function sessionView(s) {
    const p = pack(s.slug);
    const rr = R();
    const pos = s.pos;
    const day = rr.dayOf(pos);
    const open = p.questions.filter((q) => rr.questionPositions(q).opens <= pos).map((q) => {
      const v = rr.questionOf(p, q, pos, qst(s, q.id), s.masked);
      return v;
    });
    const openIds = open.filter((v) => v.status === "open").map((v) => v.id);
    const pendingIds = open.filter((v) => v.status === "open" && rr.questionPositions(p.questions.find((q) => q.id === v.id)).closes === pos).map((v) => v.id);
    return {
      save_id: s.id,
      name: s.name || "",
      level: { slug: p.slug, version: p.version, title: s.masked ? p.title_masked : p.title },
      masked: s.masked,
      status: s.settled ? "settled" : "active",
      day_idx: day,
      play_days: p.play_days,
      phase: rr.phaseOf(pos),
      tick: pos,
      date: rr.isoOf(p, day, s.masked),
      date_label: rr.dateLabelOf(p, day, s.masked),
      cash_cents: s.cash,
      initial_fund_cents: s.initial,
      equity_cents: s.settled ? s.settled.final_equity_cents : equityAt(s, pos),
      pending_question_ids: pendingIds,
      open_question_ids: openIds,
      settled: s.settled ? { ...s.settled } : null,
      created_at: s.created_at,
    };
  }

  /** 下单（市价，当前阶段价格成交）：规则同服务端口径（05 §1.4） */
  function doOrder(s, { code, side, quantity }) {
    const p = pack(s.slug);
    const rr = R();
    if (s.settled) throw err("REPLAY_SESSION_SETTLED", 409, { save_id: s.id });
    const phase = rr.phaseOf(s.pos);
    if (!rr.isTradable(phase)) throw err("MARKET_CLOSED", 409);
    if (!Number.isInteger(quantity) || quantity <= 0 || quantity % rr.LOT !== 0) throw err("TRADE_INVALID_QUANTITY", 422, { unit: rr.LOT });
    const key = rr.keyOfCode(p, code, s.masked);
    if (!key) throw err("STOCK_NOT_FOUND", 404, { code });
    const q = rr.quoteOf(p, key, s.pos, s.masked);
    if (rr.isLocked(side, q.price_cents, q.limit_up_cents, q.limit_down_cents)) throw err("REPLAY_LIMIT_LOCKED", 409, { code, side });
    const h = lotsByKey(s).find((x) => x.key === key) || { qty: 0, sellable: 0 };
    if (side === "sell") {
      if (quantity > h.qty) throw err("TRADE_INSUFFICIENT_HOLDINGS", 422, { code });
      if (quantity > h.sellable) throw err("TRADE_T1_SELL_BLOCKED", 422, { code });
    }
    const est = rr.estimateOrder({ side, quantity, price_cents: q.price_cents });
    if (side === "buy" && est.total_cents > s.cash) throw err("TRADE_INSUFFICIENT_FUNDS", 422);
    const day = rr.dayOf(s.pos);
    if (side === "buy") {
      s.cash -= est.total_cents;
      s.lots.push({ key, qty: quantity, day, cost: est.total_cents });
    } else {
      s.cash += est.total_cents;
      let left = quantity;
      for (const l of s.lots.filter((x) => x.key === key && x.day < day)) {
        const take = Math.min(left, l.qty);
        const ratio = take / l.qty;
        l.cost -= Math.round(l.cost * ratio);
        l.qty -= take;
        left -= take;
        if (!left) break;
      }
      s.lots = s.lots.filter((l) => l.qty > 0);
    }
    const trade = {
      id: uuid(),
      seq: s.trades.length + 1,
      code: q.code,
      name: q.name,
      side,
      source: "manual",
      price_type: "market",
      limit_price_cents: null,
      price_cents: q.price_cents,
      quantity,
      gross_cents: est.amount_cents,
      fee_cents: est.fee_cents,
      cash_delta_cents: side === "buy" ? -est.total_cents : est.total_cents,
      realized_pnl_cents: 0,
      prev_close_cents: q.prev_close_cents,
      tick: s.pos,
      trading_day: day,
      clock_minute: R().phaseOf(s.pos) === "open" ? 570 : 900,
      auto_config_id: null,
      created_at: new Date().toISOString(),
    };
    s.trades.push(trade);
    return { trade, unlocked_achievement_ids: [], cash_cents: s.cash, replayed: false };
  }

  /** 推进（05 §5.8 AdvanceOut）：过期 tick → stale；未答题越过截止 → REPLAY_PREDICTION_PENDING */
  function advance(s, body) {
    const p = pack(s.slug);
    const rr = R();
    if (s.settled) throw err("REPLAY_SESSION_SETTLED", 409, { save_id: s.id });
    const to = body.to || "next_phase";
    if (body.expected_tick !== s.pos) return { session: sessionView(s), stale: true, stopped_reason: null, new_feed_items: [], scored_question_ids: [] };
    const from = s.pos;
    const t = rr.targetPos(from, to, p.play_days);
    const plan = rr.checkQuestions(questionStates(s, p), from, t.target, to, !!body.skip_pending);
    if (plan.blocked.length) throw err("REPLAY_PREDICTION_PENDING", 409, { question_ids: plan.blocked });
    for (const id of plan.skip) qst(s, id).skipped = true;
    const newPos = plan.stop ? plan.stop.pos : t.target;
    const scored = [];
    for (const q of p.questions) {
      const pos = rr.questionPositions(q);
      if (pos.resolves > from && pos.resolves <= newPos && qst(s, q.id).answer && !qst(s, q.id).skipped) {
        scoreQuestion(s, p, q);
        scored.push(q.id);
      }
    }
    const newItems = rr.eventsAt(p, newPos, s.masked).filter((e) => e.tick > from);
    s.pos = newPos;
    snapshotsBetween(s, p, from, newPos);
    let stopped = plan.stop ? plan.stop.reason : null;
    if (t.settle && !plan.stop) {
      settle(s, p);
      stopped = "settled";
    }
    return { session: sessionView(s), stale: false, stopped_reason: stopped, new_feed_items: newItems, scored_question_ids: scored };
  }

  function createSession(slug, { masked = true, name } = {}) {
    const p = pack(slug);
    if (!p) throw err("REPLAY_LEVEL_NOT_FOUND", 404, { slug });
    if (masked && !p.masked_allowed) throw err("VALIDATION_ERROR", 422, { field: "masked" });
    const s = {
      id: uuid(),
      name: name || "",
      slug,
      masked: !!masked,
      pos: R().posOf(0, "pre_open"),
      cash: INITIAL_FUND,
      initial: INITIAL_FUND,
      lots: [],
      trades: [],
      qs: {},
      equity: [{ trading_day: -1, equity_cents: INITIAL_FUND, cash_cents: INITIAL_FUND, market_value_cents: 0, kind: "initial" }],
      settled: null,
      holdAllBp: 0,
      created_at: new Date().toISOString(),
    };
    db[s.id] = s;
    return sessionView(s);
  }

  /** 演示用的进行中会话：第 3 日开盘、已在第 2 日收盘前买入 300 股（次日起可卖） */
  function seedDb() {
    db = {};
    const v = createSession("stamp-duty-2023", { masked: true });
    const s = db[v.save_id];
    s.pos = R().posOf(1, "close");
    doOrder(s, { code: "990001", side: "buy", quantity: 300 });
    s.pos = R().posOf(0, "post_close");
    snapshotsBetween(s, pack("stamp-duty-2023"), R().posOf(-1, "post_close"), s.pos);
    s.pos = R().posOf(1, "post_close");
    snapshotsBetween(s, pack("stamp-duty-2023"), R().posOf(0, "post_close"), s.pos);
    qst(s, "q1").skipped = true;
    s.pos = R().posOf(2, "open");
    return s;
  }
  const ensureDb = () => {
    if (!db) seedDb();
    return db;
  };

  /** 关卡列表项（ReplayLevelOut）：匿名标题与导语为默认 */
  function levelOut(spec) {
    const mine = Object.values(ensureDb()).filter((s) => s.slug === spec.slug);
    const settled = mine.filter((s) => s.settled);
    return {
      ...MK().replayLevelBase(spec),
      title: spec.masked_allowed ? spec.title_masked : spec.title,
      teaser: spec.masked_allowed ? spec.teaser_masked : spec.teaser,
      title_real: spec.masked_allowed ? null : spec.title,
      my_best: mine.length
        ? {
            sessions: mine.length,
            settled: settled.length,
            best_points: settled.length ? Math.max(...settled.map((s) => s.settled.points_total)) : null,
            best_excess_bp: settled.length ? Math.max(...settled.map((s) => s.settled.excess_bp)) : null,
          }
        : null,
    };
  }

  const mockApi = {
    async listReplayLevels({ tag, difficulty } = {}) {
      const list = MK()
        .replayLevelSpecs.slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .filter((s) => (!tag || s.tags.includes(tag)) && (!difficulty || s.difficulty === Number(difficulty)))
        .map(levelOut);
      return { items: list, next_cursor: null };
    },
    async createReplaySession(slug, opts) {
      ensureDb();
      const v = createSession(slug, opts);
      state.replay.sessions = null;
      return v;
    },
    async listReplaySessions() {
      const items = Object.values(ensureDb())
        .map(sessionView)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
      state.replay.sessions = items;
      return { items };
    },
    async getReplaySession(saveId) {
      ensureDb();
      return sessionView(sessionOf(saveId));
    },
    async advanceReplay(saveId, body) {
      ensureDb();
      return advance(sessionOf(saveId), body);
    },
    async finishReplay(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      if (s.settled) throw err("REPLAY_SESSION_SETTLED", 409, { save_id: saveId });
      const p = pack(s.slug);
      for (const q of p.questions) {
        const st = qst(s, q.id);
        if (!st.answer && !st.result) st.skipped = true;
      }
      settle(s, p);
      return sessionView(s);
    },
    async getReplayFeed(saveId, { cursor, limit = 20 } = {}) {
      ensureDb();
      const s = sessionOf(saveId);
      const list = R().eventsAt(pack(s.slug), s.pos, s.masked);
      const from = Number(cursor) || 0;
      return { items: list.slice(from, from + limit), next_cursor: from + limit < list.length ? String(from + limit) : null };
    },
    async listReplayQuestions(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      const p = pack(s.slug);
      const items = p.questions
        .filter((q) => R().questionPositions(q).opens <= s.pos)
        .map((q) => R().questionOf(p, q, s.pos, qst(s, q.id), s.masked));
      return { items };
    },
    async answerReplayQuestion(saveId, qid, body) {
      ensureDb();
      const s = sessionOf(saveId);
      if (s.settled) throw err("REPLAY_SESSION_SETTLED", 409, { save_id: saveId });
      const p = pack(s.slug);
      const q = p.questions.find((x) => x.id === qid);
      const pos = q && R().questionPositions(q);
      if (!q || s.pos < pos.opens || s.pos > pos.closes) throw err("REPLAY_QUESTION_CLOSED", 409, { question_id: qid, state: !q ? "missing" : s.pos < pos.opens ? "not_open" : "closed" });
      const st = qst(s, qid);
      if (q.kind === "rank") {
        const keys = (body.order || []).map((c) => R().keyOfCode(p, c, s.masked));
        if (keys.length !== q.top_k || keys.some((k) => !k || !q.stock_keys.includes(k)) || new Set(keys).size !== keys.length) throw err("VALIDATION_ERROR", 422, { field: "order" });
        st.answer = { order: keys };
      } else {
        const probs = body.probs || [];
        if (probs.length !== 5 || probs.some((x) => !Number.isInteger(x) || x < 0) || probs.reduce((a, b) => a + b, 0) !== 100) throw err("VALIDATION_ERROR", 422, { field: "probs" });
        st.answer = { probs: probs.slice() };
      }
      return R().questionOf(p, q, s.pos, st, s.masked);
    },
    async getReplayBenchmark(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      const p = pack(s.slug);
      const points = [];
      for (let d = -p.lookback_days; d <= R().dayOf(s.pos); d++) {
        points.push({ trading_day: d, date: R().isoOf(p, d, s.masked), close: p.benchmark.closes[d + p.lookback_days] });
      }
      return { name: s.masked ? "基准指数" : p.benchmark.name, points };
    },
    async getReplayReveal(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      if (!s.settled) throw err("REPLAY_REVEAL_LOCKED", 409, { save_id: saveId });
      const p = pack(s.slug);
      const rr = R();
      const last = rr.lastPos(p.play_days);
      const sess = sessionView(s);
      const stocks = p.stocks.map((st) => ({
        code: rr.identityOf(p, st.key, s.masked).code,
        real_code: st.real_code,
        real_name: st.real_name,
        industry: st.industry,
        candles: fullCandles(p, st.key),
        play_range: [0, p.play_days - 1],
      }));
      // 揭示后题目里的代码与名称是真实的（同服务端）；my_answer 仍是会话内提交的别名代码
      const questions = p.questions.map((q) => {
        const v = rr.questionOf(p, q, last, qst(s, q.id), false);
        return { ...v, my_answer: rr.questionOf(p, q, last, qst(s, q.id), true).my_answer };
      });
      const events = rr.eventsAt(p, last, false).map((e) => ({ ...e, impact: mockImpact(e) }));
      return {
        session: sess,
        commentary: p.commentary,
        stocks,
        benchmark: { name: p.benchmark.name, points: p.benchmark.closes.map((c, j) => ({ trading_day: j - p.lookback_days, date: p.calendar[j], close: c })) },
        events,
        questions,
        equity: s.equity.slice(),
        trades_count: s.trades.length,
        hold_all_return_bp: s.holdAllBp,
        benchmark_return_bp: s.settled.benchmark_return_bp,
      };
    },
    async loadReplayMarket(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      const p = pack(s.slug);
      const stocks = p.stocks.map((st) => R().quoteOf(p, st.key, s.pos, s.masked));
      return { stocks, total: stocks.length, next_cursor: null };
    },
    async loadReplayStock(saveId, code) {
      ensureDb();
      const s = sessionOf(saveId);
      const p = pack(s.slug);
      const key = R().keyOfCode(p, code, s.masked);
      if (!key) throw err("STOCK_NOT_FOUND", 404, { code });
      return { ...R().quoteOf(p, key, s.pos, s.masked), candles: R().candlesAt(p, key, s.pos, s.masked), order_book: { bids: [], asks: [] } };
    },
    async loadReplayPortfolio(saveId) {
      ensureDb();
      const s = sessionOf(saveId);
      const p = pack(s.slug);
      const rr = R();
      const holdings = lotsByKey(s).map((h) => {
        const q = rr.quoteOf(p, h.key, s.pos, s.masked);
        const mv = h.qty * q.price_cents;
        return {
          code: q.code,
          name: q.name,
          quantity: h.qty,
          sellable_quantity: h.sellable,
          avg_price_cents: Math.round(h.cost / h.qty),
          total_cost_cents: h.cost,
          market_price_cents: q.price_cents,
          market_value_cents: mv,
          pnl_cents: mv - h.cost,
          pnl_bp: h.cost ? Math.round(((mv - h.cost) * 10000) / h.cost) : 0,
        };
      });
      const mv = holdings.reduce((a, h) => a + h.market_value_cents, 0);
      const equity = s.cash + mv;
      const prevEq = s.equity.length ? s.equity[s.equity.length - 1].equity_cents : s.initial;
      return {
        tick: s.pos,
        trading_day: rr.dayOf(s.pos),
        cash_cents: s.cash,
        initial_fund_cents: s.initial,
        market_value_cents: mv,
        equity_cents: equity,
        net_pnl_cents: equity - s.initial,
        holdings,
        prev_equity_cents: prevEq,
        day_pnl_cents: equity - prevEq,
        day_pnl_bp: prevEq ? Math.round(((equity - prevEq) * 10000) / prevEq) : 0,
      };
    },
    async replayOrder(saveId, body) {
      ensureDb();
      const out = doOrder(sessionOf(saveId), body);
      return out;
    },
  };

  /** 揭示用的日 K（真实价、真实日期，含揭示期）：整个关卡包的 K 线 */
  function fullCandles(p, key) {
    const out = [];
    for (let d = -p.lookback_days; d < p.play_days + p.reveal_days; d++) {
      const b = R().barAt(p, key, d);
      out.push({ trading_day: d, date: p.calendar[d + p.lookback_days], open_cents: b.o, high_cents: b.h, low_cents: b.l, close_cents: b.c, volume: b.v });
    }
    return out;
  }

  /** 揭示用的事件影响（相对基准的超额收益，bp）：mock 按重要度给固定值，仅用于界面展示 */
  function mockImpact(e) {
    const base = e.importance >= 3 ? 420 : e.importance === 2 ? 180 : -90;
    return { ar_1d_bp: base, ar_5d_bp: Math.round(base * 0.6) };
  }

  // ---------- real ----------
  const api = SS.api;
  async function guarded(fn) {
    if (api.missing.has("replay")) throw new ApiError("FEATURE_UNAVAILABLE", 404);
    try {
      return await fn();
    } catch (e) {
      if (api.isMissing(e)) {
        api.missing.add("replay");
        throw new ApiError("FEATURE_UNAVAILABLE", 404);
      }
      throw e;
    }
  }
  const sid = (id) => encodeURIComponent(id);
  const realApi = {
    listReplayLevels: ({ tag, difficulty, cursor, limit = 20 } = {}) => guarded(() => api.get("/replay/levels", { query: qs({ tag, difficulty, cursor, limit }) })),
    createReplaySession: (slug, { masked = true, name } = {}) =>
      guarded(() => api.post("/replay/sessions", { body: qs({ level_slug: slug, masked, name }) })),
    listReplaySessions: () => guarded(() => api.get("/replay/sessions")).then((r) => ((state.replay.sessions = r.items), r)),
    getReplaySession: (saveId) => guarded(() => api.get(`/replay/sessions/${sid(saveId)}`)),
    advanceReplay: (saveId, { to = "next_phase", expected_tick, skip_pending = false } = {}) =>
      guarded(() => api.post(`/replay/sessions/${sid(saveId)}/advance`, { body: { to, expected_tick, skip_pending } })),
    finishReplay: (saveId) => guarded(() => api.post(`/replay/sessions/${sid(saveId)}/finish`)),
    getReplayFeed: (saveId, { cursor, limit = 20 } = {}) => guarded(() => api.get(`/replay/sessions/${sid(saveId)}/feed`, { query: qs({ cursor, limit }) })),
    listReplayQuestions: (saveId) => guarded(() => api.get(`/replay/sessions/${sid(saveId)}/questions`)),
    answerReplayQuestion: (saveId, qid, { probs, order } = {}) =>
      guarded(() => api.put(`/replay/sessions/${sid(saveId)}/questions/${sid(qid)}/answer`, { body: qs({ probs, order }) })),
    getReplayBenchmark: (saveId) => guarded(() => api.get(`/replay/sessions/${sid(saveId)}/benchmark`)),
    getReplayReveal: (saveId) => guarded(() => api.get(`/replay/sessions/${sid(saveId)}/reveal`)),
    loadReplayMarket: (saveId) => guarded(() => api.get(`/saves/${sid(saveId)}/market`, { query: { limit: 50 } })),
    loadReplayStock: (saveId, code) => guarded(() => api.get(`/saves/${sid(saveId)}/market/${sid(code)}`)),
    loadReplayPortfolio: (saveId) => guarded(() => api.get(`/saves/${sid(saveId)}/portfolio`)),
    replayOrder: (saveId, { code, side, quantity }) =>
      guarded(() =>
        api.post(`/saves/${sid(saveId)}/orders`, {
          body: { code, side, quantity, price_type: "market", limit_price_cents: null, confirm_deviation: false },
          headers: { "Idempotency-Key": uuid() },
        })
      ),
  };

  Object.assign(SS.store, { resetReplay }, SS.isMock ? mockApi : realApi);
  SS.assertSameKeys("replay", mockApi, realApi);
})();
