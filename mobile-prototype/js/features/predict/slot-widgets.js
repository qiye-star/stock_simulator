/**
 * 其它页面的挂载点小部件（⑥ 预留的槽位，由 index.js 注册）：
 *   news.majorFooter（html）  重大快讯底行：预测待答 / 已提交 · 第 N 日揭晓 / 预测 +N 积分
 *   event.intel（html）       事件详情锁提示右侧：“用情报卡查看”（产业链）+ 传闻未揭晓时“真假提示”（情报卡抽屉）
 *   event.footer（mount）     事件详情底部“你的预测”卡
 *   chain.edgeAction（html）  产业链未揭示 / 只揭示强度的边：情报按钮（data-intel-edge，点击由 index.js 分流到情报卡）
 *   closeSummary.extra（mount） 收盘小结“今天的大事”：待结算预测卡数与揭晓日
 * html 型槽只读缓存（state.predict），缓存缺失时给出缺省文案；mount 型槽在缓存刷新后重绘（predict:update）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.predictModel;
  const store = () => SS.store;
  const byEvent = (id) => (store().state.predict.byEvent || {})[id] || null;
  const intelPrices = () => (store().state.predict.intel && store().state.predict.intel.prices) || { edge_l1: 100, edge_l2: 200, rumor_hint: 80 };

  /** 你的预测对应的简短描述（事件详情用） */
  function cardLine(c) {
    const d = M.qOf(c, "dir");
    const r = M.qOf(c, "rank");
    const a = M.aOf(c, "dir");
    if (d) {
      const label = SS.predictMath.bucketLabels(d.edges_bp)[a ? a.pick : 0];
      const conf = a ? Math.max(...a.probs) : null;
      return `${M.targetLabel(d)} ${M.windowDays(d)} 日 “${label}”${conf != null ? ` · 把握 ${conf}%` : ""}`;
    }
    if (r) return "传导排序 · 选前三板块";
    const u = M.qOf(c, "rumor");
    if (u) {
      const ua = M.aOf(c, "rumor");
      return ua && ua.probs ? `传闻 · 选 ${M.rumorPickText(ua.pick)} · 把握 ${Math.max(...ua.probs)}%` : "传闻真假题";
    }
    return "";
  }

  // ---------- news.majorFooter ----------
  function majorFooter(ctx) {
    const c = byEvent(ctx.event_id);
    if (!c) return "";
    const rev = M.revealDay(c);
    const when = rev == null ? "传闻揭晓后结算" : `第 ${SS.fmt.dayNo(rev)} 个交易日揭晓`;
    if (c.status === "open") return html`<span class="pred-tag pred-tag--strong">待作答</span>`;
    if (c.status === "answered") return html`<span class="t2 xs">预测已提交 · ${when}</span>`;
    if (c.status === "settled") return html`<span class="num pred-tag pred-tag--strong">预测 +${c.points || 0} 积分</span>`;
    return "";
  }

  // ---------- event.intel ----------
  function eventIntel(ctx) {
    const e = ctx.event;
    if (!e) return "";
    const chain = e.source_industry ? html`<a class="intel-link" href="${SS.href("/chain", { focus: e.source_industry })}">用情报卡查看</a>` : "";
    // 已购买过的传闻提示：直接显示结果，不再给购买入口（IntelStateOut.rumor_hints，按事件 id 匹配）
    const have = ((store().state.predict.intel || {}).rumor_hints || []).find((h) => h.event_id === e.event_id);
    let rumor = "";
    if (have) rumor = html`<span class="intel-pill intel-pill--done" role="status">${have.hint === "likely_true" ? "可能为真" : "可能为假"} · 准确率 ${have.accuracy_pct}%</span>`;
    else if (e.rumor_status === "unresolved" && store().predictEnabled())
      rumor = html`<button type="button" class="intel-pill" data-intel-event="${e.event_id}">真假提示 · ${intelPrices().rumor_hint} 分</button>`;
    return html`${chain}${rumor}`;
  }

  // ---------- event.footer ----------
  function eventFooter(host, ctx) {
    const e = ctx.event;
    if (!store().predictEnabled() || !e) return () => {};
    const draw = () => {
      const c = byEvent(e.event_id);
      if (!c) return SS.mount(host, "");
      const rev = M.revealDay(c);
      const tag =
        c.status === "settled" ? html`<span class="num pred-tag pred-tag--strong">+${c.points || 0}</span>`
        : c.status === "answered" ? html`<span class="tag">第 ${SS.fmt.dayNo(rev == null ? c.opened_trading_day : rev)} 日揭晓</span>`
        : c.status === "open" ? html`<span class="tag tag--accent">待作答</span>`
        : html`<span class="tag">${M.STATUS_TAG[c.status] || ""}</span>`;
      SS.mount(
        host,
        html`<a class="card pred-mine" href="${SS.href(`/prediction/${c.id}`)}">
          <span class="pred-mine__main"><span class="t2 xs">你的预测</span><span class="pred-mine__text">${cardLine(c)}</span></span>
          ${tag}
        </a>`
      );
    };
    draw();
    return store().on("predict:update", draw);
  }

  // ---------- chain.edgeAction ----------
  function chainEdge(ctx) {
    const edge = ctx.edge;
    if (!edge || !store().predictEnabled() || (edge.revealed_level || 0) >= 2) return "";
    const p = intelPrices();
    const lvl = edge.revealed_level || 0;
    const price = lvl === 0 ? p.edge_l1 : p.edge_l2 - p.edge_l1;
    return html`<span class="intel-pill" data-intel-edge="${edge.id}" role="button" tabindex="0" aria-label="用情报卡${lvl === 0 ? "揭示强度" : "查看滞后"}">${lvl === 0 ? "揭示" : "看滞后"} · ${price} 分</span>`;
  }

  // ---------- closeSummary.extra ----------
  function closeExtra(host) {
    if (!store().predictEnabled()) return;
    const pending = (store().state.predict.cards || []).filter((c) => c.status === "open" || c.status === "answered");
    if (!pending.length) return;
    const days = pending.map((c) => M.revealDay(c)).filter((d) => d != null);
    const when = days.length ? ` · 第 ${SS.fmt.dayNo(Math.max(...days))} 个交易日揭晓` : "";
    SS.mount(
      host,
      html`<a class="cs-event" href="${SS.href("/predictions", { status: "pending" })}">
        <span class="tag tag--accent">预测</span>
        <span class="cs-event__title">预测卡 ${pending.length} 张待结算${when}</span>
        <span class="t2" aria-hidden="true">›</span>
      </a>`
    );
  }

  SS.predictSlots = { majorFooter, eventIntel, eventFooter, chainEdge, closeExtra };
})();
