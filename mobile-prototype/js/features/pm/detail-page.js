/**
 * 合约详情（#/pm/:id，SS.pages.pmDetail）—— 对照 Contract 画板：
 *   顶栏返回 + “预测市场”；问题 h1 + 关闭说明与人数；选项行（概率条，选中 accent）；
 *   单选项概率曲线（开市以来，accent 线 + 浅面积）；买卖面板（SS.pmTrade，滑点保护/持仓）。
 * 数据：loadPredictionMarket（详情）+ loadPredictionHistory（曲线）；页面存活期间 watchPredictions + subscribePrediction(id)。
 *   tick：只改选项百分比、条宽、曲线末点，并刷新报价；status 变化或 resolved → 整体重拉。
 *   离开页面：取消订阅与 WS 引用（unwatchPredictions）。
 * FEATURE_UNAVAILABLE → “即将开放”；PM_NOT_FOUND → 空态。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.pages = SS.pages || {};
  const { html } = SS;
  const store = () => SS.store;
  const M = () => SS.pmModel;
  const U = () => SS.pmUi;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function render(view, params) {
    const id = params.id;
    let alive = true;
    let market = null;
    let hist = [];
    let outcome = null;
    let shell = false;
    let panel = null;
    let seq = 0;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">预测市场</h1>
        </header>
        <div class="pm-page" data-role="page"><div class="skeleton" style="height:120px;border-radius:16px;margin-top:8px"></div></div>`
    );
    const page = SS.$('[data-role="page"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    const curvePoints = () => hist.map((h) => (Number((h.prices_ppm || [])[outcome]) || 0) / 1e6);
    const curveLabel = () => `“${M().outcomeLabels(market)[outcome] || ""}” 的全服概率，开市以来`;
    const metaText = () => `${M().closeText(market)} · ${market.traders} 人参与`;

    /** 首次：整页骨架 + 买卖面板（之后只刷新内容，面板实例保留份数与方向） */
    function drawShell() {
      const labels = M().outcomeLabels(market);
      SS.mount(
        page,
        html`<h1 class="pm-title">${M().questionText(market)}</h1>
          <p class="t2 xs pm-meta" data-role="meta">${metaText()}</p>
          ${U().optsHtml(market, outcome)}
          <section class="card pm-curve-card">
            <div class="pm-curve-card__head"><span data-role="curve-title">${curveLabel()}</span></div>
            <div class="pm-curve-wrap" data-role="curve">${U().curveHtml(curvePoints(), curveLabel())}</div>
          </section>
          <div data-role="trade"></div>`
      );
      // 选项用事件委托：整块 opts 替换后仍有效
      page.addEventListener("click", (e) => {
        const b = e.target.closest(".pm-opt");
        if (b && page.contains(b)) selectOutcome(Number(b.dataset.idx));
      });
      panel = SS.pmTrade.mount(SS.$('[data-role="trade"]', page), { onDone: () => load() });
      panel.render(market, outcome);
      shell = true;
    }

    function refresh() {
      SS.$('[data-role="meta"]', page).textContent = metaText();
      const old = SS.$('[data-role="opts"]', page);
      if (old) old.replaceWith(SS.el(U().optsHtml(market, outcome)));
      SS.mount(SS.$('[data-role="curve"]', page), U().curveHtml(curvePoints(), curveLabel()));
      SS.$('[data-role="curve-title"]', page).textContent = curveLabel();
      panel.render(market, outcome);
    }

    /** 推送：就地改数字与曲线 path，不重建面板 */
    function patchLive() {
      const opts = SS.$('[data-role="opts"]', page);
      if (!opts) return;
      SS.$$(".pm-opt", opts).forEach((b, i) => U().setOptPct(b, market.outcomes[i].price_ppm));
      const line = SS.$(".pm-curve__line", page);
      const area = SS.$(".pm-curve__area", page);
      const dot = SS.$(".pm-curve__dot", page);
      const c = M().curvePaths(curvePoints(), 320, 90, 6);
      if (!line || !area || !c.last) return refresh();
      line.setAttribute("d", c.line);
      area.setAttribute("d", c.area);
      if (dot) {
        dot.setAttribute("cx", c.last.x);
        dot.setAttribute("cy", c.last.y);
      }
    }

    function selectOutcome(i) {
      if (!market || i === outcome || i < 0 || i >= market.outcomes.length) return;
      outcome = i;
      SS.$$(".pm-opt", page).forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.idx) === i ? "true" : "false"));
      SS.$('[data-role="curve-title"]', page).textContent = curveLabel();
      SS.mount(SS.$('[data-role="curve"]', page), U().curveHtml(curvePoints(), curveLabel()));
      panel.setOutcome(i);
    }

    async function load() {
      const my = ++seq;
      try {
        const [d, h] = await Promise.all([store().loadPredictionMarket(id), store().loadPredictionHistory(id)]);
        if (!alive || my !== seq) return;
        market = d;
        hist = h.items.slice();
        if (outcome == null) outcome = M().leadingIndex(market.outcomes.map((o) => o.price_ppm));
        outcome = clamp(outcome, 0, market.outcomes.length - 1);
        if (!shell) drawShell();
        else refresh();
      } catch (err) {
        if (!alive || my !== seq) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") return SS.soonCard(page, { title: "预测市场", desc: "用积分买卖，价格就是全服的判断，功能即将开放。" });
        if (err && err.code === "PM_NOT_FOUND") return SS.mount(page, html`<div class="empty" style="padding-top:20vh"><div class="empty__title">${store().errorText(err.code)}</div></div>`);
        store().notifyError(err);
      }
    }

    function onPm(msg) {
      if (!alive || !market) return;
      if (msg.type === "list" || (msg.type === "resolved" && msg.id === id)) return load();
      if (msg.type !== "tick" || msg.id !== id) return;
      if (msg.status && msg.status !== market.status) return load();
      market = M().applyTick(market, msg);
      const last = hist[hist.length - 1];
      if (msg.prices_ppm && (!last || msg.seq > last.seq)) hist.push({ seq: msg.seq, public_tt: msg.public_tt, prices_ppm: msg.prices_ppm });
      patchLive();
      panel && panel.refreshQuote();
    }

    const off = store().onPredictions(onPm);
    store().watchPredictions();
    store().subscribePrediction(id);
    load();

    return () => {
      alive = false;
      off();
      panel && panel.destroy();
      store().unsubscribePrediction(id);
      store().unwatchPredictions();
    };
  }

  SS.pages.pmDetail = { tab: null, render };
})();
