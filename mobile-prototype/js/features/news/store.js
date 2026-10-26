/**
 * 快讯 / 事件 / 产业链的数据层：mock 与 real 两套同名方法，按 SS.isMock 挂到 SS.store 上。
 *
 *   ensureNews({force})        首屏：最近快讯（state.news.items）与重大快讯（state.news.majors）；事件模式关闭时不调用
 *   newsFeed() / majorNews()   同步读取缓存
 *   listNews({cursor,limit,major,code,industry})      GET /saves/{id}/news          → {items, next_cursor}
 *   listEvents({cursor,limit,phase,major,code,industry}) GET /saves/{id}/events      → {items, next_cursor}
 *   loadEvent(eventId)         GET /saves/{id}/events/{event_id}                     → EventDetailOut
 *   loadEventMarks(code, days) GET /saves/{id}/market/{code}/event-marks             → {code, items: EventMarkOut[]}（K 线标注，服务端按 tick 降序）
 *   loadSupplyChain({force})   GET /saves/{id}/supply-chain（按存档缓存）            → SupplyChainOut
 *
 * real 版经 guarded()：后端没有该接口（HTTP_404/405/501）时抛 FEATURE_UNAVAILABLE 并记入 SS.api.missing，本会话不再请求；
 * 业务错误（EVENTS_DISABLED、EVENT_NOT_FOUND 等）原样抛出，由页面处理。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const M = SS.newsModel;
  const { ApiError } = SS;
  const state = SS.store.state;
  state.news = state.news || { saveId: null, items: [], majors: [], loaded: false, chain: null };

  const resetNews = () => Object.assign(state.news, { saveId: null, items: [], majors: [], loaded: false, chain: null });
  /** 公开形态：去掉 mock 私有字段 */
  const pub = (n) => {
    const { _queued, ...rest } = n;
    return rest;
  };
  /** 当前存档是否开启事件模式（SaveOut.events_enabled） */
  const enabled = () => !!state.save && state.save.events_enabled === true;

  // ---------- mock ----------
  const mockData = () => SS.mockFeatures.news;
  const mockEvents = () => mockData().events.filter((e) => e.news.some((n) => !n._queued));
  const nowTick = () => {
    const c = state.clock;
    return c.trading_day * 242 + (c.clock_minute <= 690 ? c.clock_minute - 570 : c.clock_minute - 659);
  };
  const mockPublished = (e) => e.news.filter((n) => !n._queued);
  /** EventOut：标题取最早一条已发布快讯（与后端 first_seen 口径一致） */
  const mockEventOut = (e) => {
    const news = mockPublished(e).slice().sort((a, b) => a.trading_tick - b.trading_tick);
    return { ...e.event, title: news.length ? news[0].title : e.event.title };
  };
  function mockPage(list, { cursor, limit = 30 }) {
    const from = Number(cursor) || 0;
    const items = list.slice(from, from + limit);
    return { items, next_cursor: from + limit < list.length ? String(from + limit) : null };
  }
  const mockFeed = () => M.sortNews(mockData().events.flatMap((e) => mockPublished(e)).map(pub));

  const mock = {
    ensureNews({ force = false } = {}) {
      const n = state.news;
      if (!force && n.loaded && n.saveId === state.save.id) return Promise.resolve();
      const all = mockFeed();
      n.saveId = state.save.id;
      n.items = all.slice(0, M.FEED_LIMIT);
      n.majors = all.filter((x) => x.major).slice(0, M.MAJOR_LIMIT);
      n.loaded = true;
      return Promise.resolve();
    },
    newsFeed: () => state.news.items,
    majorNews: () => state.news.majors,
    listNews({ cursor, limit, major, code, industry } = {}) {
      let list = mockFeed();
      if (major) list = list.filter((x) => x.major);
      if (code) list = list.filter((x) => x.code === code);
      if (industry) list = list.filter((x) => x.industry === industry);
      return Promise.resolve(mockPage(list, { cursor, limit }));
    },
    listEvents({ cursor, limit = 20, major, phase, code, industry } = {}) {
      let list = mockEvents().map(mockEventOut);
      if (major) list = list.filter((x) => x.major);
      if (phase) list = list.filter((x) => x.phase === phase);
      if (code) list = list.filter((x) => x.source_code === code);
      if (industry) list = list.filter((x) => x.source_industry === industry);
      list.sort((a, b) => b.first_seen_trading_tick - a.first_seen_trading_tick || (a.event_id < b.event_id ? 1 : -1));
      return Promise.resolve(mockPage(list, { cursor, limit }));
    },
    loadEvent(eventId) {
      const e = mockEvents().find((x) => x.event.event_id === eventId);
      if (!e) return Promise.reject(new ApiError("EVENT_NOT_FOUND", 404, { event_id: eventId }));
      const now = nowTick();
      const news = mockPublished(e).map(pub).sort((a, b) => a.trading_tick - b.trading_tick || (a.news_id < b.news_id ? -1 : 1));
      const propagation = e.propagation.filter((p) => p.arrived_trading_tick <= now);
      return Promise.resolve({ ...mockEventOut(e), news, propagation });
    },
    /** 与后端 event_marks 同口径：source（事发股或事发行业）/ market（全市场）/ propagated（传导到本股行业，取最早到达）；只含当前时刻已发生的 */
    loadEventMarks(code, days = 60) {
      const q = SS.store.quote(code);
      if (!q) return Promise.reject(new ApiError("STOCK_NOT_FOUND", 404, { code }));
      const now = nowTick();
      const lo = Math.max(0, state.clock.trading_day - days);
      const items = [];
      for (const e of mockEvents()) {
        const ev = mockEventOut(e);
        let role = null;
        let tick = null;
        if (ev.scope === "market") {
          role = "market";
          tick = ev.publish_trading_tick;
        } else if ((ev.scope === "stock" && ev.source_code === code) || ev.source_industry === q.industry) {
          role = "source";
          tick = ev.publish_trading_tick;
        } else {
          const arrivals = e.propagation.filter((p) => p.industry === q.industry && p.hop > 0 && p.arrived_trading_tick <= now).map((p) => p.arrived_trading_tick);
          if (arrivals.length) {
            role = "propagated";
            tick = Math.min(...arrivals);
          }
        }
        if (!role || tick == null || tick > now || ev.trading_day < lo) continue;
        items.push({ event_id: ev.event_id, trading_day: ev.trading_day, trading_tick: tick, role, major: ev.major, kind: ev.kind, sentiment: ev.sentiment, title: ev.title });
      }
      items.sort((a, b) => b.trading_tick - a.trading_tick || (a.event_id < b.event_id ? -1 : 1));
      return Promise.resolve({ code, items });
    },
    loadSupplyChain({ force = false } = {}) {
      if (!force && state.news.chain && state.news.chain.saveId === state.save.id) return Promise.resolve(state.news.chain.data);
      state.news.chain = { saveId: state.save.id, data: mockData().chain };
      return Promise.resolve(mockData().chain);
    },
  };

  // ---------- real ----------
  const api = SS.api;
  const P = (p) => `/saves/${state.save.id}${p}`;

  /** 缺失接口（404/405/501）→ FEATURE_UNAVAILABLE；会话内记住，不再请求 */
  async function guarded(fn) {
    if (api.missing.has("news")) throw new ApiError("FEATURE_UNAVAILABLE", 404);
    try {
      return await fn();
    } catch (err) {
      if (api.isMissing(err)) {
        api.missing.add("news");
        throw new ApiError("FEATURE_UNAVAILABLE", 404);
      }
      throw err;
    }
  }

  const real = {
    async ensureNews({ force = false } = {}) {
      const n = state.news;
      const sid = state.save.id;
      if (!force && n.loaded && n.saveId === sid) return;
      if (n.saveId !== sid) resetNews();
      const [all, major] = await guarded(() =>
        Promise.all([api.get(P("/news"), { query: { limit: 30 } }), api.get(P("/news"), { query: { major: true, limit: M.MAJOR_LIMIT } })])
      );
      if (state.save.id !== sid) return; // 切换存档期间的旧结果丢弃
      n.saveId = sid;
      n.items = M.mergeNews(n.items, all.items);
      n.majors = M.mergeNews(n.majors, major.items, M.MAJOR_LIMIT);
      n.loaded = true;
    },
    newsFeed: () => state.news.items,
    majorNews: () => state.news.majors,
    listNews: ({ cursor, limit = 30, major, code, industry } = {}) =>
      guarded(() => api.get(P("/news"), { query: { cursor, limit, major, code, industry } })),
    listEvents: ({ cursor, limit = 20, major, phase, code, industry } = {}) =>
      guarded(() => api.get(P("/events"), { query: { cursor, limit, major, phase, code, industry } })),
    loadEvent: (eventId) => guarded(() => api.get(P(`/events/${encodeURIComponent(eventId)}`))),
    loadEventMarks: (code, days = 60) => guarded(() => api.get(P(`/market/${encodeURIComponent(code)}/event-marks`), { query: { days } })),
    async loadSupplyChain({ force = false } = {}) {
      const sid = state.save.id;
      if (!force && state.news.chain && state.news.chain.saveId === sid) return state.news.chain.data;
      const data = await guarded(() => api.get(P("/supply-chain")));
      if (state.save.id === sid) state.news.chain = { saveId: sid, data };
      return data;
    },
  };

  // 两种模式共用的方法（不计入 mock/real 对照）
  const shared = { newsEnabled: enabled, resetNews };
  Object.assign(SS.store, shared, SS.isMock ? mock : real);
  SS.assertSameKeys("news", mock, real);
})();
