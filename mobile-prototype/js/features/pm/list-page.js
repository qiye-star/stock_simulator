/**
 * 预测市场列表（#/pm?status=open|ended，SS.pages.pmList）：
 *   顶栏返回 + “预测市场” + 右侧“记录 ›”；分段 进行中 / 已结束（query.status，缺省进行中）；
 *   进行中 = open + closed（待结算也还在这里），已结束 = resolved + voided（后端 status=all，前端分组）。
 *   WS：页面存活期间 watchPredictions()；list 事件 → 重拉；tick → 只替换受影响的那一张卡。
 *   FEATURE_UNAVAILABLE（后端没有该接口）→ “即将开放”占位。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  SS.pages = SS.pages || {};
  const { html } = SS;
  const store = () => SS.store;
  const U = () => SS.pmUi;
  const SOON_DESC = "用积分买卖，价格就是全服的判断，功能即将开放。";

  const inTab = (tab, m) => (tab === "ended" ? m.status === "resolved" || m.status === "voided" : m.status === "open" || m.status === "closed");

  function render(view, params) {
    const q = params.query || {};
    let tab = q.status === "ended" ? "ended" : "open";
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
          <h1 class="topbar__title topbar__title--sub">预测市场</h1>
          <a class="topbar__link" href="${SS.href("/pm/records")}">记录 ›</a>
        </header>
        <div class="pm-page">
          <div class="seg seg--inline-full pm-seg" data-role="seg">
            <span class="seg__thumb" aria-hidden="true"></span>
            <button type="button" data-value="open">进行中</button>
            <button type="button" data-value="ended">已结束</button>
          </div>
          <div class="pm-list" data-role="list"></div>
          <button type="button" class="btn btn-ghost btn-block" data-role="more" hidden>加载更多</button>
        </div>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    $("back").addEventListener("click", () => SS.router.back());
    const seg = SS.segmented($("seg"), (v) => SS.router.replace(`/pm?status=${v}`));
    seg.set(tab);
    $("more").addEventListener("click", () => {
      if (next) load(false);
    });

    function draw() {
      const list = $("list");
      $("more").hidden = !next || !!fail;
      if (fail) {
        if (fail.code === "FEATURE_UNAVAILABLE") return SS.soonCard(list, { title: "预测市场", desc: SOON_DESC });
        return SS.mount(list, html`<div class="empty-inline t2 sm">${store().errorText(fail.code)}</div>`);
      }
      if (!loaded) {
        return SS.mount(list, html`<div class="skeleton" style="height:96px;border-radius:18px"></div><div class="skeleton" style="height:96px;border-radius:18px;margin-top:10px"></div>`);
      }
      const shown = items.filter((m) => inTab(tab, m));
      if (!shown.length) {
        return SS.mount(list, html`<div class="empty-inline t2 sm">${tab === "ended" ? "还没有已结束的市场" : "今日挑战开始后开市，合约按挑战的回合陆续出现。"}</div>`);
      }
      SS.mount(list, shown.map((m) => U().cardHtml(m)));
    }

    async function load(reset) {
      const my = ++seq;
      if (reset) {
        items = [];
        next = null;
      }
      try {
        const out = await store().listPredictionMarkets({ status: "all", cursor: reset ? undefined : next || undefined });
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

    /** 推送的价格变动只替换这一张卡；状态变化（开市/休市/结算）重拉 */
    function onTick(msg) {
      const idx = items.findIndex((m) => m.id === msg.id);
      if (idx < 0) return;
      if (msg.status && msg.status !== items[idx].status) return load(true);
      const cur = items[idx];
      const nxt = SS.pmModel.applyTick(cur, msg);
      if (nxt === cur) return;
      items[idx] = nxt;
      const el = SS.$(`[data-pm-card="${msg.id}"]`, view);
      if (el && inTab(tab, nxt)) el.replaceWith(SS.el(U().cardHtml(nxt)));
    }

    const off = store().onPredictions((msg) => {
      if (!alive) return;
      if (msg.type === "list" || msg.type === "resolved") load(true);
      else if (msg.type === "tick") onTick(msg);
    });
    store().watchPredictions();
    load(true);

    return () => {
      alive = false;
      off();
      store().unwatchPredictions();
    };
  }

  SS.pages.pmList = { tab: null, render };
})();
