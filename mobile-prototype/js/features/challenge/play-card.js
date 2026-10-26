/**
 * 每日挑战的两个挂件（SS.challengeCard）：
 *   mount(host)        玩法页的挑战卡（slot play:challenge，order 10）：回合条、阶段与倒计时、结算后的名次、主按钮（primaryAction）
 *   mountBanner(host)  挑战存档里行情页顶部的横幅（slot market.banner:challenge-banner）：仅 state.save.mode === "challenge" 时显示
 * 秒级刷新只改 data-role="sub" / 横幅文字，不重建卡片（避免打断点按）；数据变化（challenge:update）才整体重绘。
 * 后端没有挑战接口（FEATURE_UNAVAILABLE）时显示“即将开放”。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const store = () => SS.store;
  const M = () => SS.challengeModel;
  const UI = () => SS.challengeUi;
  const DESC = "全服同一份行情和事件。每天 4 轮，每轮一条重大事件，大家同时预测、交易，晚上统一结算排名。";
  const ROUND_WORD = { before: "未开始", burst: "快放中", hold: "进行中", final: "最后一段" };

  const inChallengeSave = () => {
    const s = store().state;
    return !!(s.save && s.save.mode === "challenge");
  };

  /** 标题（阶段相关，不含倒计时） */
  function titleOf(ch) {
    if (ch.status === "scheduled") return `${M().clockText(ch.starts_at)} 开赛`;
    if (ch.status === "settled") return "今日已结算";
    if (ch.status === "void") return "今日挑战已作废";
    if (!ch.round_index) return "今日行情进行中";
    return `第 ${ch.round_index} 轮${ROUND_WORD[ch.phase] || ""}`;
  }

  /** 副文案（秒级刷新）：倒计时 + 本人进度或名次 */
  function subText(ch, st, now) {
    const tl = M().timeline(ch, st.skew, now);
    const mine = ch.my_entry;
    if (ch.status === "scheduled") return `距开赛 ${M().countdown(ch.starts_at, st.skew, now).text}`;
    if (ch.status === "settled") {
      const r = mine && mine.result;
      return r && r.rank != null ? `你的排名 第 ${r.rank} 名 / ${r.eligible_count} 人` : `全服 ${ch.participant_count} 人参加`;
    }
    const me = mine ? `已答 ${mine.answered_rounds}/${ch.rounds_total} 轮` : "未参加";
    const rankNote = mine ? "排名结算后公布" : "";
    return [tl.hint, me, rankNote].filter(Boolean).join(" · ");
  }

  function actionHtml(action) {
    if (action.kind === "enter") return html`<button type="button" class="btn btn-primary btn-block btn-lg" data-action="enter">${action.label}</button>`;
    if (action.kind === "nav") return html`<a class="btn btn-primary btn-block btn-lg" href="${SS.href(action.to)}">${action.label}</a>`;
    if (action.kind === "disabled") return html`<button type="button" class="btn btn-block btn-lg" disabled>${action.label}</button>`;
    return "";
  }

  function cardHtml(ch, st, now) {
    const tl = M().timeline(ch, st.skew, now);
    const action = M().primaryAction(ch, { now, skew: st.skew, cards: st.cards[ch.id] });
    return html`<section class="card challenge-card" data-role="challenge-card">
      <div class="ch-head">
        <h2 class="card__title">每日挑战</h2>
        <span class="t2 num xs">${SS.challengeModel.ymdText(ch.challenge_date)} · ${ch.participant_count} 人参加</span>
      </div>
      <p class="t2 sm ch-desc">${DESC}</p>
      ${UI().roundBarHtml(tl.bar)}
      <div class="ch-meta">
        <div class="ch-meta__text">
          <span class="ch-meta__title">${titleOf(ch)}</span>
          <span class="t2 xs" data-role="sub">${subText(ch, st, now)}</span>
        </div>
        <a class="ch-link" href="#/challenge/board">排行榜 ›</a>
      </div>
      ${actionHtml(action)}
    </section>`;
  }

  /** 占位 / 加载 / 未生成 三种非正常状态 */
  function placeholderHtml(st) {
    if (st.error === "FEATURE_UNAVAILABLE") return SS.soonCardHtml({ title: "每日挑战", desc: DESC });
    if (!st.loaded) return html`<section class="card challenge-card"><div class="skeleton" style="height:20px;width:40%"></div><div class="skeleton" style="height:6px;margin-top:14px"></div><div class="skeleton" style="height:44px;margin-top:14px"></div></section>`;
    if (!st.today) return html`<section class="card challenge-card" data-role="challenge-card"><h2 class="card__title">每日挑战</h2><p class="t2 sm ch-desc">今日挑战未生成，稍后再来看看。</p></section>`;
    return html`<section class="card challenge-card"><h2 class="card__title">每日挑战</h2><p class="t2 sm">${st.error ? SS.store.errorText(st.error) : ""}</p></section>`;
  }

  function mount(host) {
    let lastRefresh = 0;
    const draw = () => {
      const st = store().state.challenge;
      const now = Date.now();
      if (!st.today || st.error) return SS.mount(host, placeholderHtml(st));
      SS.mount(host, cardHtml(st.today, st, now));
    };
    const onClick = (e) => {
      const b = e.target.closest('[data-action="enter"]');
      if (!b || b.disabled) return;
      b.disabled = true;
      SS.challengeFlow.enter(store().state.challenge.today.id);
    };
    host.addEventListener("click", onClick);
    const unsub = store().on("challenge:update", draw);
    const timer = setInterval(() => {
      const st = store().state.challenge;
      if (!st.today) return;
      const now = Date.now();
      const sub = host.querySelector('[data-role="sub"]');
      if (sub) sub.textContent = subText(st.today, st, now);
      if (SS.challengeFlow.needsRefresh(M().timeline(st.today, st.skew, now), lastRefresh, now)) {
        lastRefresh = now;
        SS.challengeFlow.refresh();
      }
    }, 1000);
    draw();
    SS.challengeFlow.refresh();
    return () => {
      clearInterval(timer);
      unsub();
      host.removeEventListener("click", onClick);
    };
  }

  /** 挑战存档的行情横幅：点击回挑战页 */
  function mountBanner(host) {
    const draw = () => {
      const st = store().state.challenge;
      const ch = st.today;
      const show = inChallengeSave() && ch && ch.status === "running";
      host.hidden = !show;
      if (!show) return SS.mount(host, "");
      const tl = M().timeline(ch, st.skew, Date.now());
      SS.mount(
        host,
        html`<a class="challenge-banner" href="#/challenge">
          <span class="tag tag--accent">挑战中</span>
          <span class="challenge-banner__text">${tl.roundText}${tl.hint ? " · " : ""}<span data-role="cd">${tl.hint}</span></span>
          <span class="t2" aria-hidden="true">›</span>
        </a>`
      );
    };
    const unsub = store().on("challenge:update", draw);
    const timer = setInterval(() => {
      if (inChallengeSave()) draw();
    }, 1000);
    draw();
    return () => {
      clearInterval(timer);
      unsub();
    };
  }

  SS.challengeCard = { mount, mountBanner, subText };
})();
