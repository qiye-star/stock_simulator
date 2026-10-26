/**
 * 预测市场的共用片段（SS.pmUi）：只拼 HTML（SS.html 默认转义；问题与事件标题都经转义），不做请求。
 *   cardHtml(m)                 市场卡（列表页、玩法页）：问题、状态 tag、最热选项与概率条、关闭说明与人数
 *   settledCardHtml(s)          结算卡（玩法页最近一张、记录页）：结果、兑付、盈亏（中性色，积分不用红绿）
 *   optsHtml(m, sel)            选项行（.pm-opt，≥44px，选中项 aria-pressed）
 *   curveHtml(points, label)    单选项概率曲线（中性 + accent，SVG；points 为 0–1 的概率数组）
 *   setOptPct(el, ppm)          就地更新一个选项的概率条与百分比（推送时不重绘整页）
 * 颜色只用 tokens；概率与积分一律中性/accent，不用 --up/--down。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.pmModel;
  const TAG = { open: "进行中", closed: "待结算", resolved: "已结算", voided: "已作废" };

  const pctText = (ppm) => M().formatProb(ppm);
  const barStyle = (ppm) => `width:${M().barPct(ppm).toFixed(2)}%`;

  /** 最热选项（并列取小下标） */
  function leadOf(m) {
    const labels = M().outcomeLabels(m);
    const idx = M().leadingIndex(m.outcomes.map((o) => o.price_ppm));
    return { idx, label: labels[idx] || "", ppm: m.outcomes[idx] ? m.outcomes[idx].price_ppm : 0 };
  }

  /** 已结算时的获胜项文案 */
  function winnerText(m) {
    const labels = M().outcomeLabels(m);
    return m.winning_outcome == null ? "" : labels[m.winning_outcome] || "";
  }

  function cardHtml(m) {
    const mine = Array.isArray(m.my_shares) && m.my_shares.some((n) => n > 0);
    const body =
      m.status === "resolved" || m.status === "voided"
        ? html`<div class="pm-card__lead"><span class="pm-card__result">${m.status === "voided" ? "已作废" : `结果：${winnerText(m)}`}</span></div>`
        : (() => {
            const lead = leadOf(m);
            return html`<div class="pm-card__lead">
              <span class="t2 xs pm-card__label">最热 ${lead.label}</span>
              <span class="pm-bar" aria-hidden="true"><i style="${barStyle(lead.ppm)}"></i></span>
              <span class="num pm-card__pct" data-role="pct">${pctText(lead.ppm)}</span>
            </div>`;
          })();
    return html`<a class="card pm-card" href="${SS.href(`/pm/${m.id}`)}" data-pm-card="${m.id}">
      <div class="pm-card__top">
        <span class="pm-card__q">${M().questionText(m)}</span>
        ${m.status === "resolved" || m.status === "voided" ? "" : html`<span class="tag ${m.status === "open" ? "tag--accent" : ""}">${TAG[m.status] || ""}</span>`}
      </div>
      ${body}
      <div class="pm-card__meta t3 xs">
        <span>${M().closeText(m)}</span><span>${m.traders} 人参与</span>
        ${mine ? html`<span class="tag">我已持仓</span>` : ""}
      </div>
    </a>`;
  }

  /** 净投入为负（卖出回收超过买入）时写“已回收”，不显示负的投入 */
  const costText = (net) => (net >= 0 ? `投入 ${net} 积分` : `已回收 ${-net} 积分`);

  /** 结算卡：s 为 PmSettlementOut（question、market_kind、winning_outcome、payout/net/pnl） */
  function settledCardHtml(s, { title = null } = {}) {
    const kind = s.market_kind || "bucket";
    const labels = M().outcomeLabels({ kind, question: s.question });
    const win = s.winning_outcome == null ? "" : labels[s.winning_outcome] || "";
    // 结算记录不含事件标题（PmSettlementOut 只有 event_id），传闻合约用通用问句
    const q = title || (kind === "rumor" ? "传闻合约：会被辟谣吗？" : M().questionText({ kind, question: s.question, event: null }));
    const pnl = Number(s.pnl_points) || 0;
    const pnlText = `${pnl > 0 ? "+" : ""}${pnl} 积分`;
    const voided = s.kind === "voided";
    return html`<a class="card pm-settle" href="${SS.href(`/pm/${s.market_id}`)}">
      <span class="pm-settle__q">${q}</span>
      <span class="t2 xs">${voided ? "已作废，按净投入退款" : `结果：${win} · 兑付 ${s.payout_points} 积分 · ${costText(Number(s.net_cost_points) || 0)}`}</span>
      <span class="num pm-settle__pnl">${voided ? `退款 ${s.payout_points} 积分` : pnlText}</span>
    </a>`;
  }

  function optsHtml(m, sel) {
    const labels = M().outcomeLabels(m);
    return html`<div class="pm-opts" role="group" aria-label="选项" data-role="opts">${m.outcomes.map(
      (o, i) => html`<button type="button" class="pm-opt" data-idx="${i}" aria-pressed="${i === sel ? "true" : "false"}">
        <span class="pm-opt__label num">${labels[i] || ""}</span>
        <span class="pm-bar pm-opt__bar" aria-hidden="true"><i style="${barStyle(o.price_ppm)}"></i></span>
        <span class="pm-opt__pct num" data-role="opt-pct">${pctText(o.price_ppm)}</span>
      </button>`
    )}</div>`;
  }

  /** 曲线：W=320，H=90；points 为 0–1 概率数组（按时间升序）。样式见 css/features/pm.css */
  function curveHtml(points, label) {
    const c = M().curvePaths(points, 320, 90, 6);
    return html`<svg class="pm-curve" viewBox="0 0 320 90" width="100%" role="img" aria-label="${label}" data-role="curve">
      <line class="pm-curve__grid" x1="0" y1="84" x2="320" y2="84"></line>
      <line class="pm-curve__grid pm-curve__grid--mid" x1="0" y1="45" x2="320" y2="45"></line>
      <path class="pm-curve__area" d="${c.area}"></path>
      <path class="pm-curve__line" d="${c.line}"></path>
      ${c.last ? html`<circle class="pm-curve__dot" cx="${c.last.x}" cy="${c.last.y}" r="3.5"></circle>` : ""}
    </svg>`;
  }

  /** 就地更新选项行（推送） */
  function setOptPct(el, ppm) {
    const bar = el.querySelector(".pm-opt__bar i");
    if (bar) bar.style.width = barStyle(ppm).replace("width:", "");
    const pct = el.querySelector('[data-role="opt-pct"]');
    if (pct) pct.textContent = pctText(ppm);
  }

  SS.pmUi = { cardHtml, settledCardHtml, optsHtml, curveHtml, setOptPct, leadOf, winnerText };
})();
