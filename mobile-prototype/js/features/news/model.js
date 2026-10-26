/**
 * 快讯 / 事件 / 产业链的纯函数（无 DOM、不读 SS.store）：供页面与 tests/news-model.test.mjs 使用。
 * 输入输出字段与 backend/src/stocksim/schemas/events.py 一致。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  const PROP_DAYS = 3; // 传导回放窗口（与后端 industry_change_bp 的 3 日窗口一致）
  const FEED_LIMIT = 50; // 快讯缓存上限（WS 合并后）
  const MAJOR_LIMIT = 20; // 重大快讯缓存上限
  const FILTERS = [
    { id: "all", label: "全部" },
    { id: "major", label: "重大" },
    { id: "holding", label: "我的持仓" },
    { id: "policy", label: "政策" },
    { id: "rumor", label: "传闻" },
  ];
  const KIND_TEXT = { announcement: "公告", news: "新闻", policy: "政策", sudden: "突发", rumor: "传闻" };
  const STAGE_TEXT = { precursor: "预期", confirm: "已证实", deny: "已辟谣" };
  const RUMOR_TEXT = { unresolved: "未揭晓", confirmed: "已证实", denied: "已辟谣" };
  const RELATION_TEXT = { supply: "供应", demand: "需求", substitute: "替代", same_theme: "同题材" };

  const has = (set, v) => !!set && typeof set.has === "function" && set.has(v);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const newer = (a, b) => (a.trading_tick - b.trading_tick) || (a.news_id < b.news_id ? -1 : a.news_id > b.news_id ? 1 : 0);

  /** 分钟数 → "HH:MM"；null 为 "—" */
  function clockText(minute) {
    if (minute == null) return "—";
    const h = Math.floor(minute / 60);
    const m = minute % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }

  /** bp → 行情色调（只用于行情数据：up/down/flat） */
  const toneOf = (bp) => (bp == null || bp === 0 ? "flat" : bp > 0 ? "up" : "down");

  /** 按 (trading_tick desc, news_id asc) 排序的副本 */
  function sortNews(items) {
    return items.slice().sort((a, b) => newer(b, a));
  }

  /** 合并快讯：按 news_id 去重（已有的优先），排序后截断 */
  function mergeNews(list, incoming, limit = FEED_LIMIT) {
    const seen = new Set(list.map((x) => x.news_id));
    const add = [];
    for (const it of incoming || []) {
      if (seen.has(it.news_id)) continue;
      seen.add(it.news_id);
      add.push(it);
    }
    return sortNews([...list, ...add]).slice(0, limit);
  }

  /** 过滤胶囊的谓词。holding 需要 ctx.codes（持仓代码 Set）与 ctx.industries（持仓行业 Set） */
  function matchesFilter(item, filter, ctx = {}) {
    switch (filter) {
      case "major":
        return !!item.major;
      case "policy":
        return item.kind === "policy";
      case "rumor":
        return item.kind === "rumor";
      case "holding":
        return item.scope === "market" || (!!item.code && has(ctx.codes, item.code)) || (!!item.industry && has(ctx.industries, item.industry));
      default:
        return true;
    }
  }

  /** 按交易日分组（保持输入顺序；输入已按时间倒序） */
  function groupByDay(items) {
    const map = new Map();
    for (const it of items) {
      if (!map.has(it.trading_day)) map.set(it.trading_day, []);
      map.get(it.trading_day).push(it);
    }
    return Array.from(map, ([day, list]) => ({ day, items: list }));
  }

  /** 快讯条目的标签：[{text, cls}]；cls 只用于样式，颜色来自 tokens */
  function newsTags(item) {
    const tags = [{ text: KIND_TEXT[item.kind] || item.kind, cls: "" }];
    if (item.stage && item.stage !== "publish") tags.push({ text: STAGE_TEXT[item.stage] || item.stage, cls: "tag--strong" });
    if (item.scope === "stock" && item.stock_name) tags.push({ text: item.stock_name, cls: "" });
    else if (item.industry) tags.push({ text: item.industry, cls: "" });
    return tags;
  }

  /** 传导回放窗口：窗口天数、已走天数（a / 3）、默认选中的日（今天或窗口最后一日） */
  function propWindow(event, curDay) {
    const start = event.trading_day;
    return {
      days: Array.from({ length: PROP_DAYS }, (_, i) => start + i),
      elapsed: clamp(curDay - start + 1, 1, PROP_DAYS),
      defaultDay: clamp(curDay, start, start + PROP_DAYS - 1),
    };
  }

  /**
   * 传导回放在 day（含）之前已到达的步骤，按到达时刻、hop 排序。
   * 每步：{industry, hop, from (源行业或上游行业，源节点为 null), relation_text, tone, change_bp, arrived_trading_day, source}
   */
  function propSteps(detail, day) {
    return (detail.propagation || [])
      .filter((s) => s.arrived_trading_day <= day)
      .slice()
      .sort((a, b) => a.arrived_trading_tick - b.arrived_trading_tick || a.hop - b.hop)
      .map((s) => ({
        industry: s.industry,
        hop: s.hop,
        from: s.hop === 0 ? null : s.via_industry,
        relation_text: RELATION_TEXT[s.relation] || "",
        tone: toneOf(s.change_bp),
        change_bp: s.change_bp,
        arrived_trading_day: s.arrived_trading_day,
        source: s.hop === 0,
      }));
  }

  /**
   * 产业链视图：焦点行业的上游（to=焦点，供应/需求）、下游（from=焦点，供应/需求）、同题材/替代。
   * 返回的 edge 保留原字段（用于展示揭示状态）。焦点不存在时各列为空。
   */
  function chainView(chain, focus) {
    const nodes = (chain && chain.nodes) || [];
    const node = nodes.find((n) => n.id === focus) || null;
    const view = { node, upstream: [], downstream: [], theme: [] };
    if (!node) return view;
    for (const e of (chain && chain.edges) || []) {
      if (e.relation === "same_theme" || e.relation === "substitute") {
        if (e.from_industry === focus) view.theme.push({ industry: e.to_industry, edge: e });
        else if (e.to_industry === focus) view.theme.push({ industry: e.from_industry, edge: e });
      } else if (e.to_industry === focus) view.upstream.push({ industry: e.from_industry, edge: e });
      else if (e.from_industry === focus) view.downstream.push({ industry: e.to_industry, edge: e });
    }
    return view;
  }

  /** 已揭示的边文案：level 1 只有强度，level 2 加滞后；未揭示返回 "" */
  function revealText(edge) {
    const level = edge.revealed_level || 0;
    const parts = [];
    if (level >= 1 && edge.strength != null) parts.push(`强度 ${edge.strength}`);
    if (level >= 2 && edge.lag_days != null) parts.push(`滞后 ${edge.lag_days} 天`);
    return parts.join(" · ");
  }

  /** 产业链搜索候选：行业名包含 q（最多 limit 个） */
  function suggestIndustries(nodes, q, limit = 8) {
    const needle = String(q || "").trim();
    if (!needle) return [];
    return (nodes || [])
      .filter((n) => n.id.includes(needle))
      .slice(0, limit)
      .map((n) => n.id);
  }

  /** 产业链默认焦点：第一只持仓所在行业（若在结构里），否则股票数最多的行业 */
  function defaultFocus(nodes, holdingIndustries = []) {
    const list = nodes || [];
    const hold = holdingIndustries.find((ind) => list.some((n) => n.id === ind));
    if (hold) return hold;
    const best = list.slice().sort((a, b) => b.stock_count - a.stock_count || (a.id < b.id ? -1 : 1))[0];
    return best ? best.id : null;
  }

  /** 行情页快讯条：优先最新的重大快讯，没有则最新一条快讯 */
  function pickStrip(majors, items) {
    const newest = (list) => (list || []).reduce((best, x) => (!best || newer(x, best) > 0 ? x : best), null);
    return newest(majors) || newest(items);
  }

  /** 收盘小结“今天的大事”：当日重大快讯，最多 limit 条（时间倒序） */
  function dayMajors(majors, day, limit = 2) {
    return sortNews((majors || []).filter((x) => x.major && x.trading_day === day)).slice(0, limit);
  }

  /**
   * 行情页“事件相关”分段：事件（已取详情）→ 股票 + 标注。
   *   事发：scope=stock 的源股票；scope=industry 的源行业股票
   *   传导：已到达的其余传导行业（含市场级事件的全部节点）
   * events: EventOut[]；details: 与 events 同序的 EventDetailOut（失败为 null）；quotes: QuoteOut[]
   * 返回 {items, notes}：items 按 |change_bp| 降序，最多 limit 只。
   */
  function relatedQuotes(events, details, quotes, limit = 50) {
    const fireCodes = new Set();
    const fireInd = new Set();
    const relayInd = new Set();
    events.forEach((ev, i) => {
      const d = details[i];
      if (!d) return;
      if (ev.scope === "stock" && ev.source_code) fireCodes.add(ev.source_code);
      if (ev.scope === "industry" && ev.source_industry) fireInd.add(ev.source_industry);
      for (const s of d.propagation || []) if (!(ev.scope === "industry" && s.hop === 0)) relayInd.add(s.industry);
    });
    const notes = {};
    const picked = [];
    for (const q of quotes || []) {
      if (fireCodes.has(q.code) || fireInd.has(q.industry)) notes[q.code] = "事发";
      else if (relayInd.has(q.industry)) notes[q.code] = "传导";
      else continue;
      picked.push(q);
    }
    picked.sort((a, b) => Math.abs(b.change_bp || 0) - Math.abs(a.change_bp || 0) || (a.code < b.code ? -1 : 1));
    const items = picked.slice(0, limit);
    const kept = {};
    for (const q of items) kept[q.code] = notes[q.code];
    return { items, notes: kept };
  }

  const MARK_ROLE_TEXT = { source: "事发", propagated: "传导", market: "大盘" };

  /** 快讯页的过滤参数（#/news?filter=…）：合法的 FILTERS id 返回该 id，否则 null */
  function filterFromQuery(value) {
    return typeof value === "string" && FILTERS.some((f) => f.id === value) ? value : null;
  }

  /**
   * K 线事件标记的位置（EventMarkOut[] → 候选 K 线下标）：按 trading_day 对齐 candles（需含 trading_day）。
   * 不在当前 K 线窗口内的标记丢弃；同一根 K 线多条标记保留（按原顺序，服务端已按 tick 降序）。
   */
  function klineMarks(marks, candles) {
    const idx = new Map();
    (candles || []).forEach((c, i) => idx.set(c.trading_day, i));
    return (marks || [])
      .filter((m) => idx.has(m.trading_day))
      .map((m) => ({ ...m, index: idx.get(m.trading_day), roleText: MARK_ROLE_TEXT[m.role] || "" }));
  }

  /** 标记的图例行（最近 limit 条）：{ day, role, roleText, title, event_id, major, kind } */
  function markLegend(marks, limit = 5) {
    return (marks || []).slice(0, limit).map((m) => ({
      event_id: m.event_id,
      trading_day: m.trading_day,
      role: m.role,
      roleText: MARK_ROLE_TEXT[m.role] || "",
      major: !!m.major,
      kind: m.kind,
      title: m.title,
    }));
  }

  /**
   * 行业成分股（产业链抽屉）：quotes 为行情行（QuoteOut），按 industry 过滤，代码升序；limit 之外给出 total。
   * 只用行情字段，不含任何隐藏的强度/滞后信息。
   */
  function constituents(quotes, industry, limit = 40) {
    const list = (quotes || []).filter((q) => q.industry === industry).sort((a, b) => (a.code < b.code ? -1 : a.code > b.code ? 1 : 0));
    return { total: list.length, items: list.slice(0, limit) };
  }

  /**
   * 传导节点对应的产业链边的揭示记录（{ revealed_level, strength, lag_days }）。
   * 边是 from→to 的供需关系，传导方向可能相反（需求冲击从下游传到上游），两个方向都查；查不到返回 {}。
   * rev：{ "from>to": record }（由 GET /intel 的 edges 组成）。
   */
  function revealOf(rev, step) {
    if (!step || step.source) return {};
    return rev[`${step.from}>${step.industry}`] || rev[`${step.industry}>${step.from}`] || {};
  }

  /** 锁提示文案：按已走到的传导边统计未揭示 / 只揭示强度（缺滞后）的数量；没有任何边时保持原文案 */
  function lockText(steps, rev) {
    const hops = (steps || []).filter((s) => !s.source);
    const l0 = hops.filter((s) => !revealOf(rev, s).revealed_level).length;
    const l1 = hops.filter((s) => revealOf(rev, s).revealed_level === 1).length;
    if (!hops.length || l0 === hops.length) return "每条边的强度和滞后天数是隐藏的";
    const parts = [];
    if (l0) parts.push(`${l0} 条边的强度和滞后隐藏`);
    if (l1) parts.push(`${l1} 条边的滞后隐藏`);
    return parts.length ? parts.join("，") : "已走到的边强度和滞后都已揭示";
  }

  /**
   * 事件摘要段（EventDetail 画板）：EventDetailOut 没有 summary 字段，用现有数据拼：
   * 首条快讯标题（与事件标题不同时）；否则说明事发行业与已波及的行业数。无可用信息返回 ""。
   */
  function eventSummary(detail) {
    if (!detail) return "";
    const first = (detail.news || [])[0];
    if (first && first.title && first.title !== detail.title) return first.title;
    const src = detail.source_industry;
    if (!src) return "";
    const n = (detail.propagation || []).filter((s) => s.hop > 0).length;
    return n ? `事发于${src}，已波及 ${n} 个行业` : `事发于${src}`;
  }

  SS.newsModel = {
    revealOf,
    eventSummary,
    lockText,
    PROP_DAYS,
    FEED_LIMIT,
    MAJOR_LIMIT,
    FILTERS,
    KIND_TEXT,
    STAGE_TEXT,
    RUMOR_TEXT,
    RELATION_TEXT,
    clockText,
    toneOf,
    sortNews,
    mergeNews,
    matchesFilter,
    groupByDay,
    newsTags,
    propWindow,
    propSteps,
    chainView,
    revealText,
    suggestIndustries,
    defaultFocus,
    pickStrip,
    dayMajors,
    relatedQuotes,
    filterFromQuery,
    klineMarks,
    markLegend,
    constituents,
    MARK_ROLE_TEXT,
  };
})();
