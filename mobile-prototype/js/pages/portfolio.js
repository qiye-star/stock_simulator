/**
 * 持仓与资产（#/portfolio）—— 对应 GET /saves/{id}/portfolio
 *   - 总资产 CountUp、累计/今日盈亏；
 *   - 资产曲线（强调色单线，7 日 / 30 日 / 全部），按住查看某日读数；
 *   - 仓位占比条（持仓 vs 现金）；
 *   - 持仓卡片（SpotlightCard）：现价/成本/浮盈，卡内直接「加仓 / 卖出」，点卡片进详情。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html, raw } = SS;
  let range = "30";

  function render(view) {
    const store = SS.store;
    const fmt = SS.fmt;
    const hide = () => SS.prefs && SS.prefs.hide;
    const MASK = "****";

    SS.mount(
      view,
      html`<header class="topbar">
          <h1 class="topbar__title">持仓</h1>
          <div data-role="clock"></div>
        </header>

        <section class="hero">
          <div class="t2 sm">总资产（元）</div>
          <div class="hero__total num" data-role="equity"></div>
          <div class="hero__sub">
            <span class="t3 xs">累计</span><span class="num sm" data-role="net"></span>
            <span class="t3 xs">今日</span><span class="num sm" data-role="today"></span>
          </div>
        </section>

        <section class="card chart-card">
          <div class="chart-card__head">
            <div class="seg seg--inline" data-role="range">
              <span class="seg__thumb" aria-hidden="true"></span>
              <button type="button" data-value="7" class="${range === "7" ? "is-active" : ""}">7日</button>
              <button type="button" data-value="30" class="${range === "30" ? "is-active" : ""}">30日</button>
              <button type="button" data-value="all" class="${range === "all" ? "is-active" : ""}">全部</button>
            </div>
            <div class="chart-readout xs num" data-role="readout"></div>
          </div>
          <div class="chart chart--short" data-role="curve"></div>
        </section>

        <section class="alloc" data-role="alloc"></section>

        <div class="section-head">
          <h2 class="section-title">持仓 <span class="t3 num" data-role="count"></span></h2>
          <span class="xs t3">按住卡片有光晕 · 点按进入详情</span>
        </div>
        <div class="holding-list" data-role="list"></div>`
    );

    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    SS.segmented($("range"), (v) => {
      range = v;
      paintCurve();
    });

    function paintSummary(first) {
      const p = store.portfolio();
      SS.mount($("clock"), SS.clockChip(store.state.clock));
      const eq = $("equity");
      if (hide()) eq.textContent = MASK;
      else SS.countUp(eq, p.equity_cents, { format: (v) => fmt.yuan(v), duration: first ? 1300 : 600, from: first ? p.initial_fund_cents : undefined });
      const netBp = Math.round((p.net_pnl_cents / p.initial_fund_cents) * 10000);
      $("net").className = `num sm ${fmt.trend(p.net_pnl_cents)}`;
      $("net").textContent = hide() ? MASK : `${fmt.yuan(p.net_pnl_cents, { sign: true })} ${fmt.pctBp(netBp)}`;
      $("today").className = `num sm ${fmt.trend(p._today_pnl_cents)}`;
      $("today").textContent = hide() ? MASK : fmt.yuan(p._today_pnl_cents, { sign: true });

      const ratio = p.equity_cents ? p.market_value_cents / p.equity_cents : 0;
      SS.mount(
        $("alloc"),
        html`<div class="alloc__bar"><i style="width:${(ratio * 100).toFixed(1)}%"></i></div>
          <div class="alloc__legend xs">
            <span><i class="dot dot--accent"></i>持仓 <b class="num">${hide() ? MASK : fmt.yuanCompact(p.market_value_cents)}</b> <span class="t3 num">${(ratio * 100).toFixed(1)}%</span></span>
            <span><i class="dot"></i>现金 <b class="num">${hide() ? MASK : fmt.yuanCompact(p.cash_cents)}</b> <span class="t3 num">${((1 - ratio) * 100).toFixed(1)}%</span></span>
          </div>`
      );
    }

    function paintCurve() {
      const all = store.state.equity_history;
      const data = range === "all" ? all : all.slice(-Number(range));
      const vals = data.map((d) => d.equity_cents);
      const c = SS.chart.area(vals, 343, 120);
      const host = $("curve");
      const fresh = host.cloneNode(false);
      host.replaceWith(fresh);
      SS.mount(fresh, html`<div class="chart__plot">${raw(c.svg)}</div>`);
      const first = vals[0];
      const def = () => {
        const d = vals[vals.length - 1] - first;
        SS.mount(
          $("readout"),
          html`<span class="t3">区间</span><span class="${fmt.trend(d)}">${hide() ? MASK : fmt.yuanCompact(d, { sign: true })} ${fmt.pctBp(Math.round((d / first) * 10000))}</span>`
        );
      };
      SS.chart.crosshair(SS.$(".chart__plot", fresh), {
        count: vals.length,
        onMove(i) {
          if (i == null) return def();
          SS.mount($("readout"), html`<span class="t3">${data[i].kind === "initial" ? "起点" : `D${data[i].trading_day}`}</span><span>${hide() ? MASK : fmt.yuan(vals[i])}</span>`);
        },
      });
      def();
    }

    function card(h) {
      const tr = fmt.trend(h.pnl_cents);
      const frozen = h.quantity - h.sellable_quantity;
      return html`<article class="spotlight-card holding animated-list__item" data-code="${h.code}" tabindex="0">
        <div class="holding__top">
          <div>
            <div class="holding__name">${h.name}</div>
            <div class="xs t3 num">${h.code} · ${fmt.qty(h.quantity)} 股${frozen ? html` · <span class="tag">T+1 冻结 ${fmt.qty(frozen)}</span>` : ""}</div>
          </div>
          <div class="holding__mv">
            <div class="num">${hide() ? MASK : fmt.yuan(h.market_value_cents)}</div>
            <div class="xs t3">市值</div>
          </div>
        </div>
        <dl class="holding__grid">
          <div><dt>现价</dt><dd class="num ${fmt.trend(h.market_price_cents - SS.store.quote(h.code).prev_close_cents)}">${fmt.price(h.market_price_cents)}</dd></div>
          <div><dt>成本</dt><dd class="num">${fmt.price(h.avg_price_cents)}</dd></div>
          <div><dt>浮动盈亏</dt><dd class="num ${tr}">${hide() ? MASK : fmt.yuanCompact(h.pnl_cents, { sign: true })}<br /><small>${fmt.pctBp(h.pnl_bp)}</small></dd></div>
        </dl>
        <div class="holding__actions">
          <button type="button" class="btn btn-sm" data-action="buy">${SS.icon("plus")}加仓</button>
          <button type="button" class="btn btn-sm" data-action="sell" ${h.sellable_quantity ? "" : "disabled"}>卖出</button>
        </div>
      </article>`;
    }

    function paintList() {
      const p = store.portfolio();
      $("count").textContent = p.holdings.length;
      const list = $("list");
      if (!p.holdings.length) {
        SS.mount(
          list,
          html`<div class="empty">
            <div class="empty__title">${SS.blurText("空仓观望中")}</div>
            <p class="t3 sm">去行情里挑一只，左滑即可买入</p>
            <a class="btn btn-sm btn-primary" href="#/market">去看行情</a>
          </div>`
        );
        return;
      }
      SS.mount(list, html`<div class="animated-list">${p.holdings.sort((a, b) => b.market_value_cents - a.market_value_cents).map(card)}</div>`);
      SS.animatedList(list);
    }

    $("list").addEventListener("click", (e) => {
      const c = e.target.closest(".holding");
      if (!c) return;
      const btn = e.target.closest("[data-action]");
      if (btn) {
        SS.haptic();
        SS.orderSheet.open({ code: c.dataset.code, side: btn.dataset.action });
      } else SS.router.navigate(`/stock/${c.dataset.code}`);
    });
    $("list").addEventListener("keydown", (e) => {
      const c = e.target.closest(".holding");
      if (c && e.key === "Enter" && e.target === c) SS.router.navigate(`/stock/${c.dataset.code}`);
    });

    /** 实时刷新：只改数字，不重建卡片（保持光晕与入场状态） */
    function patchCards() {
      const p = store.portfolio();
      const codes = SS.$$(".holding", view).map((el) => el.dataset.code);
      if (codes.length !== p.holdings.length || p.holdings.some((h) => !codes.includes(h.code))) return paintList();
      for (const h of p.holdings) {
        const el = SS.$(`.holding[data-code="${h.code}"]`, view);
        const next = SS.el(card(h));
        SS.$(".holding__mv", el).replaceWith(SS.$(".holding__mv", next));
        SS.$(".holding__grid", el).replaceWith(SS.$(".holding__grid", next));
        SS.$(".holding__top", el).replaceWith(SS.$(".holding__top", next));
      }
    }

    paintSummary(true);
    paintCurve();
    paintList();

    const offs = [
      store.on("tick", () => {
        paintSummary(false);
        patchCards();
      }),
      store.on("order", () => {
        paintSummary(false);
        paintList();
      }),
    ];
    return () => offs.forEach((f) => f());
  }

  SS.pages = SS.pages || {};
  SS.pages.portfolio = { tab: "portfolio", render };
})();
