/**
 * 预测卡 / 积分 / 情报卡 / 称号的数据层：mock 与 real 两套同名方法（02 §12.1），按 SS.isMock 挂到 SS.store 上。
 *
 *   ensureCards({force})                     首屏：待答卡 + 最近 50 张（state.predict.cards / openCards / byEvent）
 *   listPredictions({status,cursor,limit})   GET  /saves/{id}/predictions           → {items,next_cursor}
 *   loadPrediction(id)                       GET  /saves/{id}/predictions/{card_id}
 *   answerPrediction(id, answers, {resume})  POST …/answer  → {card, clock}（clock 交给 applyClock）
 *   skipPrediction(id, {resume})             POST …/skip    → {card, clock}
 *   loadPredictionSettings() / setPredictionMode(mode)       GET|PUT /saves/{id}/predictions/settings
 *   loadPoints() / listLedger({cursor,reason}) / loadPointStats({saveId}) / loadTitles() / equipTitle(id)
 *   loadIntel() / buyEdgeReveal(edgeId, level) / buyRumorHint(eventId)
 * 共用（不计入 mock/real 对照）：predictEnabled()、resetPredict()、upsertCard(card)。
 * real 经 guarded()：后端没有该接口（HTTP_404/405/501）时抛 FEATURE_UNAVAILABLE 并记入 SS.api.missing。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { ApiError } = SS;
  const state = SS.store.state;
  const blank = () => ({ saveId: null, cards: [], openCards: [], byEvent: {}, loaded: false, points: null, titles: null, settings: null, intel: null, stats: null });
  state.predict = state.predict || blank();

  const resetPredict = () => Object.assign(state.predict, blank());
  /** 当前存档是否开启事件模式（预测卡只存在于事件模式存档） */
  const enabled = () => !!state.save && state.save.events_enabled === true;

  /** 把一张卡并入缓存（按 id 替换或追加），重算 openCards 与 byEvent */
  function upsertCard(card) {
    const p = state.predict;
    const i = p.cards.findIndex((c) => c.id === card.id);
    if (i >= 0) p.cards[i] = card;
    else p.cards.unshift(card);
    p.openCards = p.cards.filter((c) => c.status === "open");
    p.byEvent = {};
    for (const c of p.cards) p.byEvent[c.event_id] = c;
  }

  // ---------- mock ----------
  const D = () => SS.mockFeatures.predict;
  const sortCards = (list) => list.slice().sort((a, b) => b.opened_trading_tick - a.opened_trading_tick || (a.id < b.id ? 1 : -1));
  function mockPage(list, { cursor, limit = 20 }) {
    const from = Number(cursor) || 0;
    const items = list.slice(from, from + limit).map(D().pub);
    return { items, next_cursor: from + limit < list.length ? String(from + limit) : null };
  }
  const mockCardsOf = () => D().cards;
  const withEvent = (c) => {
    const out = D().pub(c);
    out.event = { ...SS.mockFeatures.news.events.find((e) => e.event.event_id === c.event_id).event };
    return out;
  };
  const mockLoad = (id) => {
    const c = mockCardsOf().find((x) => x.id === id);
    if (!c) throw new ApiError("PREDICTION_NOT_FOUND", 404, { card_id: id });
    return c;
  };
  const mockEnsureDone = () => state.predict.loaded && state.predict.saveId === state.save.id;
  const mockClosed = (c) => {
    if (c.status !== "open" && c.status !== "answered") throw new ApiError("PREDICTION_CLOSED", 409, { card_id: c.id, status: c.status });
  };

  const mock = {
    async ensureCards({ force = false } = {}) {
      if (!force && mockEnsureDone()) return;
      const p = state.predict;
      p.saveId = state.save.id;
      p.cards = sortCards(mockCardsOf()).slice(0, 50).map(withEvent);
      p.openCards = p.cards.filter((c) => c.status === "open");
      p.byEvent = Object.fromEntries(p.cards.map((c) => [c.event_id, c]));
      p.loaded = true;
    },
    listPredictions({ status = "all", cursor, limit = 20 } = {}) {
      const list = sortCards(mockCardsOf()).filter((c) => status === "all" || c.status === status);
      return Promise.resolve(mockPage(list.map(withEvent), { cursor, limit }));
    },
    loadPrediction: (id) => Promise.resolve(withEvent(mockLoad(id))),
    answerPrediction(id, answers, { resume = true } = {}) {
      const c = mockLoad(id);
      mockClosed(c);
      try {
        const out = SS.mockFeatures.predict.sim.answer(c, answers, resume);
        upsertCard(withEvent(c));
        return Promise.resolve({ ...out, card: withEvent(c) });
      } catch (err) {
        return Promise.reject(err);
      }
    },
    skipPrediction(id, { resume = true } = {}) {
      const c = mockLoad(id);
      mockClosed(c);
      const out = SS.mockFeatures.predict.sim.skip(c, resume);
      upsertCard(withEvent(c));
      return Promise.resolve({ ...out, card: withEvent(c) });
    },
    loadPredictionSettings: () => Promise.resolve({ ...D().settings }),
    setPredictionMode(mode) {
      D().settings = { mode, forced: false };
      return Promise.resolve({ ...D().settings });
    },
    loadPoints: () => {
      const d = D();
      state.predict.points = { ...d.points, equipped_title: d.titles.equipped };
      return Promise.resolve(state.predict.points);
    },
    listLedger: ({ cursor, limit = 30, reason } = {}) => {
      const list = D().ledger.filter((x) => !reason || x.reason === reason);
      return Promise.resolve(mockPage(list, { cursor, limit }));
    },
    loadPointStats: () => Promise.resolve({ ...D().stats }),
    loadTitles() {
      const d = D();
      const items = SS.predictTitles.list.map((t) => ({ id: t.id, level: t.level, unlocked_at: d.titles.unlocked[t.id] || null }));
      state.predict.titles = { items, equipped: d.titles.equipped };
      return Promise.resolve(state.predict.titles);
    },
    equipTitle(id) {
      const d = D();
      if (id && !d.titles.unlocked[id]) return Promise.reject(new ApiError("TITLE_NOT_UNLOCKED", 409, { title_id: id }));
      d.titles.equipped = id || null;
      d.points.equipped_title = id || null;
      return mock.loadPoints();
    },
    loadIntel() {
      const d = D();
      const out = { ...d.intel, balance: d.points.balance };
      state.predict.intel = out;
      return Promise.resolve(out);
    },
    buyEdgeReveal(edgeId, level) {
      const d = D();
      const news = SS.mockFeatures.news;
      const edge = news.chain.edges.find((e) => e.id === edgeId);
      if (!edge) return Promise.reject(new ApiError("SUPPLY_EDGE_NOT_FOUND", 404, { edge_id: edgeId }));
      const cur = edge.revealed_level || 0;
      if (cur >= level) return Promise.resolve({ charged: 0, balance: d.points.balance, edge: null, hint: null });
      if (d.intel.used_today >= d.intel.daily_limit) return Promise.reject(new ApiError("INTEL_LIMIT_REACHED", 409, { limit: d.intel.daily_limit }));
      const price = level === 1 ? d.intel.prices.edge_l1 : d.intel.prices.edge_l2 - (cur >= 1 ? d.intel.prices.edge_l1 : 0);
      if (d.points.balance < price) return Promise.reject(new ApiError("POINTS_INSUFFICIENT", 422, { required: price, balance: d.points.balance }));
      d.points.balance -= price;
      d.points.lifetime_spent += price;
      d.intel.used_today += 1;
      edge.revealed_level = level;
      edge.strength = edge._strength;
      edge.lag_days = level >= 2 ? edge._lag : null;
      const row = { edge_id: edge.id, from_industry: edge.from_industry, to_industry: edge.to_industry, relation: edge.relation, sign: edge.sign, strength: edge._strength, lag_days: level >= 2 ? edge._lag : null, level };
      d.intel.edges = d.intel.edges.filter((x) => x.edge_id !== edgeId).concat([row]);
      return Promise.resolve({ charged: price, balance: d.points.balance, edge: row, hint: null });
    },
    buyRumorHint(eventId) {
      const d = D();
      const ev = SS.mockFeatures.news.events.find((e) => e.event.event_id === eventId);
      if (!ev) return Promise.reject(new ApiError("EVENT_NOT_FOUND", 404, { event_id: eventId }));
      if (ev.event.rumor_status && ev.event.rumor_status !== "unresolved") return Promise.reject(new ApiError("INTEL_UNAVAILABLE", 409, { card: "rumor_hint", reason: "resolved" }));
      const have = d.intel.rumor_hints.find((h) => h.event_id === eventId);
      if (have) return Promise.resolve({ charged: 0, balance: d.points.balance, edge: null, hint: have });
      if (d.intel.used_today >= d.intel.daily_limit) return Promise.reject(new ApiError("INTEL_LIMIT_REACHED", 409, { limit: d.intel.daily_limit }));
      const price = d.intel.prices.rumor_hint;
      if (d.points.balance < price) return Promise.reject(new ApiError("POINTS_INSUFFICIENT", 422, { required: price, balance: d.points.balance }));
      const truth = d.rumorTruth[eventId] !== false;
      const hint = { event_id: eventId, hint: truth ? "likely_true" : "likely_false", accuracy_pct: 80 };
      d.points.balance -= price;
      d.points.lifetime_spent += price;
      d.intel.used_today += 1;
      d.intel.rumor_hints.push(hint);
      return Promise.resolve({ charged: price, balance: d.points.balance, edge: null, hint });
    },
  };

  // ---------- real ----------
  const api = SS.api;
  const P = (p) => `/saves/${state.save.id}${p}`;
  /** 缺失接口 → FEATURE_UNAVAILABLE；会话内记住，不再请求 */
  async function guarded(fn) {
    if (api.missing.has("predict")) throw new ApiError("FEATURE_UNAVAILABLE", 404);
    try {
      return await fn();
    } catch (err) {
      if (api.isMissing(err)) {
        api.missing.add("predict");
        throw new ApiError("FEATURE_UNAVAILABLE", 404);
      }
      throw err;
    }
  }
  const applyClock = (c) => c && SS.store.applyClock && SS.store.applyClock(c);

  const real = {
    async ensureCards({ force = false } = {}) {
      const p = state.predict;
      const sid = state.save.id;
      if (!force && p.loaded && p.saveId === sid) return;
      const [open, all] = await guarded(() =>
        Promise.all([api.get(P("/predictions"), { query: { status: "open", limit: 50 } }), api.get(P("/predictions"), { query: { limit: 50 } })])
      );
      if (state.save.id !== sid) return;
      const map = new Map();
      for (const c of [...open.items, ...all.items]) map.set(c.id, c);
      p.saveId = sid;
      p.cards = [...map.values()].sort((a, b) => b.opened_trading_tick - a.opened_trading_tick);
      p.openCards = p.cards.filter((c) => c.status === "open");
      p.byEvent = Object.fromEntries(p.cards.map((c) => [c.event_id, c]));
      p.loaded = true;
    },
    listPredictions: ({ status, cursor, limit = 20 } = {}) => guarded(() => api.get(P("/predictions"), { query: { status, cursor, limit } })),
    async loadPrediction(id) {
      const c = await guarded(() => api.get(P(`/predictions/${encodeURIComponent(id)}`)));
      upsertCard(c);
      return c;
    },
    async answerPrediction(id, answers, { resume = true } = {}) {
      const out = await guarded(() => api.post(P(`/predictions/${encodeURIComponent(id)}/answer`), { body: { answers, resume } }));
      applyClock(out.clock);
      upsertCard(out.card);
      return out;
    },
    async skipPrediction(id, { resume = true } = {}) {
      const out = await guarded(() => api.post(P(`/predictions/${encodeURIComponent(id)}/skip`), { body: { resume } }));
      applyClock(out.clock);
      upsertCard(out.card);
      return out;
    },
    loadPredictionSettings: () => guarded(() => api.get(P("/predictions/settings"))),
    setPredictionMode: (mode) => guarded(() => api.put(P("/predictions/settings"), { body: { mode } })),
    async loadPoints() {
      state.predict.points = await guarded(() => api.get("/points"));
      return state.predict.points;
    },
    listLedger: ({ cursor, limit = 30, reason } = {}) => guarded(() => api.get("/points/ledger", { query: { cursor, limit, reason } })),
    loadPointStats: ({ saveId } = {}) => guarded(() => api.get("/points/stats", { query: { save_id: saveId } })),
    async loadTitles() {
      state.predict.titles = await guarded(() => api.get("/points/titles"));
      return state.predict.titles;
    },
    equipTitle: (id) => guarded(() => api.put("/points/title", { body: { title_id: id || null } })).then((p) => ((state.predict.points = p), p)),
    async loadIntel() {
      state.predict.intel = await guarded(() => api.get(P("/intel")));
      return state.predict.intel;
    },
    buyEdgeReveal: (edgeId, level) => guarded(() => api.post(P("/intel/edges"), { body: { edge_id: edgeId, level } })),
    buyRumorHint: (eventId) => guarded(() => api.post(P("/intel/rumor-hints"), { body: { event_id: eventId } })),
  };

  // 共用方法（不计入 mock/real 对照）
  const shared = { predictEnabled: enabled, resetPredict, upsertCard };
  Object.assign(SS.store, shared, SS.isMock ? mock : real);
  SS.assertSameKeys("predict", mock, real);
})();
