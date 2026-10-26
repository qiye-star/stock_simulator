/**
 * 市场记录（#/pm/records，SS.pages.pmRecords）：我的结算记录（PmSettlementOut，按时间降序），游标“加载更多”。
 * 每条：问题、获胜项与兑付/投入、净盈亏（中性色，积分不用红绿）；点开进入合约详情。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.pages = SS.pages || {};
  const { html } = SS;
  const store = () => SS.store;
  const SOON_DESC = "市场结算后的记录会出现在这里，功能即将开放。";

  function render(view) {
    let items = [];
    let next = null;
    let loaded = false;
    let fail = null;
    let seq = 0;
    let alive = true;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">市场记录</h1>
        </header>
        <div class="pm-page">
          <div class="pm-list" data-role="list"></div>
          <button type="button" class="btn btn-ghost btn-block" data-role="more" hidden>加载更多</button>
        </div>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    $("back").addEventListener("click", () => SS.router.back());
    $("more").addEventListener("click", () => {
      if (next) load(false);
    });

    function draw() {
      const list = $("list");
      $("more").hidden = !next || !!fail;
      if (fail) {
        if (fail.code === "FEATURE_UNAVAILABLE") return SS.soonCard(list, { title: "市场记录", desc: SOON_DESC });
        return SS.mount(list, html`<div class="empty-inline t2 sm">${store().errorText(fail.code)}</div>`);
      }
      if (!loaded) return SS.mount(list, html`<div class="skeleton" style="height:96px;border-radius:18px"></div>`);
      if (!items.length) return SS.mount(list, html`<div class="empty-inline t2 sm">还没有结算记录</div>`);
      SS.mount(list, items.map((s) => SS.pmUi.settledCardHtml(s)));
    }

    async function load(reset) {
      const my = ++seq;
      if (reset) {
        items = [];
        next = null;
      }
      try {
        const out = await store().listMyPredictionSettlements(reset ? undefined : next || undefined);
        if (!alive || my !== seq) return;
        items = reset ? out.items : items.concat(out.items);
        next = out.next_cursor || null;
        loaded = true;
        fail = null;
      } catch (err) {
        if (!alive || my !== seq) return;
        fail = err;
      }
      draw();
    }

    load(true);
    return () => {
      alive = false;
    };
  }

  SS.pages.pmRecords = { tab: null, render };
})();
