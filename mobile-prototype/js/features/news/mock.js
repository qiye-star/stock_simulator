/**
 * 快讯 / 事件 / 产业链的假数据（确定性）。字段与 backend/src/stocksim/schemas/events.py 一致；私有字段以 _ 开头。
 *   SS.mockFeatures.news = { events: EventSpec[], queue: [news_id…] }
 *   - 事件按 (trading_day, slot) 给出；news 中 _queued=true 的快讯尚未“发布”，由 mock store 按队列推送；
 *   - 时钟：今天是 trading_day 48，10:35（与 js/mock/data.js 一致）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.mockFeatures = SS.mockFeatures || {};

  /** 分钟 → 日内偏移（v2：9:30=0，11:30=120 不接单，13:00=121，15:00=241） */
  const off = (m) => (m <= 690 ? m - 570 : m - 659);
  const tt = (day, m) => day * 242 + off(m);
  const NAME = { 601899: "紫金矿业", 603993: "洛阳钼业", 300750: "宁德时代", 002460: "赣锋锂业" };

  // 产业链：12 个节点（与 backend/src/stocksim/data/supply_chain.json 的行业名一致）+ 14 条边
  const NODES = [
    ["有色", 1, 16, ["601899", "603993"]],
    ["化工", 1, 22, []],
    ["稀土", 1, 6, []],
    ["电子", 2, 31, []],
    ["电力", 3, 18, []],
    ["光伏", 3, 12, []],
    ["新能源", 4, 16, ["300750", "002460"]],
    ["新能源汽车", 5, 20, []],
    ["汽车", 5, 14, []],
    ["家电", 5, 9, []],
    ["银行", 1, 26, []],
    ["券商", 1, 11, []],
  ];
  const EDGES = [
    // from, to, relation, sign, strength, lag, revealed_level
    ["有色", "新能源", "supply", -1, 2, 1, 1],
    ["化工", "新能源", "supply", 1, 2, 0, 0],
    ["稀土", "汽车", "supply", 1, 1, 1, 0],
    ["电子", "新能源汽车", "supply", 1, 2, 0, 0],
    ["电子", "家电", "supply", 1, 1, 1, 0],
    ["有色", "电子", "supply", 1, 1, 2, 0],
    ["有色", "电力", "supply", 1, 1, 1, 0],
    ["光伏", "电力", "supply", 1, 2, 1, 0],
    ["化工", "光伏", "supply", 1, 1, 2, 0],
    ["电力", "家电", "supply", 1, 1, 0, 0],
    ["新能源", "新能源汽车", "demand", 1, 3, 1, 0],
    ["新能源", "汽车", "demand", 1, 1, 2, 0],
    ["新能源", "电力", "demand", 1, 2, 1, 0],
    ["新能源", "光伏", "same_theme", 1, 2, 0, 0],
    ["汽车", "新能源汽车", "substitute", -1, 1, 0, 0],
    ["银行", "券商", "same_theme", 1, 2, 0, 0],
  ];

  /** 事件规格：publish 为正式发布的快讯；extra 为后续快讯（confirm/deny/precursor）；prop 为已到达/将到达的传导步骤 */
  const EVENTS = [
    {
      day: 46, slot: 0, kind: "policy", subtype: null, scope: "market", source_industry: null, source_code: null, major: true, sentiment: 1,
      phase: "settled", rumor: null,
      news: [{ stage: "publish", minute: 580, title: "央行宣布定向降准，释放长期资金约 5000 亿元", sentiment: 1 }],
      prop: [
        { industry: "银行", hop: 0, via: null, relation: null, day: 46, minute: 580, bp: 120 },
        { industry: "券商", hop: 1, via: "银行", relation: "same_theme", day: 47, minute: 600, bp: 260 },
      ],
    },
    {
      day: 47, slot: 0, kind: "sudden", subtype: null, scope: "industry", source_industry: "有色", source_code: null, major: true, sentiment: -1,
      phase: "active", rumor: null,
      news: [{ stage: "publish", minute: 582, title: "华中某锂矿区因环保督察全面停产整改，涉及国内锂盐供给约 8%", sentiment: -1 }],
      prop: [
        { industry: "有色", hop: 0, via: null, relation: null, day: 47, minute: 582, bp: 844 },
        { industry: "新能源", hop: 1, via: "有色", relation: "supply", day: 48, minute: 570, bp: -440 },
        { industry: "新能源汽车", hop: 2, via: "新能源", relation: "demand", day: 48, minute: 600, bp: -80 },
      ],
    },
    {
      day: 47, slot: 4, kind: "announcement", subtype: "股份回购", scope: "stock", source_industry: "新能源", source_code: "300750", major: false, sentiment: 1,
      phase: "settled", rumor: null,
      news: [{ stage: "publish", minute: 800, title: "宁德时代：拟以不超过 5 亿元回购股份", sentiment: 1 }],
      prop: [{ industry: "新能源", hop: 0, via: null, relation: null, day: 47, minute: 800, bp: 230 }],
    },
    {
      day: 48, slot: 2, kind: "rumor", subtype: null, scope: "industry", source_industry: "有色", source_code: null, major: false, sentiment: 1,
      phase: "active", rumor: { status: "denied", resolve_minute: 605 },
      news: [
        { stage: "publish", minute: 590, title: "网传矿区一周内复产", sentiment: 1 },
        { stage: "deny", minute: 605, title: "当地回应：矿区复产时间未定，“一周内复产”传闻不实", sentiment: -1 },
      ],
      prop: [{ industry: "有色", hop: 0, via: null, relation: null, day: 48, minute: 590, bp: 310 }],
    },
    {
      day: 48, slot: 3, kind: "news", subtype: null, scope: "industry", source_industry: "新能源", source_code: null, major: false, sentiment: 1,
      phase: "active", rumor: null,
      news: [{ stage: "publish", minute: 571, title: "两家电池龙头宣布上调电芯报价 3%–5%", sentiment: 1 }],
      prop: [{ industry: "新能源", hop: 0, via: null, relation: null, day: 48, minute: 571, bp: 180 }],
    },
    {
      day: 48, slot: 5, kind: "news", subtype: null, scope: "industry", source_industry: "有色", source_code: null, major: false, sentiment: 1,
      phase: "active", rumor: null,
      news: [{ stage: "publish", minute: 615, title: "有色板块集体拉升，多只锂业股封板", sentiment: 1 }],
      prop: [{ industry: "有色", hop: 0, via: null, relation: null, day: 48, minute: 615, bp: 300 }],
    },
    // 以下尚未发布：由 mock store 按队列推送（WS news）
    {
      day: 48, slot: 6, kind: "sudden", subtype: null, scope: "industry", source_industry: "有色", source_code: null, major: true, sentiment: -1,
      phase: "active", rumor: null, queued: true,
      news: [{ stage: "publish", minute: 636, title: "某锂盐企业停产检修，产能约占行业 3%", sentiment: -1 }],
      prop: [
        { industry: "有色", hop: 0, via: null, relation: null, day: 48, minute: 636, bp: -120 },
        { industry: "新能源", hop: 1, via: "有色", relation: "supply", day: 49, minute: 570, bp: null },
      ],
    },
    {
      day: 48, slot: 7, kind: "policy", subtype: null, scope: "market", source_industry: null, source_code: null, major: false, sentiment: 1,
      phase: "active", rumor: null, queued: true,
      news: [{ stage: "publish", minute: 652, title: "工信部征求意见：新能源汽车补贴延续至年底", sentiment: 1 }],
      prop: [{ industry: "新能源汽车", hop: 0, via: null, relation: null, day: 48, minute: 652, bp: null }],
    },
    {
      day: 48, slot: 8, kind: "rumor", subtype: null, scope: "stock", source_industry: "新能源", source_code: "300750", major: false, sentiment: 1,
      phase: "active", rumor: { status: "unresolved", resolve_minute: null }, queued: true,
      news: [{ stage: "publish", minute: 658, title: "网传某电池龙头有意收购上游矿企", sentiment: 1 }],
      prop: [{ industry: "新能源", hop: 0, via: null, relation: null, day: 48, minute: 658, bp: null }],
    },
  ];

  // 构造事件与快讯
  const events = [];
  const queue = [];
  for (const sp of EVENTS) {
    const eventId = `e${sp.day}-${sp.slot}`;
    const news = sp.news.map((n) => {
      const item = {
        news_id: `${eventId}:${n.stage}`,
        event_id: eventId,
        stage: n.stage,
        kind: sp.kind,
        subtype: sp.subtype,
        scope: sp.scope,
        major: sp.major,
        sentiment: n.sentiment,
        title: n.title,
        industry: sp.source_industry,
        code: sp.source_code,
        stock_name: sp.source_code ? NAME[sp.source_code] || null : null,
        trading_day: sp.day,
        trading_tick: tt(sp.day, n.minute),
        day_offset: off(n.minute),
        tick: null,
        clock_minute: n.minute,
        _queued: !!sp.queued,
      };
      if (sp.queued) queue.push(item.news_id);
      return item;
    });
    const pub = news.find((x) => x.stage === "publish") || news[0];
    const first = news.slice().sort((a, b) => a.trading_tick - b.trading_tick)[0];
    const rumorStatus = sp.rumor ? sp.rumor.status : null;
    events.push({
      event: {
        event_id: eventId,
        trading_day: sp.day,
        slot: sp.slot,
        kind: sp.kind,
        subtype: sp.subtype,
        scope: sp.scope,
        source_industry: sp.source_industry,
        source_code: sp.source_code,
        major: sp.major,
        sentiment: sp.sentiment,
        title: pub.title,
        first_seen_trading_tick: first.trading_tick,
        publish_trading_tick: tt(sp.day, sp.news[0].minute),
        phase: sp.phase,
        rumor_status: rumorStatus,
        resolved_trading_tick: sp.rumor && sp.rumor.resolve_minute != null ? tt(sp.day, sp.rumor.resolve_minute) : null,
      },
      news,
      propagation: sp.prop.map((p) => ({
        industry: p.industry,
        hop: p.hop,
        via_industry: p.via,
        relation: p.relation,
        arrived_trading_tick: tt(p.day, p.minute),
        arrived_trading_day: p.day,
        change_bp: p.bp,
      })),
    });
  }

  // 产业链结构（SupplyChainOut）
  const chain = {
    ruleset: 1,
    nodes: NODES.map(([id, layer, count, leaders]) => ({ id, layer, stock_count: count, leaders })),
    edges: EDGES.map(([from, to, relation, sign, strength, lag, level]) => ({
      id: `${from}>${to}`,
      from_industry: from,
      to_industry: to,
      relation,
      sign,
      strength: level >= 1 ? strength : null,
      lag_days: level >= 2 ? lag : null,
      revealed_level: level,
      _strength: strength, // 隐藏真值（⑥ 情报卡购买后揭示，见 js/features/predict/store.js）
      _lag: lag,
    })),
  };

  SS.mockFeatures.news = { events, chain, queue };
})();
