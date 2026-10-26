// 快讯 / 事件 / 产业链的纯函数（js/features/news/model.js）：合并去重、过滤、分组、传导回放窗口与步骤、产业链视图、
// 揭示文案、搜索候选、默认焦点、快讯条与收盘大事、行情分段“事件相关”。
export default function (SS, assert, t) {
  const M = SS.newsModel;

  const news = (id, day, tick, extra = {}) => ({
    news_id: id,
    event_id: id.split(":")[0],
    stage: "publish",
    kind: "news",
    scope: "industry",
    major: false,
    sentiment: 1,
    title: id,
    industry: null,
    code: null,
    stock_name: null,
    trading_day: day,
    trading_tick: tick,
    clock_minute: 600,
    ...extra,
  });

  t("mergeNews：按 news_id 去重、按时间倒序、截断；已有项优先", () => {
    const a = news("e1-0:publish", 1, 10);
    const b = news("e2-0:publish", 2, 20);
    const dup = { ...a, title: "改过的" };
    const out = M.mergeNews([a], [b, dup, news("e3-0:publish", 3, 30)], 2);
    assert.deepEqual(out.map((x) => x.news_id), ["e3-0:publish", "e2-0:publish"]);
    assert.equal(M.mergeNews([a], [dup]).find((x) => x.news_id === a.news_id).title, a.title);
  });

  t("matchesFilter：重大 / 政策 / 传闻 / 我的持仓（市场级、持仓代码、持仓行业）", () => {
    const ctx = { codes: new Set(["600519"]), industries: new Set(["有色"]) };
    assert.equal(M.matchesFilter({ major: true }, "major"), true);
    assert.equal(M.matchesFilter({ major: false }, "major"), false);
    assert.equal(M.matchesFilter({ kind: "policy" }, "policy"), true);
    assert.equal(M.matchesFilter({ kind: "rumor" }, "rumor"), true);
    assert.equal(M.matchesFilter({ kind: "news", scope: "market" }, "holding", ctx), true);
    assert.equal(M.matchesFilter({ kind: "news", scope: "stock", code: "600519" }, "holding", ctx), true);
    assert.equal(M.matchesFilter({ kind: "news", scope: "industry", industry: "有色" }, "holding", ctx), true);
    assert.equal(M.matchesFilter({ kind: "news", scope: "industry", industry: "银行" }, "holding", ctx), false);
    assert.equal(M.matchesFilter({}, "all"), true);
  });

  t("groupByDay：相邻同日合并，保持顺序", () => {
    const g = M.groupByDay([news("a:1", 48, 3), news("a:2", 48, 2), news("b:1", 47, 1)]);
    assert.deepEqual(g.map((x) => [x.day, x.items.length]), [[48, 2], [47, 1]]);
  });

  t("newsTags：种类、非发布阶段（亮字）、股票名优先于行业", () => {
    assert.deepEqual(
      M.newsTags({ kind: "rumor", stage: "deny", scope: "industry", industry: "有色" }).map((x) => x.text),
      ["传闻", "已辟谣", "有色"]
    );
    assert.deepEqual(M.newsTags({ kind: "announcement", stage: "publish", scope: "stock", stock_name: "宁德时代", industry: "新能源" }).map((x) => x.text), ["公告", "宁德时代"]);
    assert.equal(M.newsTags({ kind: "rumor", stage: "deny" })[1].cls, "tag--strong");
  });

  t("propWindow：窗口 3 日；已走天数夹在 1..3；默认日为今天或窗口最后一日", () => {
    const ev = { trading_day: 47 };
    assert.deepEqual(M.propWindow(ev, 47), { days: [47, 48, 49], elapsed: 1, defaultDay: 47 });
    assert.deepEqual(M.propWindow(ev, 48), { days: [47, 48, 49], elapsed: 2, defaultDay: 48 });
    assert.deepEqual(M.propWindow(ev, 60), { days: [47, 48, 49], elapsed: 3, defaultDay: 49 });
    assert.equal(M.propWindow(ev, 40).elapsed, 1);
  });

  t("propSteps：只取已到达日的节点；按到达时刻与 hop 排序；源节点无上游", () => {
    const detail = {
      propagation: [
        { industry: "新能源汽车", hop: 2, via_industry: "新能源", relation: "demand", arrived_trading_tick: 300, arrived_trading_day: 49, change_bp: -80 },
        { industry: "有色", hop: 0, via_industry: null, relation: null, arrived_trading_tick: 100, arrived_trading_day: 47, change_bp: 844 },
        { industry: "新能源", hop: 1, via_industry: "有色", relation: "supply", arrived_trading_tick: 200, arrived_trading_day: 48, change_bp: null },
      ],
    };
    const at48 = M.propSteps(detail, 48);
    assert.deepEqual(at48.map((s) => s.industry), ["有色", "新能源"]);
    assert.equal(at48[0].source, true);
    assert.equal(at48[0].from, null);
    assert.equal(at48[1].from, "有色");
    assert.equal(at48[1].relation_text, "供应");
    assert.equal(at48[1].tone, "flat");
    assert.equal(M.propSteps(detail, 49).length, 3);
    assert.equal(M.propSteps(detail, 49)[2].tone, "down");
    assert.equal(M.propSteps(detail, 46).length, 0);
  });

  t("chainView：上游指向焦点的供应/需求、下游由焦点指出、同题材/替代双向", () => {
    const chain = {
      nodes: [{ id: "新能源" }, { id: "有色" }],
      edges: [
        { from_industry: "有色", to_industry: "新能源", relation: "supply" },
        { from_industry: "新能源", to_industry: "新能源汽车", relation: "demand" },
        { from_industry: "新能源", to_industry: "光伏", relation: "same_theme" },
        { from_industry: "汽车", to_industry: "新能源", relation: "substitute" },
      ],
    };
    const v = M.chainView(chain, "新能源");
    assert.deepEqual(v.upstream.map((x) => x.industry), ["有色"]);
    assert.deepEqual(v.downstream.map((x) => x.industry), ["新能源汽车"]);
    assert.deepEqual(v.theme.map((x) => x.industry), ["光伏", "汽车"]);
    assert.equal(M.chainView(chain, "不存在").node, null);
  });

  t("revealText：未揭示为空；level1 只有强度；level2 加滞后", () => {
    assert.equal(M.revealText({ revealed_level: 0, strength: null, lag_days: null }), "");
    assert.equal(M.revealText({ revealed_level: 1, strength: 2, lag_days: null }), "强度 2");
    assert.equal(M.revealText({ revealed_level: 2, strength: 2, lag_days: 1 }), "强度 2 · 滞后 1 天");
  });

  t("suggestIndustries：空串无候选，包含匹配，最多 limit 条", () => {
    const nodes = [{ id: "新能源" }, { id: "新能源汽车" }, { id: "有色" }];
    assert.deepEqual(M.suggestIndustries(nodes, "  "), []);
    assert.deepEqual(M.suggestIndustries(nodes, "新能源"), ["新能源", "新能源汽车"]);
    assert.deepEqual(M.suggestIndustries(nodes, "新能源", 1), ["新能源"]);
  });

  t("defaultFocus：持仓行业优先，否则股票数最多", () => {
    const nodes = [
      { id: "有色", stock_count: 16 },
      { id: "电子", stock_count: 31 },
      { id: "银行", stock_count: 26 },
    ];
    assert.equal(M.defaultFocus(nodes, ["银行", "有色"]), "银行");
    assert.equal(M.defaultFocus(nodes, ["不存在"]), "电子");
    assert.equal(M.defaultFocus([]), null);
  });

  t("pickStrip：有重大取最新重大（不论是否更新于普通快讯），否则最新一条", () => {
    const major = news("e1-0:publish", 47, 500, { major: true });
    const plain = news("e9-0:publish", 48, 900);
    assert.equal(M.pickStrip([major], [plain]).news_id, major.news_id);
    assert.equal(M.pickStrip([], [plain]).news_id, plain.news_id);
    assert.equal(M.pickStrip([], []), null);
  });

  t("dayMajors：只取当日重大，时间倒序，最多 2 条", () => {
    const ms = [
      news("a:1", 48, 10, { major: true }),
      news("b:1", 48, 30, { major: true }),
      news("c:1", 48, 20, { major: true }),
      news("d:1", 47, 99, { major: true }),
      news("e:1", 48, 40, { major: false }),
    ];
    assert.deepEqual(M.dayMajors(ms, 48).map((x) => x.news_id), ["b:1", "c:1"]);
  });

  t("relatedQuotes：事发（源股票、行业级源行业）与传导（已到达行业）；按 |涨跌| 排序；无关股票不入列", () => {
    const events = [
      { scope: "industry", source_industry: "有色", source_code: null },
      { scope: "stock", source_industry: "新能源", source_code: "300750" },
    ];
    const details = [
      { propagation: [{ industry: "有色", hop: 0 }, { industry: "新能源", hop: 1 }] },
      { propagation: [{ industry: "新能源", hop: 0 }] },
    ];
    const quotes = [
      { code: "601899", industry: "有色", change_bp: 300 },
      { code: "603993", industry: "有色", change_bp: -500 },
      { code: "300750", industry: "新能源", change_bp: 100 },
      { code: "002460", industry: "新能源", change_bp: -200 },
      { code: "600519", industry: "白酒", change_bp: 900 },
    ];
    const out = M.relatedQuotes(events, details, quotes, 50);
    assert.deepEqual(out.items.map((q) => q.code), ["603993", "601899", "002460", "300750"]);
    assert.deepEqual(out.notes, { "603993": "事发", "601899": "事发", "002460": "传导", "300750": "事发" });
    assert.equal(M.relatedQuotes(events, details, quotes, 2).items.length, 2);
  });

  t("relatedQuotes：空详情（失败）被跳过；市场级事件的 hop0 行业按传导标注", () => {
    const out = M.relatedQuotes([{ scope: "market", source_industry: null }, { scope: "industry", source_industry: "银行" }], [null, null], [{ code: "600036", industry: "银行", change_bp: 1 }], 50);
    assert.deepEqual(out.items, []);
    const out2 = M.relatedQuotes([{ scope: "market" }], [{ propagation: [{ industry: "银行", hop: 0 }] }], [{ code: "600036", industry: "银行", change_bp: 1 }], 50);
    assert.deepEqual(out2.notes, { "600036": "传导" });
  });

  t("clockText / toneOf：分钟格式与行情色调", () => {
    assert.equal(M.clockText(null), "—");
    assert.equal(M.clockText(570), "09:30");
    assert.equal(M.clockText(1439), "23:59");
    assert.equal(M.toneOf(null), "flat");
    assert.equal(M.toneOf(0), "flat");
    assert.equal(M.toneOf(12), "up");
    assert.equal(M.toneOf(-3), "down");
  });

  t("filterFromQuery：只认 FILTERS 里的 id，其它返回 null（深链 #/news?filter=…）", () => {
    assert.equal(SS.newsModel.filterFromQuery("rumor"), "rumor");
    assert.equal(SS.newsModel.filterFromQuery("major"), "major");
    assert.equal(SS.newsModel.filterFromQuery("holding"), "holding");
    assert.equal(SS.newsModel.filterFromQuery("drop table"), null);
    assert.equal(SS.newsModel.filterFromQuery(undefined), null);
    assert.equal(SS.newsModel.filterFromQuery(["rumor"]), null, "数组参数不接受");
  });

  t("klineMarks：按 trading_day 对齐 K 线下标；窗口外的丢弃；保留同日多条", () => {
    const candles = [{ trading_day: 10 }, { trading_day: 11 }, { trading_day: 12 }];
    const marks = [
      { event_id: "a", trading_day: 12, role: "source", title: "甲", major: true, kind: "sudden", sentiment: -1, trading_tick: 2000 },
      { event_id: "b", trading_day: 11, role: "propagated", title: "乙", major: false, kind: "news", sentiment: 1, trading_tick: 1500 },
      { event_id: "c", trading_day: 11, role: "market", title: "丙", major: false, kind: "policy", sentiment: 1, trading_tick: 1200 },
      { event_id: "d", trading_day: 3, role: "source", title: "丁", major: false, kind: "news", sentiment: 1, trading_tick: 100 },
    ];
    const out = SS.newsModel.klineMarks(marks, candles);
    assert.deepEqual(out.map((m) => m.event_id), ["a", "b", "c"]);
    assert.deepEqual(out.map((m) => m.index), [2, 1, 1]);
    assert.equal(out[1].roleText, "传导");
    assert.equal(out[0].roleText, "事发");
    assert.deepEqual(SS.newsModel.klineMarks(null, candles), []);
  });

  t("markLegend：取前 limit 条，带角色文案与重大标记，不带 trading_tick", () => {
    const marks = [
      { event_id: "a", trading_day: 12, role: "source", title: "甲", major: true, kind: "sudden", sentiment: -1, trading_tick: 2000 },
      { event_id: "c", trading_day: 11, role: "market", title: "丙", major: false, kind: "policy", sentiment: 1, trading_tick: 1200 },
    ];
    const lg = SS.newsModel.markLegend(marks, 1);
    assert.equal(lg.length, 1);
    assert.equal(lg[0].roleText, "事发");
    assert.equal(lg[0].major, true);
    assert.equal("trading_tick" in lg[0], false);
  });

  t("constituents：按 industry 过滤、代码升序、超出 limit 时给出 total", () => {
    const quotes = [
      { code: "601899", name: "紫金矿业", industry: "有色" },
      { code: "000001", name: "甲", industry: "银行" },
      { code: "000630", name: "铜陵有色", industry: "有色" },
      { code: "600362", name: "江西铜业", industry: "有色" },
    ];
    const c = SS.newsModel.constituents(quotes, "有色", 2);
    assert.equal(c.total, 3);
    assert.deepEqual(c.items.map((q) => q.code), ["000630", "600362"]);
    assert.equal(SS.newsModel.constituents(quotes, "电力").total, 0);
    assert.equal(SS.newsModel.constituents(null, "有色").total, 0);
  });

  t("revealOf：边方向两种都查（需求从下游传到上游）；源节点与未揭示返回 {}", () => {
    const rev = { "银行>房地产": { revealed_level: 1, strength: 2, lag_days: null } };
    // 房地产需求 → 银行：step.from=房地产，industry=银行，边是 银行>房地产
    assert.deepEqual(M.revealOf(rev, { from: "房地产", industry: "银行", source: false }), rev["银行>房地产"]);
    assert.deepEqual(M.revealOf(rev, { from: "银行", industry: "房地产", source: false }), rev["银行>房地产"]);
    assert.deepEqual(M.revealOf(rev, { from: "房地产", industry: "钢铁", source: false }), {});
    assert.deepEqual(M.revealOf(rev, { from: null, industry: "房地产", source: true }), {});
  });

  t("lockText：全部隐藏保持原文案；部分只揭示强度时提示滞后仍隐藏；全部揭示到 L2", () => {
    const steps = [
      { from: "房地产", industry: "银行", source: false },
      { from: "房地产", industry: "钢铁", source: false },
      { from: null, industry: "房地产", source: true },
    ];
    assert.equal(M.lockText(steps, {}), "每条边的强度和滞后天数是隐藏的");
    assert.equal(M.lockText([], {}), "每条边的强度和滞后天数是隐藏的");
    const one = { "银行>房地产": { revealed_level: 1, strength: 2, lag_days: null } };
    assert.equal(M.lockText(steps, one), "1 条边的强度和滞后隐藏，1 条边的滞后隐藏");
    const two = { "银行>房地产": { revealed_level: 2, strength: 2, lag_days: 1 }, "钢铁>房地产": { revealed_level: 2, strength: 1, lag_days: 0 } };
    assert.equal(M.lockText(steps, two), "已走到的边强度和滞后都已揭示");
  });

  t("事件摘要：优先首条快讯标题（与事件标题不同），否则用事发行业与波及数", () => {
    const d = { title: "锂矿停产", source_industry: "锂矿", news: [{ title: "锂矿停产整改，供给约占 8%" }], propagation: [{ hop: 0 }, { hop: 1 }, { hop: 2 }] };
    assert.equal(M.eventSummary(d), "锂矿停产整改，供给约占 8%");
    assert.equal(M.eventSummary({ ...d, news: [{ title: "锂矿停产" }] }), "事发于锂矿，已波及 2 个行业");
    assert.equal(M.eventSummary({ ...d, news: [{ title: "锂矿停产" }], propagation: [{ hop: 0 }] }), "事发于锂矿");
    assert.equal(M.eventSummary({ title: "x", news: [], propagation: [] }), "");
    assert.equal(M.eventSummary(null), "");
  });
}
