/**
 * 快讯 / 事件 / 产业链（⑤ A 事件行情）的注册入口。
 *   routes：/news（快讯 tab，支持 ?filter=all|major|holding|policy|rumor）、/event/:id（事件详情）、/chain（产业链）
 *   挂载点：market.banner（行情页快讯条，order 20）、closeSummary.extra（收盘小结“今天的大事”）、stock.extra（个股页“相关事件”）、
 *           stock.kline（个股日 K 下方的事件标记，⑤ 第 4 项）
 *   行情分段：SS.marketLists “事件相关”（仅事件模式存档显示）
 *   WS：订阅 ws:news → 合并缓存、广播 news:update、重大快讯弹 toast
 *   mock 模式：按 SS.mockFeatures.news.queue 每隔一段时间推送一条（模拟 WS news）
 *
 * 事件模式关闭的存档：不发任何快讯请求（快讯 tab 显示“本存档未开启事件模式”，行情页不显示快讯条与分段）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.newsModel;

  /** 并发受限的 map（真实模式逐个拉事件详情，避免一次性打满） */
  async function mapLimit(list, n, fn) {
    const out = new Array(list.length);
    let i = 0;
    await Promise.all(
      Array.from({ length: Math.min(n, list.length) }, async () => {
        while (i < list.length) {
          const k = i++;
          out[k] = await fn(list[k], k);
        }
      })
    );
    return out;
  }

  /** 首屏缓存：最近快讯与重大快讯；完成后广播一次 news:update（items 为空），让订阅方刷新 */
  function ensure() {
    const store = SS.store;
    if (!store.newsEnabled()) return;
    store
      .ensureNews()
      .then(() => store.emitLocal("news:update", { items: [], loaded: true }))
      .catch(() => {}); // 失败由各页面自行显示（FEATURE_UNAVAILABLE / 重试）
  }

  function onWs(msg) {
    const store = SS.store;
    if (!store.newsEnabled()) return;
    const st = store.state.news;
    const known = new Set(st.items.map((x) => x.news_id));
    const fresh = (msg.items || []).filter((x) => !known.has(x.news_id));
    st.items = M.mergeNews(st.items, fresh);
    st.majors = M.mergeNews(st.majors, fresh.filter((x) => x.major), M.MAJOR_LIMIT);
    if (fresh.length) store.emitLocal("news:update", { items: fresh, truncated: !!msg.truncated });
    for (const x of fresh) if (x.major) SS.toast(`重大：${x.title}`, { icon: null, duration: 2600 });
    // 一帧推送条数超限（truncated）：缺的部分重新拉首屏
    if (msg.truncated) store.ensureNews({ force: true }).catch(() => {});
  }

  // ---------- 行情页快讯条（market.banner） ----------
  function stripHtml(it) {
    return html`<a class="news-strip" href="${SS.href(`/event/${it.event_id}`)}">
      ${it.major ? html`<span class="tag tag--accent">重大</span>` : ""}
      <span class="num t2 xs">${M.clockText(it.clock_minute)}</span>
      <span class="news-strip__title">${it.title}</span>
      <span class="t2 news-strip__more" aria-hidden="true">›</span>
    </a>`;
  }

  function mountStrip(host) {
    const store = SS.store;
    const draw = () => {
      const it = store.newsEnabled() ? M.pickStrip(store.majorNews(), store.newsFeed()) : null;
      host.hidden = !it;
      SS.mount(host, it ? stripHtml(it) : "");
    };
    draw();
    return store.on("news:update", draw);
  }

  // ---------- 收盘小结：今天的大事（closeSummary.extra） ----------
  function mountDayMajors(host, { trading_day: day }) {
    const store = SS.store;
    if (!store.newsEnabled()) return;
    const list = M.dayMajors(store.majorNews(), day, 2);
    if (!list.length) return; // 空则卡片整体隐藏（close-summary 据此判断）
    SS.mount(
      host,
      html`${list.map(
        (x) => html`<a class="cs-event" href="${SS.href(`/event/${x.event_id}`)}">
          <span class="tag tag--accent">重大</span>
          <span class="cs-event__title">${x.title}</span>
          <span class="t2" aria-hidden="true">›</span>
        </a>`
      )}`
    );
  }

  // ---------- 个股日 K 的事件标记（stock.kline 槽，事件模式存档） ----------
  // 按 (代码, 交易日) 缓存 event-marks；快讯 WS 与存档切换时清空。失败不缓存，下次绘制再取。
  const markCache = new Map();
  function marksFor(code, day) {
    const key = `${code}|${day}`;
    if (!markCache.has(key)) {
      const p = SS.store.loadEventMarks(code, 60);
      markCache.set(key, p);
      p.catch(() => markCache.delete(key));
    }
    return markCache.get(key);
  }

  /** candles 为日 K 的 CandleOut[]（含 trading_day）；标记落在窗口外的丢弃；没有标记时不占位 */
  function mountKlineMarks(host, { code, candles }) {
    const store = SS.store;
    if (!store.newsEnabled() || !candles || !candles.length) return;
    const n = candles.length;
    marksFor(code, store.state.clock.trading_day)
      .then((r) => {
        if (!host.isConnected) return;
        const slots = M.klineMarks(r.items, candles);
        if (!slots.length) return SS.mount(host, "");
        const legend = M.markLegend(slots, 5);
        SS.mount(
          host,
          html`<div class="kmarks" aria-label="事件标记">
            <div class="kmarks__track">
              ${slots.map((m) => html`<i class="kmark kmark--${m.role}" style="left:${(((m.index + 0.5) / n) * 100).toFixed(2)}%" title="${m.roleText} · ${m.title}"></i>`)}
            </div>
            <ul class="kmarks__list">
              ${legend.map(
                (x) => html`<li><a class="kmarks__item" href="${SS.href(`/event/${x.event_id}`)}">
                  <span class="kmark kmark--${x.role} kmark--inline" aria-hidden="true"></span>
                  <span class="t2 xs num">${SS.fmt.dayNo(x.trading_day)} 日</span>
                  <span class="tag">${x.roleText}</span>
                  ${x.major ? html`<span class="tag tag--accent">重大</span>` : ""}
                  <span class="kmarks__title">${x.title}</span>
                  <span class="t2" aria-hidden="true">›</span>
                </a></li>`
              )}
            </ul>
          </div>`
        );
      })
      .catch(() => host.isConnected && SS.mount(host, "")); // 接口缺失或失败：静默不显示
  }

  // ---------- 行情分段：事件相关（marketLists） ----------
  async function loadRelated() {
    const store = SS.store;
    const [active, expected] = await Promise.all([
      store.listEvents({ phase: "active", limit: 10 }),
      store.listEvents({ phase: "expected", limit: 10 }),
    ]);
    const events = [...active.items, ...expected.items];
    const details = await mapLimit(events, 3, (e) => store.loadEvent(e.event_id).catch(() => null));
    const quotes = await store.loadAllQuotes();
    return M.relatedQuotes(events, details, quotes, 50);
  }

  // ---------- 个股页底部：相关事件（stock.extra，事件模式存档） ----------
  function mountStockEvents(host, { code }) {
    const store = SS.store;
    if (!store.newsEnabled()) return;
    let seq = 0;
    SS.mount(host, html`<section class="card stock-events"><h3 class="card__title">相关事件</h3><div data-role="list"></div></section>`);
    const list = () => SS.$('[data-role="list"]', host);
    async function load() {
      const my = ++seq;
      try {
        const r = await store.listNews({ code, limit: 5 });
        if (my !== seq) return;
        if (!r.items.length) return SS.mount(list(), html`<p class="t3 sm">近期没有相关事件</p>`);
        SS.mount(
          list(),
          r.items.map(
            (x) => html`<div class="later-row">
              <span class="num t2 xs">${SS.fmt.dayNo(x.trading_day)} 日 ${M.clockText(x.clock_minute)}</span>
              <a class="later-row__body later-row__link" href="${SS.href(`/event/${x.event_id}`)}">${x.major ? html`<span class="tag tag--accent">重大</span> ` : ""}${x.title}</a>
            </div>`
          )
        );
      } catch (err) {
        if (my !== seq) return;
        host.hidden = true; // 接口缺失或失败：整块隐藏，不打扰个股页
        SS.mount(host, "");
      }
    }
    load();
    return store.on("news:update", ({ items }) => (items || []).some((x) => x.code === code) && load());
  }

  // ---------- mock 推送 ----------
  function startMockPush() {
    const store = SS.store;
    const data = SS.mockFeatures.news;
    const queue = data.queue.slice();
    const find = (id) => data.events.flatMap((e) => e.news).find((n) => n.news_id === id);
    const pushOne = () => {
      const id = queue.shift();
      const item = id && find(id);
      if (!item) return;
      item._queued = false;
      const { _queued, ...pubItem } = item;
      store.emitLocal("ws:news", { t: "news", trading_tick: pubItem.trading_tick, items: [pubItem], truncated: false });
      if (queue.length) setTimeout(pushOne, 18000);
    };
    setTimeout(pushOne, 9000);
  }

  SS.features = SS.features || {};
  SS.features.news = {
    routes: [
      ["/news", SS.pages.news],
      ["/event/:id", SS.pages.event],
      ["/chain", SS.pages.chain],
    ],
    init() {
      const store = SS.store;
      SS.slots.register("market.banner", { id: "news-strip", order: 20, mount: mountStrip });
      SS.slots.register("closeSummary.extra", { id: "news-major", order: 10, mount: mountDayMajors });
      SS.slots.register("stock.extra", { id: "related-events", order: 10, mount: mountStockEvents });
      SS.slots.register("stock.kline", { id: "event-marks", order: 10, mount: mountKlineMarks });
      SS.marketLists.register({
        value: "event",
        label: "事件相关",
        order: 30,
        visible: () => store.newsEnabled(),
        load: loadRelated,
        empty: "近期没有进行中的事件",
      });
      store.on("ws:news", (msg) => {
        markCache.clear(); // 新快讯可能新增标记
        onWs(msg);
      });
      store.on("save", () => {
        store.resetNews();
        markCache.clear();
        ensure();
      });
      ensure();
      if (SS.isMock) startMockPush();
    },
  };
})();
