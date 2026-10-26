/**
 * 每日挑战共用的片段（SS.challengeUi）：回合条、回合行、作答/结果摘要、排行行、公平性卡与校验按钮。
 * 只拼 HTML（SS.html 默认转义；用户昵称、事件标题都经转义）；颜色只用 tokens，涨跌色只用于收益率。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.challengeModel;

  const ROUND_STATE_TEXT = { pending: "未开始", burst: "快放中", open: "可作答", closed: "已截止", resolved: "已判定" };
  const QTYPE_TEXT = { dir: "涨跌档位", rank: "板块排序", rumor: "传闻真假" };
  const VERIFY_TEXT = {
    ok: "✓ 种子与开局指纹一致",
    fail: "✗ 不一致：种子与开局指纹对不上，请不要相信这场行情",
    unavailable: "当前环境无法本地校验（需要 https 或 localhost）",
    invalid: "承诺数据不完整，无法校验",
  };

  /** 回合条（4 段）：is-done / is-live / is-pending，aria 说明逐段状态 */
  function roundBarHtml(bar) {
    const label = bar.map((s) => `第 ${s.index} 轮${ROUND_STATE_TEXT[s.state] || ""}`).join("，");
    return html`<div class="round-bar" role="img" aria-label="${label}">${bar.map((s) => html`<span class="round-bar__step ${s.cls}"></span>`)}</div>`;
  }

  /** 回合状态文字（round.state） */
  const roundStateText = (s) => ROUND_STATE_TEXT[s] || "";

  /** 本人答案摘要（每题一行） */
  function answerHtml(card) {
    const lines = M().answerLines(card);
    if (!lines.length) return html`<p class="t2 xs">本轮没有题目</p>`;
    return html`<div class="ch-lines">${lines.map((l) => html`<div class="ch-line"><span class="ch-line__q t2 xs">${QTYPE_TEXT[l.qid] || l.qid}</span><span class="ch-line__t">${l.text}</span></div>`)}</div>`;
  }

  /** 结算结果（每题一行，含本题得分；未判定显示“等待判定”） */
  function resultHtml(card) {
    const lines = M().resultLines(card);
    return html`<div class="ch-lines">${lines.map(
      (l) => html`<div class="ch-line"><span class="ch-line__q t2 xs">${QTYPE_TEXT[l.qid] || l.qid}</span><span class="ch-line__t ${l.resolved ? "" : "t2"}">${l.text}</span>${l.score != null ? html`<span class="num ch-line__s">${l.score}</span>` : ""}</div>`
    )}</div>`;
  }

  /** 本轮得分行：我的分 · 得分来源（同伴分 / 基线分） */
  function roundScoreHtml(card) {
    if (card.my_round_score == null) return html`<span class="t2 xs">${card.my_answers && card.my_answers.length ? "等待判定" : "未作答"}</span>`;
    const used = M().usedText(card.used);
    return html`<span class="xs ch-round-score"><span class="num ch-round-score__n">${card.my_round_score}</span> 分${used ? html` <span class="t2">· ${used}</span>` : ""}</span>`;
  }

  /** 排行表头 + 行（boardRows 的输出） */
  function boardHeadHtml(headers) {
    return html`<div class="board-row board-row--head"><span>名次</span><span>玩家</span><span class="r">${headers.c3}</span><span class="r">${headers.c4}</span></div>`;
  }
  function boardRowHtml(r) {
    return html`<div class="board-row${r.isMe ? " board-row--me" : ""}">
      <span class="num t2">${r.rankText}</span>
      <span class="board-row__name"><span class="board-row__n">${r.name}</span>${r.title ? html`<span class="tag board-row__tag">${r.title}</span>` : ""}${r.isMe ? html`<span class="t2 xs"> · 你</span>` : ""}</span>
      <span class="num r">${r.c3}</span>
      <span class="num r ${r.c4Tone || ""}">${r.c4}</span>
    </div>`;
  }

  /** 公平性卡：承诺指纹 + 结算后可校验 */
  function fairnessHtml({ seedCommitment, settled }) {
    return html`<section class="card ch-fair" data-role="fairness">
      <h3 class="card__title">公平性</h3>
      <p class="t2 xs">开局前公布了本场行情种子的指纹，晚上结算后公布种子本身，任何人都可以验证行情没有被临时改动。</p>
      <span class="num t2 xs ch-hash" title="${seedCommitment || ""}">sha256 · ${M().shortHash(seedCommitment) || "—"}</span>
      <div class="ch-fair__verify" data-role="verify-area">
        ${settled ? html`<button type="button" class="btn btn-sm btn-ghost" data-role="verify">验证种子</button>` : html`<span class="t2 xs">结算后可验证</span>`}
        <p class="ch-fair__result xs" data-role="verify-result" hidden></p>
      </div>
    </section>`;
  }

  /**
   * 绑定“验证种子”按钮：getReveal() → RevealOut（页面已有则直接返回，否则拉取）；结果写到 verify-result。
   * 非安全上下文显示“无法本地校验”，不假装通过。
   */
  function bindVerify(root, getReveal) {
    const btn = SS.$('[data-role="verify"]', root);
    if (!btn) return;
    const out = SS.$('[data-role="verify-result"]', root);
    const show = (text, ok) => {
      out.hidden = !text;
      out.textContent = text || "";
      out.classList.toggle("is-ok", !!ok);
    };
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const reveal = await getReveal();
        const r = await SS.challengeVerify.run(reveal);
        show(VERIFY_TEXT[r.status] || "", r.status === "ok");
      } catch (err) {
        SS.store.notifyError(err);
      } finally {
        btn.disabled = false;
      }
    });
  }

  SS.challengeUi = {
    ROUND_STATE_TEXT,
    QTYPE_TEXT,
    VERIFY_TEXT,
    roundBarHtml,
    roundStateText,
    answerHtml,
    resultHtml,
    roundScoreHtml,
    boardHeadHtml,
    boardRowHtml,
    fairnessHtml,
    bindVerify,
  };
})();
