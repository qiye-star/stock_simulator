/**
 * 每日挑战的假数据（确定性，字段与 docs/10.26-plan/03-每日挑战.md §10.2 一致；私有字段以 _ 开头）。
 *   SS.mockFeatures.challenge = { list, view, rounds, enter, answer, board, week, reveal, review, state }
 *   两场：今日（running，第 2 轮 open，未参加）与昨日（settled，可复盘）。承诺哈希是对承诺原文真实计算的 sha256，
 *   因此 SS.challengeVerify 在 mock 下也能给出 ✓。
 *   sim 的状态（参加、作答）只存在内存里，刷新即重置。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.mockFeatures = SS.mockFeatures || {};
  const MIN = 60e3;
  const H = 3600e3;
  const BASE = Date.now(); // 模拟“现在”：页面加载时确定
  const iso = (ms) => new Date(ms).toISOString();
  const TODAY_ID = "0b7e6c1a-2d3f-4a5b-8c9d-0e1f2a3b4c5d";
  const DAY_ID = "0b7e6c1a-2d3f-4a5b-8c9d-0e1f2a3b4c4c";
  const EDGES = [-240, -80, 80, 240]; // 行业 n=16 的五档边界（与 predict/mock 一致）
  const CANDS = ["新能源", "新能源汽车", "化工", "光伏", "汽车零部件", "电力", "银行"];
  const SEED_TODAY = { date: "2026-10-26", seed: "7715203948817260331", salt: "a0b1c2d3e4f5061728394a5b6c7d8e9f" };
  const SEED_DAY = { date: "2026-10-25", seed: "3482910573829104657", salt: "5c1e8a7f2b9d4036e1f0a2c3d4b5e6f7" };
  // 承诺 = sha256(commitment_input)，已用 sha256sum 预先算好（见 CLAUDE.md）
  const DIGEST = {
    [DAY_ID]: "605f7532bd1e66fefb3373251c246222620d7f8f3101044c6e20b30584c1d2cb",
    [TODAY_ID]: "7f8a86c531ec1fb3d15ee08ed661645c0a21bcc98081a7bf94d7e0ce6b01b610",
  };
  const commitmentInput = (s) => `stocksim-challenge|v1|${s.date}|ruleset=2|clock=2|seed=${s.seed}|salt=${s.salt}`;

  const EVENTS = {
    r2: { event_id: "e46-3", title: "华中某锂矿区因环保督察全面停产整改，涉及国内锂盐供给约 8%", kind: "sudden", major: true, phase: "active" },
    d1: { event_id: "e42-2", title: "两部门发布新能源汽车下乡补贴细则", kind: "policy", major: true, phase: "closed" },
    d2: { event_id: "e43-5", title: "头部电池厂商宣布扩产，锂盐需求预期上修", kind: "news", major: true, phase: "closed" },
    d3: { event_id: "e44-7", title: "某化工龙头安全事故，停产检修两周", kind: "sudden", major: true, phase: "closed" },
    d4: { event_id: "e45-4", title: "“一周内复产”传闻在社交平台流传", kind: "rumor", major: true, phase: "closed" },
  };

  const dirQ = (from, to) => ({ qid: "dir", kind: "bucket", target_kind: "industry", target: "有色", target_name: "有色", edges_bp: EDGES, from_day: from, to_day: to });
  const rankQ = (at) => ({ qid: "rank", kind: "rank", k: 3, exclude: "有色", candidates: CANDS.slice(), at_day: at });

  // ---------- 我的作答（内存） ----------
  const mine = {
    // 昨日：已参加并作答四轮（用于复盘页）
    [DAY_ID]: {
      1: { answers: [{ qid: "dir", probs: [7, 8, 10, 65, 10], order: null, pick: 3, claimed_pct: 65 }, { qid: "rank", probs: null, order: ["新能源", "电力", "化工"], pick: null, claimed_pct: null }], revision: 2 },
      2: { answers: [{ qid: "dir", probs: [5, 10, 15, 60, 10], order: null, pick: 3, claimed_pct: 60 }, { qid: "rank", probs: null, order: ["光伏", "新能源", "银行"], pick: null, claimed_pct: null }], revision: 1 },
      3: { answers: [{ qid: "dir", probs: [10, 10, 60, 10, 10], order: null, pick: 2, claimed_pct: 60 }, { qid: "rank", probs: null, order: ["化工", "电力", "汽车零部件"], pick: null, claimed_pct: null }], revision: 1 },
      4: { answers: [{ qid: "dir", probs: [60, 20, 10, 5, 5], order: null, pick: 0, claimed_pct: 60 }, { qid: "rank", probs: null, order: ["新能源汽车", "新能源", "银行"], pick: null, claimed_pct: null }], revision: 3 },
    },
    // 今日：未参加（参加后 sim.enter 才会建立 my_entry；作答写入这里）
    [TODAY_ID]: {},
  };
  const today = {
    id: TODAY_ID,
    challenge_date: "2026-10-26",
    status: "running",
    phase: "hold",
    round_index: 2,
    rounds_total: 4,
    schedule_mode: "daily",
    starts_at: iso(BASE - 3 * H),
    entry_closes_at: iso(BASE + 4 * H),
    settle_expected_at: iso(BASE + 9 * H),
    next_change_at: iso(BASE + 2 * H + 14 * MIN + 5000),
    tick_ms: 750,
    clock_rules: "v2",
    events_ruleset: 2,
    seed_commitment: DIGEST[TODAY_ID],
    commitment_scheme: "sha256/stocksim-challenge|v1",
    participant_count: 1284,
    public_trading_tick: 388,
    my_entry: null,
  };
  const yesterday = {
    id: DAY_ID,
    challenge_date: "2026-10-25",
    status: "settled",
    phase: "ended",
    round_index: null,
    rounds_total: 4,
    schedule_mode: "daily",
    starts_at: iso(BASE - 27 * H),
    entry_closes_at: iso(BASE - 23 * H),
    settle_expected_at: iso(BASE - 15 * H),
    next_change_at: null,
    tick_ms: 750,
    clock_rules: "v2",
    events_ruleset: 2,
    seed_commitment: DIGEST[DAY_ID],
    commitment_scheme: "sha256/stocksim-challenge|v1",
    participant_count: 1190,
    public_trading_tick: 1694,
    my_entry: {
      entry_id: "5a0e1d2c-0000-4000-8000-000000000002",
      challenge_id: DAY_ID,
      save_id: null,
      eligible: true,
      joined_at: iso(BASE - 26 * H),
      answered_rounds: 4,
      result: { final_equity_cents: 10312000, return_bp: 312, forecast_score: 41, trade_score: 16, total_score: 57, rank: 37, eligible_count: 402, points_awarded: 60 },
    },
  };

  // 回合时间（ChallengeRoundOut）：今日 r1 已判定、r2 可作答、r3/r4 未开始
  const todayRoundRows = () => [
    { round_index: 1, state: "resolved", resume_at: iso(BASE - 3 * H), closes_at: iso(BASE - 2 * H - 35 * MIN), hold_at: iso(BASE - 2 * H - 50 * MIN), event_id: EVENTS.d1.event_id },
    { round_index: 2, state: "open", resume_at: iso(BASE - 40 * MIN), closes_at: iso(BASE + 2 * H + 14 * MIN), hold_at: iso(BASE - 35 * MIN), event_id: EVENTS.r2.event_id },
    { round_index: 3, state: "pending", resume_at: iso(BASE + 2 * H + 14 * MIN + 5000), closes_at: iso(BASE + 4 * H + 30 * MIN), hold_at: null, event_id: null },
    { round_index: 4, state: "pending", resume_at: iso(BASE + 6 * H), closes_at: iso(BASE + 7 * H), hold_at: null, event_id: null },
  ];
  const DAY_EVENTS = [EVENTS.d1, EVENTS.d2, EVENTS.d3, EVENTS.d4];
  const dayRoundRows = () => [1, 2, 3, 4].map((k) => ({ round_index: k, state: "resolved", resume_at: iso(BASE - 27 * H + k * H), closes_at: iso(BASE - 26 * H + k * H), hold_at: iso(BASE - 27 * H + k * H - 10 * MIN), event_id: DAY_EVENTS[k - 1].event_id }));

  /** 结果（QuestionResultOut）：昨日四轮 */
  const DAY_RESULTS = {
    1: { dir: { change_bp: 412, outcome_bucket: 3, score: 81, baseline: 27, uniform_score: 70 }, rank: { true_top: ["新能源", "电力", "化工"], score: 92, baseline: 46 } },
    2: { dir: { change_bp: -310, outcome_bucket: 1, score: 47, baseline: -18, uniform_score: 70 }, rank: { true_top: ["新能源汽车", "光伏", "汽车零部件"], score: 64, baseline: 12 } },
    3: { dir: { change_bp: 96, outcome_bucket: 2, score: 84, baseline: 30, uniform_score: 70 }, rank: { true_top: ["化工", "银行", "电力"], score: 71, baseline: 22 } },
    4: { dir: { change_bp: 655, outcome_bucket: 4, score: 38, baseline: -35, uniform_score: 70 }, rank: { true_top: ["光伏", "新能源", "电力"], score: 58, baseline: 4 } },
  };
  const CAND_CHG = { 新能源: 380, 新能源汽车: 120, 化工: -40, 光伏: 260, 汽车零部件: 30, 电力: -60, 银行: 10 };

  /** 回合卡（ChallengeRoundCardOut） */
  function roundCard(cid, k, row) {
    const ev = Object.values(EVENTS).find((e) => e.event_id === row.event_id) || null;
    const isDay = cid === DAY_ID;
    const dirFrom = isDay ? 40 + k : 47;
    const questions = [dirQ(dirFrom, dirFrom + 2), rankQ(dirFrom + 2)];
    const m = mine[cid][k] || null;
    const card = {
      round_index: k,
      state: row.state,
      event: ev ? { ...ev } : null,
      closes_at: row.closes_at,
      questions: row.state === "pending" ? [] : questions,
      my_answers: m ? m.answers.map((a) => ({ ...a })) : [],
      my_revision: m ? m.revision : 0,
      results: [],
      peer: null,
      used: null,
      my_round_score: null,
      crowd: null,
    };
    if (row.state === "open" || row.state === "closed" || row.state === "resolved") {
      card.crowd = row.state === "open" ? null : { n: 1190, by_qid: { dir: { mean_probs: [9, 14, 31, 33, 13] }, rank: { top3_counts: { 新能源: 402, 电力: 310, 化工: 288 } } } };
    }
    if (row.state === "resolved") {
      const r = DAY_RESULTS[k];
      card.results = [
        { qid: "dir", resolved: true, outcome_bucket: r.dir.outcome_bucket, change_bp: r.dir.change_bp, score: r.dir.score, uniform_score: r.dir.uniform_score, baseline: r.dir.baseline, points: null, hit: null, truth: null, true_top: null, relevance: null, candidate_change_bp: null },
        {
          qid: "rank",
          resolved: true,
          true_top: r.rank.true_top,
          relevance: null,
          candidate_change_bp: Object.fromEntries(r.rank.true_top.map((x) => [x, CAND_CHG[x] == null ? 0 : CAND_CHG[x]])),
          score: r.rank.score,
          uniform_score: 60,
          baseline: r.rank.baseline,
          points: null,
          hit: null,
          outcome_bucket: null,
          change_bp: null,
          truth: null,
        },
      ];
      card.peer = 61;
      card.used = "peer";
      card.my_round_score = m ? Math.round((r.dir.score + r.rank.score) / 2) : null;
    }
    return card;
  }

  const rowsOf = (cid) => (cid === DAY_ID ? dayRoundRows() : todayRoundRows());
  const entryOf = (cid) => (cid === DAY_ID ? yesterday.my_entry : today.my_entry);
  const answeredCount = (cid) => Object.keys(mine[cid] || {}).length;

  /** ChallengeOut（每次取都带当前 server_time，倒计时以它为准） */
  function view(cid) {
    const base = cid === DAY_ID ? yesterday : today;
    const entry = entryOf(cid);
    return {
      ...base,
      server_time: iso(Date.now()),
      rounds: rowsOf(cid),
      my_entry: entry ? { ...entry, answered_rounds: answeredCount(cid) } : null,
    };
  }
  /** 抛出与真实接口同形的业务错误（ApiError 在 api.js 中定义，调用时才取） */
  const fail = (code, status, params = {}) => {
    throw new SS.ApiError(code, status, params);
  };

  // ---------- 排行榜 ----------
  const NAMES = [
    ["锂电老韭菜", "行业研究员"], ["chain_reader", "产业链"], ["周期之子", null], ["小鹿炒股", null], ["macro_mia", "宏观"],
    ["上游下游", null], ["复盘狂人", "复盘"], ["T+1 守夜人", null], ["稳健派", null], ["板块轮动者", null],
    ["价格先生", null], ["夜行者", null], ["阿尔法小白", null], ["逆向思维", null], ["量价关系", null],
    ["消息灵通", null], ["低吸党", null], ["均线之王", null], ["连板猎手", null], ["不追高", null],
  ];
  const RANKS = [1, 2, 3, 4, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
  const TOTAL = [96, 88, 86, 80, 80, 75, 72, 70, 66, 64, 60, 58, 55, 52, 49, 45, 42, 40, 36, 31];
  const FORECAST = [52, 41, 38, 30, 33, 29, 24, 22, 20, 18, 21, 16, 14, 12, 11, 9, 8, 6, 5, 3];
  const TRADE_BP = [680, 220, 940, -120, 400, 60, 550, 190, -80, 320, 110, 0, -250, 480, 90, 150, -30, 260, 70, -410];
  const DAYS = [5, 4, 5, 3, 5, 4, 3, 5, 4, 2, 5, 3, 2, 4, 3, 5, 2, 4, 3, 1];
  function boardItems(scope) {
    return NAMES.map((n, i) => ({
      rank: RANKS[i],
      username: n[0],
      equipped_title: n[1],
      total_score: scope === "week" ? TOTAL[i] * 3 + 4 : TOTAL[i],
      forecast_score: FORECAST[i],
      trade_score: TOTAL[i] - FORECAST[i],
      return_bp: TRADE_BP[i],
      answered_rounds: 4 - (i % 4 === 3 ? 1 : 0),
      days_played: DAYS[i],
      is_me: false,
    }));
  }
  const ME_DAY = { rank: 37, username: "stock_fan", equipped_title: null, total_score: 57, forecast_score: 41, trade_score: 16, return_bp: 312, answered_rounds: 4, days_played: null, is_me: true };
  const ME_WEEK = { rank: 21, username: "stock_fan", equipped_title: null, total_score: 128, forecast_score: 88, trade_score: 40, return_bp: 312, answered_rounds: null, days_played: 4, is_me: true };

  // ---------- 复盘 / 公开 seed ----------
  const revealOf = (cid) => {
    const s = cid === DAY_ID ? SEED_DAY : SEED_TODAY;
    return {
      challenge_id: cid,
      challenge_date: s.date,
      status: cid === DAY_ID ? "settled" : "running",
      market_seed: s.seed,
      seed_salt: s.salt,
      seed_commitment: DIGEST[cid],
      commitment_input: commitmentInput(s),
      events_ruleset: 2,
      clock_rules: "v2",
      format_version: 1,
      start_minute: 570,
      tick_ms: 750,
      end_tt: 1694,
      rounds: dayRoundRows().map((r) => ({ round_index: r.round_index, event_id: r.event_id, hold_tt: 242 * r.round_index, resolve_tts: { dir: 242 * r.round_index + 726, rank: 242 * r.round_index + 726 }, resume_at: r.resume_at, hold_at: r.hold_at, closes_at: r.closes_at })),
      review_available: true,
    };
  };

  const notSettled = (cid) => fail("CHALLENGE_NOT_SETTLED", 409, { challenge_id: cid });

  SS.mockFeatures.challenge = {
    TODAY_ID,
    DAY_ID,
    /** 列表（日期降序） */
    list: () => [view(TODAY_ID), view(DAY_ID)],
    view,
    /** 已开放回合的卡（pending 不返回） */
    rounds: (cid) => rowsOf(cid).filter((r) => r.state !== "pending").map((r) => roundCard(cid, r.round_index, r)),
    /** 参加：返回 ChallengeEntryOut；已参加返回原记录（200） */
    enter(cid) {
      if (cid !== TODAY_ID) fail("CHALLENGE_ENDED", 409, { challenge_id: cid });
      if (!today.my_entry) {
        today.my_entry = { entry_id: "5a0e1d2c-0000-4000-8000-000000000001", challenge_id: TODAY_ID, save_id: "3d1c0b9a-0000-4000-8000-000000000009", eligible: true, joined_at: iso(Date.now()), answered_rounds: 0, result: null };
      }
      return { ...today.my_entry, answered_rounds: answeredCount(TODAY_ID) };
    },
    /** 作答：返回 ChallengeRoundCardOut；未参加 / 截止 / 未开放按 03 §10.1 抛错 */
    answer(cid, k, answers) {
      const row = rowsOf(cid).find((r) => r.round_index === k);
      if (!row) fail("CHALLENGE_ROUND_NOT_FOUND", 404, { round_index: k });
      if (!entryOf(cid)) fail("CHALLENGE_NOT_ENTERED", 409, { challenge_id: cid });
      if (row.state !== "open") fail("CHALLENGE_ROUND_CLOSED", 409, { round_index: k, closes_at: row.closes_at });
      const prev = mine[cid][k] || { answers: [], revision: 0 };
      const probs = answers.dir ? answers.dir.probs : null;
      const order = answers.rank ? answers.rank.order : null;
      const pick = probs ? probs.indexOf(Math.max(...probs)) : null;
      mine[cid][k] = {
        answers: [
          ...(probs ? [{ qid: "dir", probs, order: null, pick, claimed_pct: Math.max(...probs) }] : []),
          ...(order ? [{ qid: "rank", probs: null, order, pick: null, claimed_pct: null }] : []),
        ],
        revision: prev.revision + 1,
      };
      return roundCard(cid, k, row);
    },
    answeredCount,
    /** 排行：day（已结算场次）；未结算返回 CHALLENGE_NOT_SETTLED */
    board(cid, board = "total") {
      if (cid !== DAY_ID) notSettled(cid);
      return { scope: "day", key: yesterday.challenge_date, board, eligible_count: 402, items: boardItems("day"), me: ME_DAY, next_cursor: null };
    },
    week(scope = "week") {
      const items = boardItems(scope);
      return { scope, key: scope === "week" ? "2026-W44" : "all", board: "total", eligible_count: 402, items, me: scope === "week" ? ME_WEEK : { ...ME_WEEK, rank: 58, total_score: 310, days_played: 9 }, next_cursor: null };
    },
    reveal(cid) {
      if (cid !== DAY_ID) notSettled(cid);
      return revealOf(cid);
    },
    review(cid) {
      if (cid !== DAY_ID) notSettled(cid);
      return { challenge: view(DAY_ID), entry: yesterday.my_entry, rounds: rowsOf(DAY_ID).map((r) => roundCard(DAY_ID, r.round_index, r)), save_available: false };
    },
  };
})();
