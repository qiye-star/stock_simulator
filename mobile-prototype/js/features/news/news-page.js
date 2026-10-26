/**
 * 快讯 tab（#/news）：对照 News 画板。
 *   - 顶栏“快讯”+“产业链”按钮；过滤胶囊（全部/重大/我的持仓/政策/传闻）；深链 #/news?filter=rumor 直接选中对应胶囊（非法值忽略）；
 *   - 按交易日分组（今天=强调色）；普通条目两列；重大条目整卡（强调细边框 +“看传导 ›”）；
 *   - 全部/重大走服务端分页；持仓/政策/传闻前端过滤已拉取页，不足 10 条时自动续拉，最多 5 页；
 *   - WS 新快讯（news:update）按过滤条件插入顶部，只插新节点，不重绘已有行；
 *   - 失败：FEATURE_UNAVAILABLE → 整页“即将开放”；EVENTS_DISABLED → “本存档未开启事件模式”+ 新建按钮；其它 → 重试。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.newsModel;

  /** 过滤胶囊是模块级状态：返回行情或其它页再回来时保持 */
  const ui = { filter: "all" };
  const FETCH_LIMIT = 30;
  const ENOUGH = 10; // 前端过滤时至少凑够的条数
  const MAX_PAGES = 5;

  const today = () => SS.store.state.clock.trading_day;
  const dayNo = (d) => SS.fmt.dayNo(d);

  function holdingCtx() {
    const store = SS.store;
    const holds = (store.portfolio().holdings || []).filter((h) => h.quantity > 0);
    const codes = new Set(holds.map((h) => h.code));
    const industries = new Set(holds.map((h) => (store.quote(h.code) || {}).industry).filter(Boolean));
    return { codes, industries };
  }

  function dayHead(day) {
    const isToday = day === today();
    return html`<h2 class="news-day ${isToday ? "news-day--today" : ""}">第 ${dayNo(day)} 个交易日${isToday ? " · 今天" : ""}</h2>`;
  }

  function itemHtml(x, { enter = false } = {}) {
    const tags = M.newsTags(x);
    const head = x.major ? [{ text: "重大", cls: "tag--accent" }] : [];
    const tagHtml = html`<div class="news-item__tags">${[...head, ...tags].map((t) => html`<span class="tag ${t.cls}">${t.text}</span>`)}</div>`;
    const time = html`<span class="news-item__time num t2">${M.clockText(x.clock_minute)}</span>`;
    const href = SS.href(`/event/${x.event_id}`);
    if (x.major)
      return html`<a class="news-item news-item--major ${enter ? "news-item--enter" : ""}" href="${href}" data-news="${x.news_id}">
        ${time}
        <div class="news-item__body">
          ${tagHtml}
          <span class="news-item__title">${x.title}</span>
          <div class="news-item__foot">
            <span class="news-item__slot">${SS.slots.html("news.majorFooter", { event_id: x.event_id })}</span>
            <span class="news-item__more">看传导 ›</span>
          </div>
        </div>
      </a>`;
    return html`<a class="news-item ${enter ? "news-item--enter" : ""}" href="${href}" data-news="${x.news_id}">
      ${time}
      <div class="news-item__body">${tagHtml}<span class="news-item__title">${x.title}</span></div>
    </a>`;
  }

  function groupHtml(g) {
    return html`<section class="news-group" data-day="${g.day}">${dayHead(g.day)}${g.items.map((x) => itemHtml(x))}</section>`;
  }

  function soonPage(view) {
    SS.mount(
      view,
      html`<header class="topbar"><h1 class="topbar__title">快讯</h1></header>${SS.soonCardHtml({
        title: "快讯",
        desc: "开启事件模式的存档会在这里显示公告、新闻、政策与传闻。",
      })}`
    );
  }

  function disabledState(host) {
    SS.mount(
      host,
      html`<div class="empty news-empty">
        <div class="empty__title">本存档未开启事件模式</div>
        <p class="t3 sm">事件模式需要在新建存档时开启</p>
        <button type="button" class="btn btn-sm btn-primary" data-role="new-save">新建事件模式存档</button>
      </div>`
    );
    const btn = SS.$('[data-role="new-save"]', host);
    if (btn) btn.addEventListener("click", () => SS.openSaves && SS.openSaves());
  }

  function render(view, params) {
    const store = SS.store;
    const offs = [];
    // 深链：#/news?filter=…（⑤ 第 6 项）；只认 FILTERS 里的 id，其它值保持上次选择
    const fromUrl = M.filterFromQuery(params && params.query && params.query.filter);
    if (fromUrl) ui.filter = fromUrl;
    let alive = true;
    let st = null; // 当前过滤的加载状态
    let io = null;

    function newState() {
      // mode: ok（正常）| unavailable（后端无此接口，整页“即将开放”）| disabled（存档未开事件模式）
      return { mode: "ok", items: [], seen: new Set(), cursor: null, done: false, loading: false, error: null, token: (st ? st.token : 0) + 1, started: false };
    }

    /** 整页外壳（重置时重绘，保证 filter 与 save 切换一致） */
    function shell() {
      SS.mount(
        view,
        html`<header class="topbar">
            <h1 class="topbar__title">快讯</h1>
            <a class="btn btn-sm btn-ghost news-chain-btn" href="${SS.href("/chain")}">${SS.icon("chain")}<span>产业链</span></a>
          </header>
          <div class="news-filters" data-role="filters" role="tablist" aria-label="快讯过滤">
            ${M.FILTERS.map(
              (f) => html`<button type="button" class="chip ${ui.filter === f.id ? "is-active" : ""}" role="tab" aria-selected="${String(ui.filter === f.id)}" data-filter="${f.id}">${f.label}</button>`
            )}
          </div>
          <div class="news-feed" data-role="feed"></div>
          <div data-role="foot"></div>`
      );
      SS.$('[data-role="filters"]', view).addEventListener("click", (e) => {
        const b = e.target.closest("[data-filter]");
        if (!b || b.dataset.filter === ui.filter) return;
        SS.haptic(5);
        ui.filter = b.dataset.filter;
        SS.$$("[data-filter]", view).forEach((x) => {
          const on = x === b;
          x.classList.toggle("is-active", on);
          x.setAttribute("aria-selected", String(on));
        });
        reload();
      });
      SS.$('[data-role="foot"]', view).addEventListener("click", (e) => {
        if (e.target.closest('[data-role="more"],[data-role="retry"]')) fetchMore();
      });
    }

    function feedEl() {
      return SS.$('[data-role="feed"]', view);
    }
    function footEl() {
      return SS.$('[data-role="foot"]', view);
    }

    /** 完整重绘 feed（分页、过滤切换后） */
    function paint() {
      if (st.mode === "unavailable") return soonPage(view);
      const filters = SS.$('[data-role="filters"]', view);
      if (filters) filters.hidden = st.mode !== "ok"; // 未开启事件模式时不显示过滤胶囊
      if (st.mode === "disabled") {
        disabledState(feedEl());
        return SS.mount(footEl(), "");
      }
      const feed = feedEl();
      if (!st.items.length) {
        if (st.loading || !st.started) SS.mount(feed, html`${Array.from({ length: 5 }).map(() => html`<div class="skeleton news-sk"></div>`)}`);
        else if (st.error) SS.mount(feed, html`<div class="empty"><div class="empty__title">加载失败</div><p class="t3 sm">请检查网络后重试</p></div>`);
        else
          SS.mount(
            feed,
            html`<div class="empty"><div class="empty__title">${ui.filter === "all" ? "还没有快讯" : "没有符合条件的快讯"}</div>
              <p class="t3 sm">${ui.filter === "all" ? "行情推进后会出现新闻、公告、政策和传闻" : "换个过滤条件试试"}</p></div>`
          );
      } else SS.mount(feed, M.groupByDay(st.items).map(groupHtml));
      paintFoot();
    }

    function paintFoot() {
      if (io) io.disconnect();
      if (st.mode !== "ok") return;
      const foot = footEl();
      if (st.error) SS.mount(foot, html`<button type="button" class="load-more" data-role="retry">加载失败，点击重试</button>`);
      else if (st.loading && st.items.length) SS.mount(foot, html`<p class="hint xs t3">加载中…</p>`);
      else if (!st.done) SS.mount(foot, html`<button type="button" class="load-more" data-role="more">加载更多</button>`);
      else SS.mount(foot, "");
      const more = SS.$('[data-role="more"]', foot);
      if (more && "IntersectionObserver" in window) {
        io = new IntersectionObserver((es) => es.some((en) => en.isIntersecting) && fetchMore(), { rootMargin: "320px 0px" });
        io.observe(more);
      }
    }

    /** 取下一批：全部/重大取一页；其它过滤前端筛选，不足 ENOUGH 条且还有下页时续拉，最多 MAX_PAGES 页 */
    async function fetchMore() {
      if (!st || st.loading || st.done) return;
      const tk = st.token;
      const f = ui.filter;
      const serverSide = f === "all" || f === "major";
      const ctx = f === "holding" ? holdingCtx() : null;
      st.loading = true;
      st.error = null;
      st.started = true;
      paintFoot();
      try {
        let pages = 0;
        let got = 0;
        do {
          const r = await store.listNews({ cursor: st.cursor, limit: FETCH_LIMIT, major: f === "major" ? true : undefined });
          if (!alive || tk !== st.token) return;
          const matched = serverSide ? r.items : r.items.filter((x) => M.matchesFilter(x, f, ctx || {}));
          for (const x of matched) {
            if (st.seen.has(x.news_id)) continue;
            st.seen.add(x.news_id);
            st.items.push(x);
          }
          st.items = M.sortNews(st.items);
          st.cursor = r.next_cursor;
          st.done = !r.next_cursor;
          got += matched.length;
          pages++;
        } while (!serverSide && !st.done && got < ENOUGH && pages < MAX_PAGES);
      } catch (err) {
        if (!alive || tk !== st.token) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") st.mode = "unavailable";
        else if (err && err.code === "EVENTS_DISABLED") st.mode = "disabled";
        else st.error = err;
      } finally {
        if (alive && tk === st.token) {
          st.loading = false;
          paint();
        }
      }
    }

    /** 过滤或存档切换：丢弃旧请求，重新拉第一批 */
    function reload() {
      st = newState();
      if (!SS.store.newsEnabled()) st.mode = "disabled";
      paint();
      if (st.mode === "ok") fetchMore();
    }

    // 实时：WS 新快讯按当前过滤插入顶部（只插新节点，保留已有行的滑动与入场状态）
    function onLive({ items }) {
      if (!alive || !st || st.mode !== "ok" || !SS.store.newsEnabled()) return;
      const ctx = ui.filter === "holding" ? holdingCtx() : {};
      // 升序（旧→新）：逐条插到顶部，最新的最终在最上面
      const fresh = M.sortNews(items || []).reverse().filter((x) => !st.seen.has(x.news_id) && M.matchesFilter(x, ui.filter, ctx));
      for (const x of fresh) {
        const wasEmpty = !st.items.length;
        st.seen.add(x.news_id);
        st.items = M.mergeNews(st.items, [x], st.items.length + 1);
        if (wasEmpty) SS.mount(feedEl(), "");
        insertTop(x);
      }
      if (fresh.length) paintFoot();
    }

    function insertTop(x) {
      const feed = feedEl();
      let group = feed.firstElementChild;
      if (!group || !group.classList.contains("news-group") || Number(group.dataset.day) !== x.trading_day) {
        group = SS.el(html`<section class="news-group" data-day="${x.trading_day}">${dayHead(x.trading_day)}</section>`);
        feed.prepend(group);
      }
      const row = SS.el(itemHtml(x, { enter: true }));
      const head = SS.$(".news-day", group);
      head.after(row);
    }

    shell();
    reload();
    offs.push(
      store.on("news:update", onLive),
      store.on("save", () => {
        if (!alive) return;
        shell();
        reload();
      })
    );
    return () => {
      alive = false;
      if (io) io.disconnect();
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.news = { tab: "news", render };
})();
