/**
 * 每日挑战的数据层（C，03 §10、08 §5.7）：mock 与 real 两套同名方法，按 SS.isMock 挂到 SS.store 上。
 *
 *   loadTodayChallenge()                        GET  /challenges/today                 → ChallengeOut（更新 state.challenge.today 与 skew）
 *   listChallenges({cursor,limit})              GET  /challenges                       → {items, next_cursor}
 *   loadChallenge(id)                           GET  /challenges/{id}                  → ChallengeOut
 *   enterChallenge(id)                          POST /challenges/{id}/entry            → ChallengeEntryOut；真实版成功后记下参加前的存档并切到挑战存档
 *   leaveChallenge()                            切回参加前的普通存档（ss.returnSaveId 失效则第一个普通存档）
 *   loadChallengeRounds(id)                     GET  /challenges/{id}/rounds           → {items: ChallengeRoundCardOut[]}（缓存到 state.challenge.cards[id]）
 *   answerChallengeRound(id, k, answers)        PUT  /challenges/{id}/rounds/{k}/answer  body {answers} → ChallengeRoundCardOut
 *   loadChallengeLeaderboard(id, {board,cursor})GET  /challenges/{id}/leaderboard        → LeaderboardOut（scope=day）
 *   loadChallengeBoards({scope,week,sort,cursor}) GET /challenge-leaderboard            → LeaderboardOut（week|all）
 *   loadChallengeReveal(id)                     GET  /challenges/{id}/reveal           → RevealOut（结算后）
 *   loadChallengeReview(id)                     GET  /challenges/{id}/review           → ReviewOut（结算后）
 * 共用（不计入 mock/real 对照）：resetChallenge()，切存档时清缓存。
 * real 经 guarded()：后端没有该接口（HTTP_404/405/501）时抛 FEATURE_UNAVAILABLE 并记入 SS.api.missing，本会话不再请求；
 * 业务错误（CHALLENGE_NOT_FOUND、CHALLENGE_NOT_SETTLED …）原样抛出，由页面处理。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { ApiError } = SS;
  const state = SS.store.state;
  const RET_KEY = "ss.returnSaveId";
  const blank = () => ({ today: null, skew: 0, cards: {}, live: null, loaded: false, error: null });
  state.challenge = state.challenge || blank();

  const resetChallenge = () => Object.assign(state.challenge, blank());
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
    del(k) {
      try {
        localStorage.removeItem(k);
      } catch (_) {}
    },
  };

  /** 记下今日挑战视图并校准偏移（server_time − 本机时间） */
  function setToday(ch) {
    state.challenge.today = ch;
    state.challenge.skew = SS.challengeModel.skewOf(ch.server_time, Date.now());
    return ch;
  }
  /** 回合卡缓存：按回合序替换 */
  function setCards(id, items) {
    state.challenge.cards[id] = items.slice();
    return items;
  }
  function upsertCard(id, card) {
    const list = (state.challenge.cards[id] || []).filter((c) => c.round_index !== card.round_index);
    list.push(card);
    list.sort((a, b) => a.round_index - b.round_index);
    state.challenge.cards[id] = list;
    return card;
  }

  // ---------- mock ----------
  const M = () => SS.mockFeatures.challenge;
  const knownId = (id) => id === M().TODAY_ID || id === M().DAY_ID;
  const mockNotFound = (id) => new ApiError("CHALLENGE_NOT_FOUND", 404, { challenge_id: id });

  const mock = {
    async loadTodayChallenge() {
      return setToday(M().view(M().TODAY_ID));
    },
    async listChallenges() {
      return { items: M().list(), next_cursor: null };
    },
    async loadChallenge(id) {
      if (!knownId(id)) throw mockNotFound(id);
      const v = M().view(id);
      if (id === M().TODAY_ID) setToday(v);
      return v;
    },
    async enterChallenge(id) {
      if (!knownId(id)) throw mockNotFound(id);
      const entry = M().enter(id);
      state.challenge.today = M().view(M().TODAY_ID);
      return entry;
    },
    async leaveChallenge() {
      return null;
    },
    async loadChallengeRounds(id) {
      if (!knownId(id)) throw mockNotFound(id);
      return { items: setCards(id, M().rounds(id)) };
    },
    async answerChallengeRound(id, k, answers) {
      if (!knownId(id)) throw mockNotFound(id);
      return upsertCard(id, M().answer(id, k, answers));
    },
    async loadChallengeLeaderboard(id, { board = "total" } = {}) {
      if (!knownId(id)) throw mockNotFound(id);
      return M().board(id, board);
    },
    async loadChallengeBoards({ scope = "week" } = {}) {
      return M().week(scope);
    },
    async loadChallengeReveal(id) {
      if (!knownId(id)) throw mockNotFound(id);
      return M().reveal(id);
    },
    async loadChallengeReview(id) {
      if (!knownId(id)) throw mockNotFound(id);
      return M().review(id);
    },
  };

  // ---------- real ----------
  const api = SS.api;
  /** 缺失接口 → FEATURE_UNAVAILABLE；会话内记住，不再请求 */
  async function guarded(fn) {
    if (api.missing.has("challenge")) throw new ApiError("FEATURE_UNAVAILABLE", 404);
    try {
      return await fn();
    } catch (err) {
      if (api.isMissing(err)) {
        api.missing.add("challenge");
        throw new ApiError("FEATURE_UNAVAILABLE", 404);
      }
      throw err;
    }
  }
  const qs = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v != null && v !== ""));

  /** 挑战存档的普通存档回退：优先 ss.returnSaveId，再第一个普通存档 */
  async function leaveReal() {
    const back = ls.get(RET_KEY);
    ls.del(RET_KEY);
    if (back) {
      try {
        return await SS.store.switchSave(back);
      } catch (_) {
        /* 已删除：走下面的回退 */
      }
    }
    const saves = await SS.store.listSaves();
    if (!saves.length) throw new ApiError("SAVE_NOT_FOUND", 404);
    return SS.store.switchSave(saves[0].id);
  }

  const real = {
    async loadTodayChallenge() {
      try {
        return setToday(await guarded(() => api.get("/challenges/today")));
      } catch (err) {
        if (err && err.code === "CHALLENGE_NOT_FOUND") state.challenge.today = null;
        throw err;
      }
    },
    listChallenges: ({ cursor, limit = 20 } = {}) => guarded(() => api.get("/challenges", { query: qs({ cursor, limit }) })),
    loadChallenge: (id) =>
      guarded(() => api.get(`/challenges/${encodeURIComponent(id)}`)).then((ch) => {
        if (ch.id === state.challenge.today?.id) setToday(ch);
        return ch;
      }),
    async enterChallenge(id) {
      const entry = await guarded(() => api.post(`/challenges/${encodeURIComponent(id)}/entry`));
      if (!entry.save_id) return entry; // 不符合参加条件：只返回记录，不切存档
      if (state.save.mode !== "challenge") ls.set(RET_KEY, state.save.id);
      await SS.store.switchSave(entry.save_id);
      return entry;
    },
    leaveChallenge: () => leaveReal(),
    async loadChallengeRounds(id) {
      const out = await guarded(() => api.get(`/challenges/${encodeURIComponent(id)}/rounds`));
      setCards(id, out.items);
      return out;
    },
    answerChallengeRound: (id, k, answers) =>
      guarded(() => api.put(`/challenges/${encodeURIComponent(id)}/rounds/${k}/answer`, { body: { answers } })).then((card) => upsertCard(id, card)),
    loadChallengeLeaderboard: (id, { board = "total", cursor, limit = 50 } = {}) =>
      guarded(() => api.get(`/challenges/${encodeURIComponent(id)}/leaderboard`, { query: qs({ board, cursor, limit }) })),
    loadChallengeBoards: ({ scope = "week", week, sort = "sum", cursor, limit = 50 } = {}) =>
      guarded(() => api.get("/challenge-leaderboard", { query: qs({ scope, week, sort, cursor, limit }) })),
    loadChallengeReveal: (id) => guarded(() => api.get(`/challenges/${encodeURIComponent(id)}/reveal`)),
    loadChallengeReview: (id) => guarded(() => api.get(`/challenges/${encodeURIComponent(id)}/review`)),
  };

  // 切存档 / 退出挑战时清空缓存（共用，不计入对照）
  Object.assign(SS.store, { resetChallenge }, SS.isMock ? mock : real);
  SS.assertSameKeys("challenge", mock, real);
})();
