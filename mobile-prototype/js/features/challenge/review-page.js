/**
 * 赛后复盘（#/challenge/:id/review，SS.pages.challengeReview）：
 *   成绩卡（综合 / 预测 / 交易收益 / 名次，积分）→ 各轮（事件、我的答案、判定结果、得分、全服均值）→
 *   公平性（公布的 seed、盐、承诺原文与 sha256，“验证种子”用 WebCrypto 本地计算，失败如实提示）。
 * 数据：GET /challenges/{id}/review + GET /challenges/{id}/reveal。未结算（CHALLENGE_NOT_SETTLED）、未参加（CHALLENGE_NOT_ENTERED）如实说明。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const store = () => SS.store;
  const M = () => SS.challengeModel;
  const UI = () => SS.challengeUi;

  const ERR_TEXT = {
    CHALLENGE_NOT_SETTLED: "挑战结算后才能查看复盘",
    CHALLENGE_NOT_ENTERED: "你没有参加这场挑战",
    CHALLENGE_NOT_FOUND: "挑战不存在",
    FEATURE_UNAVAILABLE: "复盘即将开放",
  };

  function statsHtml(entry) {
    const s = M().resultStats(entry && entry.result);
    if (!s) return html`<section class="card"><p class="t2 sm">这场挑战没有成绩（未参加或未判定）。</p></section>`;
    return html`<section class="card ch-score">
      <div class="ch-score__grid">
        <div class="ch-score__cell"><span class="t2 xs">综合</span><span class="num ch-score__big">${s.total}</span></div>
        <div class="ch-score__cell"><span class="t2 xs">预测</span><span class="num ch-score__big">${s.forecast}</span></div>
        <div class="ch-score__cell"><span class="t2 xs">交易收益</span><span class="num ch-score__big ${s.tradeTone}">${s.trade}</span></div>
        <div class="ch-score__cell"><span class="t2 xs">名次</span><span class="num ch-score__mid">${s.rank}</span></div>
      </div>
      <div class="ch-score__foot"><span class="t2 xs">本场积分</span><span class="num ch-score__pts">${s.points}</span></div>
    </section>`;
  }

  function roundsHtml(rounds) {
    return rounds.map((card) => {
      const crowd = M().crowdText(card);
      return html`<article class="card ch-row">
        <div class="ch-row__head"><span class="num t2 xs">第 ${card.round_index} 轮</span><span class="t2 xs">${UI().roundStateText(card.state)}</span></div>
        <h3 class="ch-row__title">${card.event ? card.event.title : "事件"}</h3>
        ${card.my_answers && card.my_answers.length ? UI().answerHtml(card) : html`<p class="t2 xs">本轮未作答</p>`}
        ${UI().resultHtml(card)}
        <div class="ch-row__foot">${UI().roundScoreHtml(card)}${crowd ? html`<span class="t2 xs">${crowd}</span>` : ""}</div>
      </article>`;
    });
  }

  function fairHtml(reveal) {
    if (!reveal) return html`<section class="card ch-fair"><h3 class="card__title">公平性</h3><p class="t2 xs">种子暂时无法获取，稍后再试。</p></section>`;
    return html`<section class="card ch-fair" data-role="fairness">
      <h3 class="card__title">公平性</h3>
      <p class="t2 xs">开局前公布了本场行情种子的指纹，结算后公布种子本身。下面的承诺原文经 sha256 计算后应与开局指纹一致。</p>
      <dl class="ch-kv">
        <dt>行情种子</dt><dd class="num ch-mono">${reveal.market_seed}</dd>
        <dt>盐</dt><dd class="ch-mono">${reveal.seed_salt}</dd>
        <dt>承诺原文</dt><dd class="ch-mono">${reveal.commitment_input}</dd>
        <dt>开局指纹 sha256</dt><dd class="ch-mono">${reveal.seed_commitment}</dd>
      </dl>
      <div class="ch-fair__verify" data-role="verify-area">
        <button type="button" class="btn btn-sm btn-ghost" data-role="verify">验证种子</button>
        <p class="ch-fair__result xs" data-role="verify-result" hidden></p>
      </div>
    </section>`;
  }

  function render(view, params) {
    const id = params.id;
    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">挑战复盘</h1>
          <a class="topbar__link" href="#/challenge/board?scope=all">排行</a>
        </header>
        <div class="ch-page" data-role="body">
          <section class="card"><div class="skeleton" style="height:120px"></div></section>
        </div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());
    let alive = true;

    async function load() {
      const [review, reveal] = await Promise.all([
        store().loadChallengeReview(id).catch((err) => ({ __err: err })),
        store().loadChallengeReveal(id).catch(() => null),
      ]);
      if (!alive) return;
      const el = body();
      if (!el) return;
      if (review.__err) {
        const code = review.__err.code;
        return SS.mount(
          el,
          html`<section class="card ch-empty"><h2 class="card__title">${ERR_TEXT[code] || "复盘暂不可用"}</h2><a class="btn btn-ghost btn-block" href="#/challenge">返回挑战</a></section>`
        );
      }
      const ymd = SS.challengeModel.ymdText(review.challenge.challenge_date);
      SS.mount(
        el,
        html`<h2 class="ch-review__title">${ymd} 挑战</h2>
          ${statsHtml(review.entry)}
          <section class="ch-rounds"><h2 class="ch-past__title">各轮结果</h2>${roundsHtml(review.rounds)}</section>
          ${fairHtml(reveal)}`
      );
      const fair = SS.$('[data-role="fairness"]', el);
      if (fair && reveal) UI().bindVerify(fair, () => Promise.resolve(reveal));
    }

    load();
    return () => {
      alive = false;
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.challengeReview = { tab: null, render };
})();
