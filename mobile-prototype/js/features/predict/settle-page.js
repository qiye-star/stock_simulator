/**
 * 结算复盘（#/prediction/:id，SS.pages.prediction）：对照 Settle 画板。
 *   头部：返回 + “预测揭晓”；事件短标题 · 第 N–M 个交易日；积分（settled 时 +N，44px、强调色）
 *   每题分数卡（得分 / 选择 / 比瞎猜）；传导排序表（实际排名 / 你的排名 / 3 日涨跌）；dir 无排序表时一行“实际 … 落在第 N 档”
 *   “为什么这样走”（≤3 条，SS.predictModel.whyBullets，事件详情不可得则隐藏；每条首句加粗）；底行“看我的校准曲线 ›”
 *   3 日涨跌按行情约定红涨绿跌（.settle-table .up/.down 覆盖 td 的文字色）
 * 状态：open → 去作答；answered → 等待揭晓；expired → 未作答（展示真值）；void → 已作废。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.predictModel;
  const PM = SS.predictMath;

  const signed = (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n}`);

  function render(view, params) {
    const store = SS.store;
    const id = params.id;
    const offs = [];
    let alive = true;
    let seq = 0;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">预测揭晓</h1>
        </header>
        <div class="settle-body" data-role="body"><div class="skeleton" style="height:96px;border-radius:var(--r-lg);margin-top:8px"></div></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    function notice(title, desc, action) {
      SS.mount(body(), html`<div class="empty"><div class="empty__title">${title}</div>${desc ? html`<p class="t3 sm">${desc}</p>` : ""}${action || ""}</div>`);
    }

    function scoreCard(q, card) {
      const res = M.rOf(card, q.qid);
      const ans = M.aOf(card, q.qid);
      const label = M.QTYPE_TEXT[q.qid];
      let desc = "未作答";
      if (q.qid === "dir" && ans && ans.probs) desc = `选 ${PM.bucketLabels(q.edges_bp)[ans.pick]}，把握 ${Math.max(...ans.probs)}%`;
      if (q.qid === "rank" && ans && ans.order) {
        const hits = M.rankHits(ans.order, res && res.true_top);
        desc = res && res.true_top ? (hits === 3 ? "前三全对" : `对了 ${hits} 个`) : "等待揭晓";
      }
      if (q.qid === "rumor" && ans && ans.probs) desc = `选 ${M.rumorPickText(ans.pick)}，把握 ${Math.max(...ans.probs)}%`;
      const score = res && res.score != null ? String(res.score) : "—";
      const base = res && res.baseline != null ? `比瞎猜 ${signed(res.baseline)}` : "";
      return html`<div class="card settle-score"><span class="t2 xs">${label}</span><span class="num settle-score__v">${score}</span><span class="t2 xs">${desc}</span>${base ? html`<span class="t3 xs">${base}</span>` : ""}</div>`;
    }

    function rankTable(card) {
      const rows = M.settleRows(card);
      if (!rows.length || !M.rOf(card, "rank") || !M.rOf(card, "rank").true_top) return "";
      return html`<div class="card card--flush settle-tbl-card"><table class="settle-table">
        <thead><tr><th>板块</th><th class="r">实际排名</th><th class="r">你的排名</th><th class="r">3 日涨跌</th></tr></thead>
        <tbody>${rows.map(
          (x) => html`<tr><td>${x.name}</td><td class="r num">${x.actual == null ? "—" : x.actual}</td><td class="r num">${x.mine == null ? "—" : x.mine}</td><td class="r num ${x.change_bp == null ? "" : SS.fmt.trend(x.change_bp)}">${x.change_bp == null ? "—" : SS.fmt.pctBp(x.change_bp)}</td></tr>`
        )}</tbody></table></div>`;
    }

    function dirLine(card) {
      const d = M.qOf(card, "dir");
      const res = M.rOf(card, "dir");
      if (!d || !res || !res.resolved || M.qOf(card, "rank")) return "";
      return html`<p class="t2 sm settle-line">实际 <span class="num ${SS.fmt.trend(res.change_bp)}">${SS.fmt.pctBp(res.change_bp)}</span> 落在第 ${res.outcome_bucket + 1} 档（${PM.bucketRangeText(res.outcome_bucket, d.edges_bp)}）</p>`;
    }

    function headline(card) {
      const d = M.qOf(card, "dir");
      const r = M.qOf(card, "rank");
      const from = d ? d.from_day : r ? r.at_day : null;
      const to = M.revealDay(card);
      const span = from == null ? "" : from === to ? ` · 第 ${SS.fmt.dayNo(from)} 个交易日` : ` · 第 ${SS.fmt.dayNo(from)}–${SS.fmt.dayNo(to)} 个交易日`;
      // 完整标题换行显示，不截断（画板为短标题，真实标题较长时不能省略关键信息）
      return `${card.event ? card.event.title : "重大事件"}${span}`;
    }

    function statusBlock(card) {
      if (card.status === "settled") {
        return html`<div class="settle-head__points"><span class="num settle-points">+${card.points || 0}</span><span class="t2 sm">积分</span>${card.points_capped ? html`<span class="tag">已达今日上限</span>` : ""}</div>`;
      }
      if (card.status === "answered") {
        const rev = M.revealDay(card);
        return html`<p class="t2 sm">等待揭晓${rev == null ? "（传闻揭晓后结算）" : ` · 第 ${SS.fmt.dayNo(rev)} 个交易日`}</p>`;
      }
      if (card.status === "open") {
        return html`<div class="settle-open"><p class="t2 sm">这张还没有作答</p><button type="button" class="btn btn-primary btn-sm" data-role="answer">去作答</button></div>`;
      }
      if (card.status === "expired") return html`<p class="t2 sm">这张没有作答</p>`;
      return html`<p class="t2 sm">本卡已作废</p>`;
    }

    async function loadWhy(card) {
      const box = SS.$('[data-role="why"]', view);
      if (!box) return;
      let detail = null;
      try {
        detail = await store.loadEvent(card.event_id);
      } catch (_) {
        detail = null;
      }
      if (!alive) return;
      const bullets = M.whyBullets(card, detail);
      if (!bullets.length) return (box.hidden = true);
      box.hidden = false;
      // 每条第一句加粗作引导句（画板：“有色涨、下游跌。”）
      const lead = (b) => {
        const sp = M.leadSplit(b);
        return sp ? html`<b>${sp.lead}</b>${sp.rest}` : b;
      };
      SS.mount(box, html`<span class="settle-why__title">为什么这样走</span><ul class="settle-why__list">${bullets.map((b) => html`<li>${lead(b)}</li>`)}</ul>`);
    }

    async function load() {
      const my = ++seq;
      try {
        const card = await store.loadPrediction(id);
        if (!alive || my !== seq) return;
        paint(card);
      } catch (err) {
        if (!alive || my !== seq) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") SS.mount(body(), SS.soonCardHtml({ title: "预测揭晓", desc: "预测卡暂未开放。" }));
        else if (err && err.code === "PREDICTION_NOT_FOUND") notice("预测卡不存在", "", html`<a class="btn btn-sm" href="${SS.href("/predictions")}">我的预测</a>`);
        else SS.mount(body(), html`<div class="empty"><div class="empty__title">加载失败</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`);
        const retry = SS.$('[data-role="retry"]', body());
        if (retry) retry.addEventListener("click", load);
      }
    }

    function paint(card) {
      const qs = M.sortQuestions(card.questions);
      SS.mount(
        body(),
        html`<div class="settle-head">
            <span class="t2 sm">${headline(card)}</span>
            ${statusBlock(card)}
          </div>
          <div class="settle-scores">${qs.map((q) => scoreCard(q, card))}</div>
          ${rankTable(card)}
          ${dirLine(card)}
          <section class="card settle-why" data-role="why" hidden></section>
          <div class="settle-foot"><a href="#/me?focus=calib">看我的校准曲线 ›</a></div>`
      );
      const ans = SS.$('[data-role="answer"]', body());
      if (ans) ans.addEventListener("click", () => SS.predictionCard.open(card.id));
      if (card.event_id) loadWhy(card);
    }

    load();
    offs.push(
      store.on("ws:prediction", (msg) => {
        if (alive && msg.card_id === id) load();
      })
    );
    return () => {
      alive = false;
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.prediction = { tab: null, render };
})();
