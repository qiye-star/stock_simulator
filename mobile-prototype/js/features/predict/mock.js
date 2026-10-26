/**
 * 预测卡 / 积分 / 情报卡 / 称号的假数据（确定性），字段与 backend 02 §10 的 schema 一致；私有字段以 _ 开头。
 *   SS.mockFeatures.predict = { cards（含 _truth 真值，不对外）, points, titles, settings, intel, stats, ledger, rumorTruth, sim }
 *   sim：模拟后端的最小行为（触发出卡 / 作答 / 不答 / 结算），由 store.js 的 mock 实现调用，结果经 emitLocal("ws:prediction"|"ws:title") 广播。
 * 依赖 SS.mockFeatures.news（快讯 mock）：事件 ID 与产业链节点取自那里。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.mockFeatures = SS.mockFeatures || {};
  const M = () => SS.predictModel;
  const PM = () => SS.predictMath;
  const NEWS = () => SS.mockFeatures.news;
  const EDGES16 = [-240, -80, 80, 240]; // 行业 n=16（v2）的五档边界
  const SETTLE_MS = 30000; // mock 的结算延迟（真实为窗口收盘后）
  const CAND_CHG = { 新能源: -552, 新能源汽车: -288, 化工: 310, 光伏: -90, 汽车: -45, 电力: -120, 稀土: 200, 电子: 80, 家电: -30, 银行: 20, 券商: -10 };
  const off = (m) => (m <= 690 ? m - 570 : m - 659);
  const tt = (day, m) => day * 242 + off(m);
  const ts = (iso) => iso;

  const nodeIds = () => NEWS().chain.nodes.map((n) => n.id);
  const candidatesFor = (exclude) => nodeIds().filter((x) => x !== exclude);

  function dirQ(target, edges, from, to) {
    return { qid: "dir", kind: "bucket", target_kind: "industry", target, target_name: target, edges_bp: edges, from_day: from, to_day: to };
  }
  function rankQ(exclude, at) {
    const candidates = candidatesFor(exclude);
    return { qid: "rank", kind: "rank", k: 3, exclude, candidates, at_day: at };
  }
  const rumorQ = () => ({ qid: "rumor", kind: "binary" });

  function relevanceOf(top) {
    const rel = {};
    candidatesFor("有色").forEach((x) => (rel[x] = 0));
    top.forEach((x, i) => (rel[x] = 3 - i));
    return rel;
  }
  const chgOf = (names) => Object.fromEntries(names.map((x) => [x, CAND_CHG[x] == null ? 0 : CAND_CHG[x]]));

  const eventOf = (id) => {
    const e = NEWS().events.find((x) => x.event.event_id === id);
    return e ? { ...e.event } : null;
  };

  // ---------- 卡片（含真值） ----------
  const topA = ["新能源", "新能源汽车", "化工"];
  const cards = [
    {
      // 待答：有色 3 日涨跌 + 传导排序（当前可作答）
      id: "c-open",
      event_id: "e47-0",
      status: "open",
      opened_trading_tick: tt(47, 582),
      opened_trading_day: 47,
      deadline_trading_tick: tt(47, 582),
      window_days: 3,
      questions: [dirQ("有色", EDGES16, 47, 49), rankQ("有色", 49)],
      answers: [],
      results: [],
      points: null,
      points_capped: false,
      answered_at: null,
      settled_at: null,
      created_at: "2026-10-26T01:10:00Z",
      _truth: { change_bp: -360, true_top: ["新能源", "新能源汽车", "电力"], relevance: relevanceOf(["新能源", "新能源汽车", "电力"]), candidate_change_bp: chgOf(["新能源", "新能源汽车", "电力"]) },
    },
    {
      // 已揭晓：有色（传闻被辟谣）；三题都已作答
      id: "c-settled",
      event_id: "e48-2",
      status: "settled",
      opened_trading_tick: tt(48, 590),
      opened_trading_day: 48,
      deadline_trading_tick: tt(48, 590),
      window_days: 3,
      questions: [dirQ("有色", EDGES16, 46, 48), rankQ("有色", 48), rumorQ()],
      answers: [
        { qid: "dir", probs: [7, 7, 8, 70, 8], order: null, pick: 3, claimed_pct: 70 },
        { qid: "rank", probs: null, order: topA, pick: null, claimed_pct: null },
        { qid: "rumor", probs: [70, 30], order: null, pick: 0, claimed_pct: 70 },
      ],
      results: [],
      points: null,
      points_capped: false,
      answered_at: "2026-10-26T01:20:00Z",
      settled_at: "2026-10-26T01:40:00Z",
      created_at: "2026-10-26T01:15:00Z",
      _truth: { change_bp: 886, true_top: topA, relevance: relevanceOf(topA), candidate_change_bp: chgOf(topA), truth: false },
    },
    {
      // 未作答：传闻题，已过期（只展示真值）
      id: "c-expired",
      event_id: "e48-8",
      status: "expired",
      opened_trading_tick: tt(48, 658),
      opened_trading_day: 48,
      deadline_trading_tick: tt(48, 658),
      window_days: 3,
      questions: [rumorQ()],
      answers: [],
      results: [],
      points: 0,
      points_capped: false,
      answered_at: null,
      settled_at: "2026-10-26T01:45:00Z",
      created_at: "2026-10-26T01:30:00Z",
      _truth: { truth: true },
    },
  ];

  const data = {
    cards,
    points: { balance: 1286, lifetime_earned: 2310, lifetime_spent: 1024, equipped_title: "chain_reader", today_prediction_points: 197, daily_cap: 2000 },
    titles: { unlocked: { forecaster_1: ts("2026-09-01T00:00:00Z"), chain_reader: ts("2026-10-10T00:00:00Z"), rumor_buster: ts("2026-10-20T00:00:00Z") }, equipped: "chain_reader" },
    settings: { mode: "pause", forced: false },
    intel: {
      edges: [{ edge_id: "有色>新能源", from_industry: "有色", to_industry: "新能源", relation: "supply", sign: -1, strength: 2, lag_days: null, level: 1 }],
      rumor_hints: [],
      prices: { edge_l1: 100, edge_l2: 200, rumor_hint: 80 },
      daily_limit: 8,
      used_today: 1,
    },
    // 传闻真假（mock 真值，仅用于 hint 与结算）
    rumorTruth: { "e48-8": true, "e48-2": false },
    stats: {
      cards_answered: 23,
      cards_settled: 19,
      cards_expired: 4,
      total_points: 2310,
      by_kind: { dir: { answered: 23, scored: 19, avg_score: 81, avg_baseline: 22 }, rank: { answered: 9, scored: 8, avg_score: 74, avg_baseline: 18 }, rumor: { answered: 6, scored: 5, avg_score: 70, avg_baseline: 12 } },
      calibration: [
        { lo_pct: 40, hi_pct: 50, n: 3, hits: 1, avg_claimed_pct: 45, hit_rate_pct: 33 },
        { lo_pct: 50, hi_pct: 60, n: 4, hits: 2, avg_claimed_pct: 55, hit_rate_pct: 50 },
        { lo_pct: 60, hi_pct: 70, n: 5, hits: 3, avg_claimed_pct: 65, hit_rate_pct: 60 },
        { lo_pct: 70, hi_pct: 80, n: 6, hits: 5, avg_claimed_pct: 74, hit_rate_pct: 83 },
        { lo_pct: 80, hi_pct: 90, n: 4, hits: 3, avg_claimed_pct: 84, hit_rate_pct: 75 },
        { lo_pct: 90, hi_pct: 100, n: 1, hits: 1, avg_claimed_pct: 95, hit_rate_pct: 100 },
      ].concat([0, 10, 20, 30].map((lo) => ({ lo_pct: lo, hi_pct: lo + 10, n: 0, hits: 0, avg_claimed_pct: null, hit_rate_pct: null }))),
      calibration_error_bp: 630,
      recent: [],
    },
    ledger: [
      { seq: 10, delta: 197, balance_after: 1286, reason: "prediction", ref: "card:c-settled", save_id: null, meta: null, created_at: "2026-10-26T01:40:00Z" },
      { seq: 9, delta: -80, balance_after: 1089, reason: "intel_card", ref: "intel:rumor", save_id: null, meta: null, created_at: "2026-10-26T01:35:00Z" },
      { seq: 8, delta: -100, balance_after: 1169, reason: "intel_card", ref: "edge:有色>新能源", save_id: null, meta: null, created_at: "2026-10-25T09:00:00Z" },
    ],
  };
  SS.mockFeatures.predict = data;

  // ---------- 模拟后端 ----------
  /** 对外形态：去掉私有字段，深拷贝 */
  const pub = (c) => {
    const { _truth, ...rest } = c;
    return JSON.parse(JSON.stringify(rest));
  };
  const bucketOf = (v, edges) => edges.filter((e) => e <= v).length;
  const argmax = (p) => PM().argmaxPick(p);

  /** 按真值生成结果（只在结算时调用） */
  function computeResults(card) {
    const t = card._truth;
    const out = [];
    const d = M().qOf(card, "dir");
    const r = M().qOf(card, "rank");
    const u = M().qOf(card, "rumor");
    const ansOf = (qid) => M().aOf(card, qid);
    if (d) {
      const outcome = bucketOf(t.change_bp, d.edges_bp);
      const a = ansOf("dir");
      const score = a ? M().rpsScore(a.probs, outcome) : null;
      const uni = M().uniformRpsScore(5, outcome);
      out.push({ qid: "dir", resolved: true, outcome_bucket: outcome, change_bp: t.change_bp, truth: null, true_top: null, relevance: null, candidate_change_bp: null, score, uniform_score: uni, baseline: score == null ? null : M().baselineScore(score, uni), points: score, hit: a ? argmax(a.probs) === outcome : null });
    }
    if (r) {
      const a = ansOf("rank");
      const score = a ? M().ndcgScore(a.order, t.relevance, 3) : null;
      const n = r.candidates.length;
      const sumGain = Object.values(t.relevance).reduce((s, x) => s + (Math.pow(2, x) - 1), 0);
      const disc = [1, 2, 3].reduce((s, i) => s + Math.round((1e6 * Math.LN2) / Math.log(i + 1)), 0);
      const idcg = [3, 2, 1].reduce((s, g, i) => s + (Math.pow(2, g) - 1) * Math.round((1e6 * Math.LN2) / Math.log(i + 2)), 0);
      const uni = M().rdiv(100 * sumGain * disc, n * idcg);
      out.push({ qid: "rank", resolved: true, outcome_bucket: null, change_bp: null, truth: null, true_top: t.true_top, relevance: t.relevance, candidate_change_bp: t.candidate_change_bp, score, uniform_score: uni, baseline: score == null ? null : M().baselineScore(score, uni), points: score, hit: null });
    }
    if (u) {
      const outcome = t.truth ? 1 : 0;
      const a = ansOf("rumor");
      const score = a ? M().rpsScore(a.probs, outcome) : null;
      const uni = M().uniformRpsScore(2, outcome);
      out.push({ qid: "rumor", resolved: true, outcome_bucket: null, change_bp: null, truth: !!t.truth, true_top: null, relevance: null, candidate_change_bp: null, score, uniform_score: uni, baseline: score == null ? null : M().baselineScore(score, uni), points: score, hit: a ? argmax(a.probs) === outcome : null });
    }
    return out;
  }

  const emit = (evt, payload) => SS.store.emitLocal(evt, payload);
  const predMsg = (op, card, extra) => ({ t: "prediction", op, card_id: card.id, event_id: card.event_id, status: card.status, points: null, balance: null, ...extra });

  /** 结算：answered 发积分，expired 只写结果；完成后广播 settled（或 expired 已在不答时广播） */
  function settle(card) {
    card.results = computeResults(card);
    card.settled_at = new Date().toISOString();
    if (card.status === "answered") {
      const pts = card.results.reduce((s, r) => s + (r.points || 0), 0);
      card.points = pts;
      card.status = "settled";
      data.points.balance += pts;
      data.points.today_prediction_points += pts;
      data.stats.cards_settled += 1;
      emit("ws:prediction", predMsg("settled", card, { points: pts, balance: data.points.balance }));
    }
  }

  function unlock(id) {
    if (data.titles.unlocked[id]) return;
    data.titles.unlocked[id] = new Date().toISOString();
    emit("ws:title", { t: "title", ids: [id] });
  }

  const sim = {
    /** 触发一张卡（模拟 on_publish）：只对有题目规格的事件出卡；返回新卡或 null */
    open(eventId) {
      if (cards.some((c) => c.event_id === eventId)) return null;
      const ev = eventOf(eventId);
      if (!ev) return null;
      let specs = null;
      if (eventId === "e48-6") specs = [dirQ("有色", EDGES16, 48, 50), rankQ("有色", 50)];
      if (!specs) return null;
      const card = {
        id: `c-${eventId}`,
        event_id: eventId,
        status: "open",
        opened_trading_tick: tt(48, 636),
        opened_trading_day: 48,
        deadline_trading_tick: tt(48, 636),
        window_days: 3,
        questions: specs,
        answers: [],
        results: [],
        points: null,
        points_capped: false,
        answered_at: null,
        settled_at: null,
        created_at: new Date().toISOString(),
        _truth: { change_bp: -360, true_top: ["新能源", "电力", "化工"], relevance: relevanceOf(["新能源", "电力", "化工"]), candidate_change_bp: chgOf(["新能源", "电力", "化工"]) },
      };
      cards.push(card);
      SS.store.setPaused(true); // 出卡即截停行情（与后端 on_publish 一致）
      emit("ws:prediction", predMsg("opened", card));
      return card;
    },
    /** 作答（覆盖式）；resume 时若无其它待答卡则恢复行情。返回 {card, clock} 对外形态 */
    answer(card, answers, resume) {
      validate(card, answers);
      const isFirst = !card.answers.length;
      card.answers = Object.entries(answers).map(([qid, v]) => ({
        qid,
        probs: v.probs || null,
        order: v.order || null,
        pick: v.probs ? PM().argmaxPick(v.probs) : null,
        claimed_pct: v.probs ? Math.max(...v.probs) : null,
      }));
      card.status = "answered";
      card.answered_at = new Date().toISOString();
      const after = cards.filter((c) => c.status === "open").length;
      if (resume && after === 0) SS.store.setPaused(false);
      if (isFirst) unlock("forecaster_1");
      setTimeout(() => settle(card), SETTLE_MS);
      return { card: pub(card), clock: SS.store.state.clock };
    },
    /** 不答：expired，行情按 resume 继续 */
    skip(card, resume) {
      card.status = "expired";
      if (resume && cards.filter((c) => c.status === "open").length === 0) SS.store.setPaused(false);
      emit("ws:prediction", predMsg("expired", card));
      setTimeout(() => settle(card), SETTLE_MS);
      return { card: pub(card), clock: SS.store.state.clock };
    },
    /** 出卡时的“待答”数（供 overlay） */
    pending: () => cards.filter((c) => c.status === "open").length,
  };

  /** 校验答案：与 domain/predictions::validate_answers 的核心规则一致（缺题、多题、长度、合计、rank 顺序） */
  function validate(card, answers) {
    const bad = (field, reason) => {
      throw new (SS.ApiError)("VALIDATION_ERROR", 422, { field, reason });
    };
    for (const q of card.questions) {
      const a = answers[q.qid];
      if (!a) bad(`answers.${q.qid}`, "missing");
      if (q.qid === "rank") {
        if (!Array.isArray(a.order) || a.order.length !== 3 || new Set(a.order).size !== 3) bad("answers.rank.order", "invalid");
        if (a.order.some((x) => !q.candidates.includes(x) || x === q.exclude)) bad("answers.rank.order", "invalid");
      } else {
        const k = q.qid === "dir" ? 5 : 2;
        if (!Array.isArray(a.probs) || a.probs.length !== k || a.probs.reduce((s, x) => s + x, 0) !== 100) bad(`answers.${q.qid}.probs`, "invalid");
      }
    }
    for (const key of Object.keys(answers)) if (!card.questions.some((q) => q.qid === key)) bad(`answers.${key}`, "unexpected");
  }

  // 初始的已结算 / 已过期卡：按真值补全结果与积分
  for (const c of cards) {
    if (c.status === "settled" || c.status === "expired") {
      c.results = computeResults(c);
      if (c.status === "settled") c.points = c.results.reduce((s, r) => s + (r.points || 0), 0);
    }
  }

  SS.mockFeatures.predict.sim = sim;
  SS.mockFeatures.predict.pub = pub;
})();
