/**
 * 真实复盘的假数据（SS.mockFeatures.replay）：两个小关卡，全部为虚构公司与事件（假数据，仅用于界面验证）。
 * 关卡包由下面的规格确定性生成（mulberry32 随机 + 固定 seed），形状同 05 §3.2 的关卡包（简化字段）：
 *   calendar（与 bars 对齐）、stocks（真实与别名、mask_scale_ppm）、bars（真实价）、benchmark、events、questions。
 * pack(slug) 惰性构建并缓存；依赖 SS.replayModel（model.js 先于本文件加载）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const M = (SS.mockFeatures = SS.mockFeatures || {});

  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /** 日 K：[o,h,l,c,v]，n 根，下标 j 对应游戏日 j − lookback；shocks[游戏日] = {open, close}（bp） */
  function genBars(seed, n, lookback, startCents, shocks) {
    const rand = rng(seed);
    const out = [];
    let prev = startCents;
    for (let j = 0; j < n; j++) {
      const sh = shocks[j - lookback] || {};
      const gap = (rand() - 0.5) * 0.024 + (sh.open || 0) / 1e4;
      const o = Math.round(prev * (1 + gap));
      const c = Math.round(o * (1 + (rand() - 0.5) * 0.04 + (sh.close || 0) / 1e4));
      const h = Math.round(Math.max(o, c) * (1 + rand() * 0.012));
      const l = Math.round(Math.min(o, c) * (1 - rand() * 0.012));
      const v = 100 * Math.round((2e6 + rand() * 6e6) / 100);
      out.push([o, h, l, c, v]);
      prev = c;
    }
    return out;
  }

  /** 从 iso 起连续 n 个工作日（不含节假日，假数据） */
  function weekdaysFrom(iso, n) {
    const out = [];
    let t = Date.parse(iso + "T00:00:00Z");
    while (out.length < n) {
      const wd = new Date(t).getUTCDay();
      if (wd !== 0 && wd !== 6) out.push(new Date(t).toISOString().slice(0, 10));
      t += 86400000;
    }
    return out;
  }

  const SPECS = [
    {
      slug: "stamp-duty-2023",
      version: 1,
      sort_order: 1,
      title: "印花税减半",
      title_masked: "周末突发的交易成本政策",
      teaser: "市场连续阴跌，一个周末之后，交易成本政策被调整。（假数据）",
      teaser_masked: "市场连续阴跌，一个周末之后，交易成本政策被调整。（假数据）",
      tags: ["政策", "券商"],
      difficulty: 2,
      kind: "curated",
      play_days: 8,
      reveal_days: 4,
      lookback_days: 20,
      calendar_start: "2023-07-31",
      masked_allowed: true,
      bench_seed: 77,
      bench_name: "沪深300（假）",
      commentary: "（假数据）政策在周末宣布，下一交易日起生效。券商板块通常先于大盘反应，但持续性取决于成交额能否跟上。",
      stocks: [
        { key: "s1", role: "focus", real_code: "600100", real_name: "华岳证券", industry: "券商", seed: 101, start: 1720, masked_prev: 1248, shocks: { 0: { open: 420 }, 3: { close: -260 } } },
        { key: "s2", role: "peer", real_code: "600200", real_name: "远峰证券", industry: "券商", seed: 102, start: 1310, masked_prev: 1085, shocks: { 0: { open: 300 }, 1: { close: 380 } } },
        { key: "s3", role: "upstream", real_code: "002310", real_name: "北辰建材", industry: "建材", seed: 103, start: 980, masked_prev: 1950, shocks: { 4: { close: 500 } } },
        { key: "s4", role: "peer", real_code: "600400", real_name: "青松证券", industry: "券商", seed: 104, start: 2640, masked_prev: 1520, shocks: { 0: { open: 250 } } },
        { key: "s5", role: "peer", real_code: "600500", real_name: "南海医药", industry: "医药", seed: 105, start: 3380, masked_prev: 3960, shocks: {} },
      ],
      events: [
        { id: "e0001", day_idx: -2, slot: "intraday", kind: "news", scope: "market", stock_keys: [], industries: [], importance: 2, source: "manual", local_time: "2023-08-25 11:20", title: "监管部门：继续推进资本市场改革（假数据）", title_masked: "监管部门：继续推进资本市场改革（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0002", day_idx: -1, slot: "post_close", kind: "policy", scope: "market", stock_keys: [], industries: [], importance: 2, source: "manual", local_time: "2023-08-25 17:30", title: "财政部门：研究调整证券交易印花税（假数据）", title_masked: "财税部门：研究调整证券交易相关税费（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0003", day_idx: 0, slot: "pre_open", kind: "policy", scope: "market", stock_keys: [], industries: [], importance: 3, source: "manual", local_time: "2023-08-27 18:00", title: "财政部、税务总局：证券交易印花税自次日起减半征收（假数据）", title_masked: "财税部门：自下一交易日起证券交易印花税减半征收（假数据）", body: "（假数据）关卡作者核对原文后填写。", body_masked: "（假数据）关卡作者核对原文后填写。" },
        { id: "e0004", day_idx: 0, slot: "pre_open", kind: "announcement", scope: "stock", stock_keys: ["s1"], industries: ["券商"], importance: 2, source: "manual", local_time: "2023-08-27 19:10", title: "华岳证券：2023 年半年度业绩预告（假数据）", title_masked: "股票 A：半年度业绩预告（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0005", day_idx: 1, slot: "intraday", kind: "news", scope: "industry", stock_keys: [], industries: ["券商"], importance: 2, source: "manual", local_time: "2023-08-28 10:12", title: "券商板块盘中异动，多股涨停（假数据）", title_masked: "一类股票盘中异动，多只涨停（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0006", day_idx: 2, slot: "pre_open", kind: "news", scope: "market", stock_keys: [], industries: [], importance: 1, source: "em_news", local_time: "2023-08-29 08:40", title: "传闻：监管拟进一步优化融资规则（假数据）", title_masked: "市场传闻：相关规则可能再调整（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0007", day_idx: 3, slot: "post_close", kind: "policy", scope: "market", stock_keys: [], industries: [], importance: 2, source: "cctv", local_time: "2023-08-30 19:00", title: "新闻联播：资本市场平稳运行（假数据）", title_masked: "新闻联播：资本市场平稳运行（假数据）", body: "（假数据）", body_masked: "（假数据）", hide_in_masked: true },
        { id: "e0008", day_idx: 4, slot: "intraday", kind: "announcement", scope: "stock", stock_keys: ["s3"], industries: ["建材"], importance: 2, source: "cninfo", local_time: "2023-08-31 13:05", title: "北辰建材：中标重大项目（假数据）", title_masked: "股票 C：中标重大项目（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0009", day_idx: 5, slot: "pre_open", kind: "news", scope: "industry", stock_keys: [], industries: ["券商"], importance: 1, source: "em_news", local_time: "2023-09-01 08:30", title: "券商研报：行业景气度回升（假数据）", title_masked: "行业研报：景气度回升（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0010", day_idx: 6, slot: "post_close", kind: "policy", scope: "market", stock_keys: [], industries: [], importance: 2, source: "manual", local_time: "2023-09-05 17:45", title: "监管部门：优化资本市场交易制度（假数据）", title_masked: "监管部门：优化资本市场交易制度（假数据）", body: "（假数据）", body_masked: "（假数据）" },
      ],
      questions: [
        { id: "q1", kind: "direction_bucket", stock_key: "s1", opens: { day: 1, phase: "pre_open" }, closes: { day: 1, phase: "pre_open" }, resolves: { day: 5, phase: "close" }, horizon: 5, prompt: "从昨收到 5 个交易日后收盘，华岳证券的涨跌幅落在哪一档？", prompt_masked: "从昨收到 5 个交易日后收盘，{name} 的涨跌幅落在哪一档？" },
        { id: "q2", kind: "rank", stock_keys: ["s1", "s2", "s3", "s4", "s5"], top_k: 3, opens: { day: 3, phase: "pre_open" }, closes: { day: 4, phase: "pre_open" }, resolves: { day: 7, phase: "close" }, horizon: 5, prompt: "未来 5 个交易日涨幅前三，按顺序选（第 3 天起算）", prompt_masked: "未来 5 个交易日涨幅前三，按顺序选（第 3 天起算）" },
      ],
    },
    {
      slug: "supply-halt-2021",
      version: 1,
      sort_order: 2,
      title: "上游产线停产检修",
      title_masked: "一家上游工厂的意外停产",
      teaser: "一家上游工厂突然停产检修，产业链会怎么反应？（假数据）",
      teaser_masked: "一家上游工厂突然停产检修，产业链会怎么反应？（假数据）",
      tags: ["停产", "行业"],
      difficulty: 1,
      kind: "curated",
      play_days: 6,
      reveal_days: 3,
      lookback_days: 20,
      calendar_start: "2021-02-01",
      masked_allowed: true,
      bench_seed: 88,
      bench_name: "化工指数（假）",
      commentary: "（假数据）停产公告通常先冲击上游同行的股价，下游要等原料价格传导后才会反映。",
      stocks: [
        { key: "s1", role: "focus", real_code: "603100", real_name: "北川新材", industry: "化工", seed: 201, start: 1540, masked_prev: 1620, shocks: { 1: { open: -300 }, 2: { close: -500 } } },
        { key: "s2", role: "peer", real_code: "002200", real_name: "南海化工", industry: "化工", seed: 202, start: 2210, masked_prev: 2750, shocks: {} },
        { key: "s3", role: "upstream", real_code: "600300", real_name: "西岭钢铁", industry: "钢铁", seed: 203, start: 890, masked_prev: 1180, shocks: { 0: { open: -200 } } },
      ],
      events: [
        { id: "e0101", day_idx: 0, slot: "pre_open", kind: "announcement", scope: "stock", stock_keys: ["s3"], industries: ["钢铁"], importance: 3, source: "cninfo", local_time: "2021-03-01 08:20", title: "西岭钢铁：子公司产线停产检修公告（假数据）", title_masked: "股票 C：子公司产线停产检修公告（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0102", day_idx: 1, slot: "intraday", kind: "news", scope: "industry", stock_keys: [], industries: ["化工"], importance: 2, source: "em_news", local_time: "2021-03-02 10:40", title: "化工板块盘中跟涨，原料价格上行（假数据）", title_masked: "同类板块盘中跟涨（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0103", day_idx: 2, slot: "pre_open", kind: "news", scope: "market", stock_keys: [], industries: [], importance: 1, source: "em_news", local_time: "2021-03-03 08:35", title: "研报：停产影响有限，需观察复产节奏（假数据）", title_masked: "研报：停产影响有限，需观察复产节奏（假数据）", body: "（假数据）", body_masked: "（假数据）" },
        { id: "e0104", day_idx: 4, slot: "post_close", kind: "policy", scope: "market", stock_keys: [], industries: [], importance: 2, source: "manual", local_time: "2021-03-05 17:30", title: "环保督查通知：多地加强检查（假数据）", title_masked: "环保督查通知：多地加强检查（假数据）", body: "（假数据）", body_masked: "（假数据）" },
      ],
      questions: [
        { id: "q1", kind: "direction_bucket", stock_key: "s1", opens: { day: 2, phase: "pre_open" }, closes: { day: 2, phase: "pre_open" }, resolves: { day: 4, phase: "close" }, horizon: 3, prompt: "从昨收到 3 个交易日后收盘，北川新材的涨跌幅落在哪一档？", prompt_masked: "从昨收到 3 个交易日后收盘，{name} 的涨跌幅落在哪一档？" },
      ],
    },
  ];

  const cache = {};

  /** 构建关卡包（真实价 + 别名缩放系数），惰性缓存 */
  function pack(slug) {
    if (cache[slug]) return cache[slug];
    const spec = SPECS.find((s) => s.slug === slug);
    if (!spec) return null;
    const R = SS.replayModel;
    const lb = spec.lookback_days;
    const n = lb + spec.play_days + spec.reveal_days;
    const bars = {};
    const stocks = spec.stocks.map((s, i) => {
      bars[s.key] = genBars(s.seed, n, lb, s.start, s.shocks);
      const prevClose = bars[s.key][lb - 1][3];
      return {
        key: s.key,
        role: s.role,
        real_code: s.real_code,
        real_name: s.real_name,
        industry: s.industry,
        alias_code: `990${String(i + 1).padStart(3, "0")}`,
        alias_name: `股票 ${String.fromCharCode(65 + i)}`,
        mask_scale_ppm: R.pickScalePpm(prevClose, s.masked_prev),
      };
    });
    const bench = genBars(spec.bench_seed, n, lb, 330000, {}).map((b) => b[3]);
    const questions = spec.questions.map((q) => {
      const out = { ...q };
      if (q.kind === "direction_bucket") {
        const cs = bars[q.stock_key].map((b) => b[3]);
        const rets = [];
        for (let j = 1; j < lb; j++) rets.push((cs[j] / cs[j - 1] - 1) * 1e4);
        out.edges_bp = R.autoEdges(rets, q.horizon);
      }
      return out;
    });
    cache[slug] = {
      format: "stocksim-replay-pack",
      slug: spec.slug,
      version: spec.version,
      title: spec.title,
      title_masked: spec.title_masked,
      teaser: spec.teaser,
      teaser_masked: spec.teaser_masked,
      tags: spec.tags,
      difficulty: spec.difficulty,
      kind: spec.kind,
      masked_allowed: spec.masked_allowed,
      play_days: spec.play_days,
      reveal_days: spec.reveal_days,
      lookback_days: lb,
      calendar: weekdaysFrom(spec.calendar_start, n),
      benchmark: { name: spec.bench_name, closes: bench },
      stocks,
      bars,
      events: spec.events.map((e) => ({ ...e })),
      questions,
      commentary: spec.commentary,
    };
    return cache[slug];
  }

  /** 关卡列表项的基础字段（不含 my_best） */
  const levelBase = (s) => ({ slug: s.slug, version: s.version, sort_order: s.sort_order, tags: s.tags, difficulty: s.difficulty, kind: s.kind, play_days: s.play_days, stock_count: s.stocks.length, masked_allowed: s.masked_allowed });

  M.replayLevelSpecs = SPECS;
  M.replayPack = pack;
  M.replayLevelBase = levelBase;
  M.replayWeekdaysFrom = weekdaysFrom;
})();
