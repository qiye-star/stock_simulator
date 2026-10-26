/**
 * 产业链（#/chain?focus=<行业>）：对照 Chain 画板，只公开结构（谁连着谁）。
 *   - 焦点行业：query.focus，缺省取第一只持仓的行业，再缺省取股票数最多的行业；
 *   - 上游 = 指向焦点的供应/需求边，下游 = 焦点指向的供应/需求边，同题材/替代 单列；
 *   - 切换焦点用 SS.router.replace（不刷历史，后退不会在产业链内部循环）；
 *   - 未揭示的边显示锁，右侧 chain.edgeAction 槽（⑥ 情报卡入口）；已揭示的显示强度/滞后；
 *   - 结构对关闭事件模式的存档同样可用（01 §1.6）；
 *   - 点中心行业打开行业抽屉（⑤ 第 5 项）：成分股（行情，龙头有标记）、关联（只显示谁连着谁，不含强度/滞后）、最近快讯（listNews industry）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.newsModel;

  function holdingIndustries(store) {
    const holds = (store.portfolio().holdings || []).filter((h) => h.quantity > 0);
    return holds.map((h) => (store.quote(h.code) || {}).industry).filter(Boolean);
  }

  function render(view, params) {
    const store = SS.store;
    const offs = [];
    let alive = true;
    let chain = null;
    let focus = (params.query && params.query.focus) || null;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">产业链</h1>
        </header>
        <div class="chain-body" data-role="body"></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());
    // 委托：行与候选的点击（只绑一次，paint 只重绘内容）
    body().addEventListener("click", (e) => {
      if (e.target.closest("[data-intel-edge]")) return; // 情报按钮由预测卡功能委托处理（⑥）
      if (e.target.closest('[data-role="industry"]')) return openIndustry(focus);
      const b = e.target.closest("[data-focus]");
      if (!b) return;
      if (b.classList.contains("chain-suggest__item")) return pickSuggest(b.dataset.focus);
      setFocus(b.dataset.focus);
    });

    function notice(title, desc) {
      SS.mount(body(), html`<div class="empty"><div class="empty__title">${title}</div>${desc ? html`<p class="t3 sm">${desc}</p>` : ""}</div>`);
    }

    async function load() {
      SS.mount(body(), html`<div class="skeleton" style="height:44px;border-radius:12px;margin-top:8px"></div><div class="skeleton" style="height:160px;border-radius:var(--r-lg);margin-top:16px"></div>`);
      try {
        chain = await store.loadSupplyChain();
        if (!alive) return;
        const nodes = chain.nodes || [];
        if (!nodes.length) return notice("暂无产业链数据");
        const valid = focus && nodes.some((n) => n.id === focus);
        if (!valid) focus = M.defaultFocus(nodes, holdingIndustries(store));
        paint();
      } catch (err) {
        if (!alive) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") SS.mount(body(), SS.soonCardHtml({ title: "产业链", desc: "产业链暂未开放。" }));
        else {
          SS.mount(body(), html`<div class="empty"><div class="empty__title">加载失败</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`);
          SS.$('[data-role="retry"]', body()).addEventListener("click", load);
        }
      }
    }

    /**
     * 行业抽屉：SS.sheet 打开，内容分三块。成分股与快讯异步加载（失败时整块隐藏，不打扰抽屉）。
     * 关联只来自 chain 的 edges 结构（谁连着谁）；未揭示的强度/滞后不在这里出现。
     */
    function openIndustry(ind) {
      const node = (chain.nodes || []).find((n) => n.id === ind);
      if (!node) return;
      SS.haptic(5);
      const rel = M.chainView(chain, ind);
      const leaders = new Set(node.leaders || []);
      const relGroup = (title, list) =>
        list.length
          ? html`<h3 class="ind-sheet__sub">${title}</h3>${list.map(
              (it) => html`<button type="button" class="ind-rel" data-sheet-focus="${it.industry}"><span>${it.industry}</span><span class="t2 xs">${M.RELATION_TEXT[it.edge.relation] || ""}</span>${SS.icon("chevron", "ind-rel__chev")}</button>`
            )}`
          : "";
      return SS.sheet.open({
        title: ind,
        className: "chain-sheet",
        render(el, api) {
          SS.mount(
            el,
            html`<div class="ind-sheet">
              <p class="t2 sm">${node.stock_count} 只股票${leaders.size ? ` · 龙头 ${leaders.size} 只` : ""}</p>
              <section class="ind-sheet__sec">
                <h2 class="ind-sheet__title">成分股</h2>
                <div data-role="stocks"><div class="skeleton" style="height:44px;margin-top:10px"></div></div>
              </section>
              <section class="ind-sheet__sec">
                <h2 class="ind-sheet__title">关联</h2>
                <p class="t3 xs">只显示谁连着谁。强度与滞后需要情报卡揭示。</p>
                ${relGroup("上游 · 它从哪里来", rel.upstream)}
                ${relGroup("下游 · 它卖给谁", rel.downstream)}
                ${relGroup("同题材 / 替代", rel.theme)}
                ${rel.upstream.length + rel.downstream.length + rel.theme.length ? "" : html`<p class="t3 sm">暂无关联</p>`}
              </section>
              <section class="ind-sheet__sec" data-role="news-sec" hidden>
                <h2 class="ind-sheet__title">最近快讯</h2>
                <div data-role="news"></div>
              </section>
            </div>`
          );
          el.addEventListener("click", (e) => {
            const f = e.target.closest("[data-sheet-focus]");
            if (f) {
              api.close();
              return setFocus(f.dataset.sheetFocus);
            }
            if (e.target.closest("a[href]")) api.close();
          });
          store
            .loadAllQuotes()
            .then((quotes) => {
              const box = SS.$('[data-role="stocks"]', el);
              if (!box) return;
              const c = M.constituents(quotes, ind, 40);
              if (!c.items.length) return SS.mount(box, html`<p class="t3 sm">行情里没有这个行业的股票</p>`);
              SS.mount(
                box,
                html`${c.items.map(
                  (q) => html`<a class="ind-row" href="${SS.href(`/stock/${q.code}`)}">
                    <span class="ind-row__name">${q.name}${leaders.has(q.code) ? html` <span class="tag">龙头</span>` : ""}</span>
                    <span class="t2 xs num">${q.code}</span>
                    <span class="num ind-row__px">${SS.fmt.price(q.price_cents)}</span>
                    <span class="num ind-row__chg ${SS.fmt.trend(q.change_bp)}">${SS.fmt.pctBp(q.change_bp)}</span>
                  </a>`
                )}
                ${c.total > c.items.length ? html`<p class="t3 xs">共 ${c.total} 只，显示前 ${c.items.length} 只</p>` : ""}`
              );
            })
            .catch(() => {
              const box = SS.$('[data-role="stocks"]', el);
              if (box) SS.mount(box, html`<p class="t3 sm">行情暂不可用</p>`);
            });
          store
            .listNews({ industry: ind, limit: 5 })
            .then((r) => {
              const sec = SS.$('[data-role="news-sec"]', el);
              if (!sec || !r.items.length) return;
              sec.hidden = false;
              SS.mount(
                SS.$('[data-role="news"]', el),
                r.items.map(
                  (x) => html`<div class="later-row">
                    <span class="num t2 xs">${SS.fmt.dayNo(x.trading_day)} 日 ${M.clockText(x.clock_minute)}</span>
                    <a class="later-row__body later-row__link" href="${SS.href(`/event/${x.event_id}`)}">${x.major ? html`<span class="tag tag--accent">重大</span> ` : ""}${x.title}</a>
                  </div>`
                )
              );
            })
            .catch(() => {}); // 快讯接口缺失或失败：整块隐藏
        },
      });
    }

    /** 切换焦点：替换历史项，重绘 */
    function setFocus(ind) {
      if (!ind || ind === focus) return;
      SS.haptic(5);
      focus = ind;
      SS.router.replace(`/chain?focus=${encodeURIComponent(ind)}`); // router.replace 接收不带 # 的路径
      paint();
    }

    function rowHtml(item, side) {
      const e = item.edge;
      const rel = M.RELATION_TEXT[e.relation] || e.relation;
      const reveal = M.revealText(e);
      // 未揭示 / 只揭示强度的边：右侧附情报按钮（⑥ chain.edgeAction 槽，由预测卡功能提供）
      const intel = (e.revealed_level || 0) < 2 ? SS.slots.html("chain.edgeAction", { edge: e }) : "";
      const right = reveal
        ? html`<span class="chain-row__rel">${rel} · ${reveal}</span>${intel}`
        : html`<span class="chain-row__rel chain-row__lock">${rel}${SS.icon("lock", "chain-row__icon")}<span class="sr-only">未揭示</span></span>${intel}`;
      return html`<button type="button" class="chain-row" data-focus="${item.industry}" data-side="${side}">
        <span class="chain-row__name">${item.industry}</span>${right}
      </button>`;
    }

    /** 候选点选：收起候选并切换焦点（输入框同步为行业名） */
    function pickSuggest(ind) {
      const q = SS.$('[data-role="q"]', body());
      const sug = SS.$('[data-role="suggest"]', body());
      if (sug) sug.hidden = true;
      if (q) q.value = ind;
      setFocus(ind);
    }

    function paint() {
      const view2 = M.chainView(chain, focus);
      const node = view2.node;
      const nodes = chain.nodes || [];
      const countText = `${nodes.length} 个行业`;
      SS.mount(
        body(),
        html`<label class="chain-search">
            ${SS.icon("search", "chain-search__icon")}
            <input class="chain-search__input" type="search" data-role="q" value="${focus || ""}" placeholder="搜索行业" aria-label="搜索行业" autocomplete="off" enterkeyhint="search" />
            <span class="t2 xs chain-search__count">${countText}</span>
          </label>
          <div class="chain-suggest" data-role="suggest" hidden></div>
          <section class="chain-col">
            <h2 class="chain-col__head">上游 · 它从哪里来</h2>
            ${view2.upstream.length ? view2.upstream.map((it) => rowHtml(it, "up")) : html`<p class="t3 sm chain-empty">暂无</p>`}
          </section>
          <div class="chain-center" aria-current="true">
            <span class="chain-center__line" aria-hidden="true"></span>
            <button type="button" class="chain-center__node" data-role="industry" ${node ? "" : "disabled"} aria-label="${node ? `查看${node.id}行业详情` : "行业"}">
              <span class="chain-center__name">${node ? node.id : "—"}</span>
              <span class="t2 xs num">${node ? `${node.stock_count} 只股票 ›` : ""}</span>
            </button>
            <span class="chain-center__line" aria-hidden="true"></span>
          </div>
          <section class="chain-col">
            <h2 class="chain-col__head">下游 · 它卖给谁</h2>
            ${view2.downstream.length ? view2.downstream.map((it) => rowHtml(it, "down")) : html`<p class="t3 sm chain-empty">暂无</p>`}
          </section>
          ${view2.theme.length
            ? html`<section class="chain-col">
                <h2 class="chain-col__head">同题材 / 替代</h2>
                <div class="chain-chips">${view2.theme.map((it) => html`<button type="button" class="chain-chip" data-focus="${it.industry}"><span>${it.industry}</span><span class="t2 xs">${M.RELATION_TEXT[it.edge.relation] || ""}</span></button>`)}</div>
              </section>`
            : ""}
          <section class="card lock-card">
            ${SS.icon("lock", "lock-card__icon")}
            <p class="t2 sm">这里只告诉你谁连着谁。冲击有多大、隔几天传到，要靠你自己判断，或者用积分买情报卡揭示。</p>
          </section>`
      );
      const q = SS.$('[data-role="q"]', body());
      const sug = SS.$('[data-role="suggest"]', body());
      q.addEventListener("input", () => {
        const list = M.suggestIndustries(nodes, q.value);
        sug.hidden = !list.length;
        SS.mount(sug, list.map((ind) => html`<button type="button" class="chain-suggest__item" data-focus="${ind}">${ind}</button>`));
      });
      q.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const first = M.suggestIndustries(nodes, q.value, 1)[0];
        if (first) pickSuggest(first);
      });
    }

    load();
    offs.push(store.on("save", () => alive && load()));
    offs.push(store.on("intel", () => alive && load())); // 情报卡购买后刷新揭示状态（⑥）
    return () => {
      alive = false;
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.chain = { tab: null, render };
})();
