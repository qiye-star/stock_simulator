/**
 * 预测市场（⑧ D）的数据层：mock 与 real 两套同名方法，按 SS.isMock 挂到 SS.store 上（04 §9.1、§10.3、08 §5.8）。
 *
 *   listPredictionMarkets({challenge_id, status, cursor, limit})  GET /prediction-markets → PmMarketPageOut
 *   loadPredictionMarket(id)               GET /prediction-markets/{id} → PmMarketDetailOut（缓存 state.pm.byId，记 balance）
 *   quotePredictionMarket(id, {side, outcome, shares, budget_points})  GET …/quote → PmQuoteOut
 *   tradePredictionMarket(id, body)        POST …/trades（Idempotency-Key 每次新生成）→ PmTradeResultOut
 *   loadPredictionHistory(id)              GET …/history → PmHistoryOut
 *   listMyPredictionPositions({status,cursor})  GET /me/prediction-positions → {items, next_cursor}
 *   listMyPredictionSettlements(cursor)    GET /me/prediction-settlements → {items, next_cursor}
 *   watchPredictions(challengeId?) / unwatchPredictions()
 *       页面存活期间的引用计数：real 打开全服 WS /ws/prediction-markets（断线后 3 s 轮询）；mock 每 4 s 模拟一次全服成交
 *   subscribePrediction(id) / unsubscribePrediction(id)   详情页订阅单个市场（real 发 subscribe/unsubscribe，每连接最多 20 个）
 * 共用（不计入 mock/real 对照）：
 *   onPredictions(fn) → 取消函数；事件 {type:"tick", id, seq, status, prices_ppm, volume_shares, public_tt}
 *                                    | {type:"list", challenge_id, rev} | {type:"resolved", id, status, winning_outcome}
 * real 经 guarded()：后端没有该接口（HTTP_404/405/501）时抛 FEATURE_UNAVAILABLE 并记入 SS.api.missing，本会话不再请求；
 * 业务错误（PM_NOT_FOUND、PM_NOT_OPEN、PM_SLIPPAGE_EXCEEDED …）原样抛出，由页面处理。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { ApiError } = SS;
  const state = SS.store.state;
  const blank = () => ({ refs: 0, challengeId: null, subs: [], byId: {}, balance: null });
  state.pm = Object.assign(blank(), state.pm || {});
  const MODEL = () => SS.pmModel;

  // 进程内广播（不走 SS.store.on：没有取消订阅接口，页面离开时需要移除）
  const listeners = new Set();
  const emitPm = (msg) => listeners.forEach((fn) => {
    try {
      fn(msg);
    } catch (e) {
      console.warn("pm 监听器异常", e);
    }
  });
  const onPredictions = (fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  };

  const qs = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v != null && v !== ""));
  const uuid = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

  // ---------- mock ----------
  const M = () => SS.mockFeatures.pm;
  let tickT = null;
  function startMockTicks() {
    if (tickT) return;
    tickT = setInterval(() => {
      for (const t of M().nudge()) emitPm({ type: "tick", ...t });
    }, 4000);
  }
  const stopMockTicks = () => {
    clearInterval(tickT);
    tickT = null;
  };

  const mock = {
    async listPredictionMarkets(q = {}) {
      return M().list(q);
    },
    async loadPredictionMarket(id) {
      const d = M().detail(id);
      state.pm.byId[id] = d;
      state.pm.balance = d.balance_points;
      return d;
    },
    async quotePredictionMarket(id, q) {
      return M().quote(id, q);
    },
    async tradePredictionMarket(id, body) {
      const r = M().trade(id, body);
      state.pm.balance = r.balance_points;
      return r;
    },
    async loadPredictionHistory(id) {
      return M().history(id);
    },
    async listMyPredictionPositions(q = {}) {
      return M().positions(q);
    },
    async listMyPredictionSettlements() {
      return M().settlements();
    },
    watchPredictions(challengeId) {
      state.pm.refs += 1;
      if (challengeId) state.pm.challengeId = challengeId;
      startMockTicks();
    },
    unwatchPredictions() {
      state.pm.refs = Math.max(0, state.pm.refs - 1);
      if (!state.pm.refs) {
        stopMockTicks();
        state.pm.subs = [];
      }
    },
    subscribePrediction(id) {
      if (!state.pm.subs.includes(id) && state.pm.subs.length < 20) state.pm.subs.push(id);
    },
    unsubscribePrediction(id) {
      state.pm.subs = state.pm.subs.filter((x) => x !== id);
    },
  };

  // ---------- real ----------
  const api = SS.api;
  /** 缺失接口 → FEATURE_UNAVAILABLE；会话内记住，不再请求 */
  async function guarded(fn) {
    if (api.missing.has("pm")) throw new ApiError("FEATURE_UNAVAILABLE", 404);
    try {
      return await fn();
    } catch (err) {
      if (api.isMissing(err)) {
        api.missing.add("pm");
        throw new ApiError("FEATURE_UNAVAILABLE", 404);
      }
      throw err;
    }
  }

  let ws = null;
  let wsT = null;
  let pollT = null;
  let attempt = 0;
  let pollSig = "";

  const send = (obj) => {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
  };

  /** 把公开的 PmMarketDetailOut / 列表项的最新状态写进缓存（只接受更新的 seq） */
  function cacheMerge(msg) {
    const c = state.pm.byId[msg.id];
    if (c) state.pm.byId[msg.id] = MODEL().applyTick(c, msg);
  }

  function onWsMessage(msg) {
    switch (msg.t) {
      case "pm_tick": {
        const { t, ...rest } = msg;
        cacheMerge(rest);
        emitPm({ type: "tick", ...rest });
        break;
      }
      case "pm_list":
        emitPm({ type: "list", challenge_id: msg.challenge_id, rev: msg.rev });
        break;
      case "pm_resolved":
        emitPm({ type: "resolved", id: msg.id, status: msg.status, winning_outcome: msg.winning_outcome });
        break;
      case "error":
        if (msg.code === "AUTH_REQUIRED") api.onUnauthorized && api.onUnauthorized(new ApiError("AUTH_REQUIRED", 401));
        break;
      default:
        break; // subscribed / unsubscribed / pong 不需要处理
    }
  }

  function connect() {
    if (ws || state.pm.refs <= 0) return;
    let sock;
    try {
      sock = new WebSocket(api.wsUrl("/ws/prediction-markets"));
    } catch (_) {
      startPoll();
      return;
    }
    ws = sock;
    sock.onopen = () => {
      attempt = 0;
      stopPoll();
      if (state.pm.challengeId) send({ t: "watch", challenge_id: state.pm.challengeId });
      state.pm.subs.forEach((id) => send({ t: "subscribe", market_id: id }));
    };
    sock.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }
      onWsMessage(msg);
    };
    sock.onclose = (ev) => {
      if (ws === sock) ws = null;
      if (state.pm.refs <= 0) return;
      if (ev.code === 4401) return api.onUnauthorized && api.onUnauthorized(new ApiError("AUTH_REQUIRED", 401));
      startPoll();
      wsT = setTimeout(connect, Math.min(10000, 1000 * 2 ** attempt++));
    };
  }

  function closeSocket() {
    clearTimeout(wsT);
    wsT = null;
    stopPoll();
    if (ws) {
      const s = ws;
      ws = null;
      s.onclose = null;
      s.close();
    }
  }

  function startPoll() {
    if (!pollT) pollT = setInterval(pollOnce, 3000);
  }
  function stopPoll() {
    clearInterval(pollT);
    pollT = null;
  }

  /** WS 不可用时的退化：列表签名变化 → list；订阅市场的 seq 变化 → tick（04 §8.3 的 3 s 轮询） */
  async function pollOnce() {
    if (state.pm.refs <= 0) return;
    try {
      const page = await real.listPredictionMarkets({ challenge_id: state.pm.challengeId || undefined, status: "all" });
      const sig = page.items.map((m) => `${m.id}:${m.status}:${m.trade_seq}`).join("|");
      if (sig !== pollSig) {
        pollSig = sig;
        emitPm({ type: "list", challenge_id: state.pm.challengeId, rev: null });
      }
      for (const id of state.pm.subs.slice()) {
        const d = await real.loadPredictionMarket(id);
        const c = state.pm.byId[id];
        if (c && d.trade_seq === c.trade_seq && d.status === c.status) continue;
        emitPm({ type: "tick", id, seq: d.trade_seq, status: d.status, prices_ppm: d.outcomes.map((o) => o.price_ppm), volume_shares: d.volume_shares, public_tt: null });
      }
    } catch (_) {
      /* 网络抖动：下一轮再试 */
    }
  }

  const real = {
    async listPredictionMarkets({ challenge_id, status, cursor, limit } = {}) {
      let out;
      try {
        out = await guarded(() => api.get("/prediction-markets", { query: qs({ challenge_id, status, cursor, limit }) }));
      } catch (err) {
        // 还没有挑战（或挑战关闭）：没有市场，页面给“今日挑战开始后开市”，不当作错误
        if (err && err.code === "CHALLENGE_NOT_FOUND") return { items: [], next_cursor: null, public: null };
        throw err;
      }
      if (out.public && out.public.challenge_id && out.public.challenge_id !== state.pm.challengeId) {
        state.pm.challengeId = out.public.challenge_id;
        if (ws && ws.readyState === 1) send({ t: "watch", challenge_id: state.pm.challengeId });
      }
      return out;
    },
    async loadPredictionMarket(id) {
      const d = await guarded(() => api.get(`/prediction-markets/${encodeURIComponent(id)}`));
      state.pm.byId[id] = d;
      state.pm.balance = d.balance_points;
      return d;
    },
    quotePredictionMarket: (id, q = {}) =>
      guarded(() => api.get(`/prediction-markets/${encodeURIComponent(id)}/quote`, { query: qs({ side: q.side, outcome: q.outcome, shares: q.shares, budget_points: q.budget_points }) })),
    async tradePredictionMarket(id, body) {
      const r = await guarded(() => api.post(`/prediction-markets/${encodeURIComponent(id)}/trades`, { body, headers: { "Idempotency-Key": uuid() } }));
      state.pm.balance = r.balance_points;
      return r;
    },
    loadPredictionHistory: (id) => guarded(() => api.get(`/prediction-markets/${encodeURIComponent(id)}/history`, { query: { max_points: 200 } })),
    listMyPredictionPositions: (q = {}) => guarded(() => api.get("/me/prediction-positions", { query: qs({ status: q.status, cursor: q.cursor }) })),
    listMyPredictionSettlements: (cursor) => guarded(() => api.get("/me/prediction-settlements", { query: qs({ cursor }) })),
    watchPredictions(challengeId) {
      state.pm.refs += 1;
      if (challengeId) state.pm.challengeId = challengeId;
      connect();
    },
    unwatchPredictions() {
      state.pm.refs = Math.max(0, state.pm.refs - 1);
      if (!state.pm.refs) {
        closeSocket();
        state.pm.subs = [];
      }
    },
    subscribePrediction(id) {
      if (!state.pm.subs.includes(id) && state.pm.subs.length < 20) state.pm.subs.push(id);
      send({ t: "subscribe", market_id: id });
    },
    unsubscribePrediction(id) {
      state.pm.subs = state.pm.subs.filter((x) => x !== id);
      send({ t: "unsubscribe", market_id: id });
    },
  };

  Object.assign(SS.store, { onPredictions }, SS.isMock ? mock : real);
  SS.assertSameKeys("pm", mock, real);
})();
