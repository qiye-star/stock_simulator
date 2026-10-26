/**
 * 挑战页（#/challenge，SS.pages.challenge，二级页无 Dock）：
 *   状态卡（阶段、回合条、下一时刻倒计时、本轮截止）→ 参加（未参加）/ 当前回合卡（已参加且回合 open）→ 本场各轮 → 往期挑战。
 *   当前回合卡复用预测卡组件 SS.predictionCard.render/bind，内联提交（onSubmit），不出“这张不答”，也不走弹层与情报卡。
 *   数据：SS.challengeFlow.refresh()；倒计时每秒只改 data-cd 文本，到点节流重拉；challenge:update 整体重绘。
 * 后端没有挑战接口（FEATURE_UNAVAILABLE）时显示“即将开放”。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const store = () => SS.store;
  const M = () => SS.challengeModel;
  const UI = () => SS.challengeUi;
  const PC = () => SS.predictionCard;
  const NOTE = "全服同一份题目，截止前可以修改；截止后统一判定。答对计入挑战成绩，不影响你的资金。";

  function statusHtml(ch, tl) {
    const live = ch.status === "running";
    return html`<section class="card ch-status">
      <div class="ch-status__head">
        <span class="tag${live && ch.phase === "hold" ? " tag--accent" : ""}">${tl.phaseText}</span>
        <span class="t2 num xs">${SS.challengeModel.ymdText(ch.challenge_date)} · ${tl.roundText}</span>
      </div>
      <div class="ch-status__count">
        <span class="t2 sm">${tl.fast ? "当前" : tl.nextLabel || (ch.status === "running" ? "阶段" : "状态")}</span>
        <span class="num ch-status__big" data-cd="next">${tl.big || "—"}</span>
      </div>
      ${tl.fast && tl.hint ? html`<p class="t2 xs" data-role="hint">${tl.hint}</p>` : ""}
      ${UI().roundBarHtml(tl.bar)}
      ${tl.closes ? html`<p class="t2 xs">本轮作答截止还有 <span class="num" data-cd="closes">${tl.closes.text}</span></p>` : ""}
    </section>`;
  }

  /** 本人未参加：说明 + 参加按钮（primaryAction 决定是否可点） */
  function enterHtml(ch, action) {
    return html`<section class="card ch-enter">
      <h2 class="card__title">你还没有参加今天的挑战</h2>
      <p class="t2 sm">参加后会切换到挑战存档：资金与其它存档分开，行情与全服一致，不能暂停或跳过。</p>
      ${action.kind === "enter"
        ? html`<button type="button" class="btn btn-primary btn-block btn-lg" data-action="enter">${action.label}</button>`
        : html`<button type="button" class="btn btn-block btn-lg" disabled>${action.label || "今日挑战已结束"}</button>`}
    </section>`;
  }

  function roundCardHtml(ch, cur, draft) {
    const answered = !!(cur.my_answers && cur.my_answers.length);
    return html`<section class="ch-round" data-role="round">
      ${PC().render(cur, draft, {
        kicker: `第 ${cur.round_index} 轮 · 共 ${ch.rounds_total} 轮`,
        note: NOTE,
        submitLabel: answered ? "更新答案" : "提交答案",
        skip: false,
      })}
      <p class="t2 xs ch-round__status" data-role="status">${answered ? `已提交 · 第 ${cur.my_revision} 次作答，截止前可修改` : "尚未作答"}</p>
    </section>`;
  }

  /** 本场各轮（回合记录 + 回合卡）；当前可作答的回合由 roundCardHtml 单独呈现，这里跳过 */
  function roundsListHtml(ch, cards, skipCurrent) {
    return ch.rounds.map((row) => {
      const card = cards.find((c) => c.round_index === row.round_index) || null;
      if (skipCurrent && row.state === "open" && card && card.questions && card.questions.length) return "";
      if (row.state === "pending") {
        return html`<article class="card ch-row is-pending"><div class="ch-row__head"><span class="num t2 xs">第 ${row.round_index} 轮</span><span class="t2 xs">${UI().roundStateText("pending")}</span></div><p class="t2 xs">约 ${M().clockText(row.resume_at)} 开始</p></article>`;
      }
      const answered = !!(card && card.my_answers && card.my_answers.length);
      const crowd = card ? M().crowdText(card) : null;
      return html`<article class="card ch-row">
        <div class="ch-row__head"><span class="num t2 xs">第 ${row.round_index} 轮</span><span class="t2 xs">${UI().roundStateText(row.state)}</span></div>
        <h3 class="ch-row__title">${card && card.event ? card.event.title : "事件待揭晓"}</h3>
        ${answered ? UI().answerHtml(card) : html`<p class="t2 xs">${ch.my_entry ? "本轮未作答" : "未参加"}</p>`}
        ${row.state === "resolved" && card ? UI().resultHtml(card) : ""}
        <div class="ch-row__foot">${card ? UI().roundScoreHtml(card) : ""}${crowd ? html`<span class="t2 xs">${crowd}</span>` : ""}</div>
      </article>`;
    });
  }

  function pastHtml(list) {
    if (!list || !list.length) return "";
    return html`<section class="ch-past">
      <h2 class="ch-past__title">往期挑战</h2>
      ${list.map((c) => {
        const r = c.my_entry && c.my_entry.result;
        return html`<a class="card ch-past__row" href="#/challenge/${c.id}/review">
          <span>${SS.challengeModel.ymdText(c.challenge_date)}</span>
          <span class="t2 xs">${r ? `第 ${r.rank == null ? "—" : r.rank} 名 · ${r.total_score} 分` : "未参加"}</span>
          <span class="t2" aria-hidden="true">›</span>
        </a>`;
      })}
    </section>`;
  }

  function render(view) {
    const drafts = new Map(); // `${挑战id}:${回合}` → 草稿（页面内存，离开即丢）
    let past = null;
    let lastRefresh = 0;
    let busy = false;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">每日挑战</h1>
          <a class="topbar__link" href="#/challenge/board">排行</a>
        </header>
        <div class="ch-page" data-role="body"></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    function draftFor(ch, cur) {
      const key = `${ch.id}:${cur.round_index}`;
      if (!drafts.has(key)) drafts.set(key, PC().initialDraft(cur));
      return drafts.get(key);
    }

    async function submit(ch, cur, answers, st, root) {
      if (busy) return;
      busy = true;
      PC().setBusy(st, true);
      try {
        await store().answerChallengeRound(ch.id, cur.round_index, answers);
        SS.toast("已提交，截止前可以修改", { duration: 1600 });
        busy = false;
        SS.challengeFlow.refresh();
      } catch (err) {
        busy = false;
        const code = err && err.code;
        if (code === "VALIDATION_ERROR") PC().showErr(root, "答案不完整或不合法，请检查每一题后重试");
        else if (code === "CHALLENGE_ROUND_CLOSED") {
          SS.toast("本回合已截止", { icon: null, duration: 1800 });
          SS.challengeFlow.refresh();
          return;
        } else if (code === "CHALLENGE_ANSWER_LIMIT") SS.toast("修改次数已用完", { icon: null, duration: 1800 });
        else if (code === "CHALLENGE_NOT_ENTERED") {
          SS.toast("你还没有参加这场挑战", { icon: null, duration: 1800 });
          SS.challengeFlow.refresh();
          return;
        } else store().notifyError(err);
        PC().setBusy(st, false);
      }
    }

    function draw() {
      const el = body();
      if (!el) return;
      const st = store().state.challenge;
      if (!st.loaded) {
        return SS.mount(el, html`<section class="card"><div class="skeleton" style="height:120px"></div></section>`);
      }
      if (st.error === "FEATURE_UNAVAILABLE") {
        return SS.mount(el, SS.soonCardHtml({ title: "每日挑战", desc: "全服同一份行情和事件，每天几轮预测与交易，晚上统一结算排名。" }));
      }
      const ch = st.today;
      if (!ch) {
        return SS.mount(el, html`<section class="card"><h2 class="card__title">今日挑战未生成</h2><p class="t2 sm">稍后再来看看。</p></section>${pastHtml(past)}`);
      }
      const now = Date.now();
      const tl = M().timeline(ch, st.skew, now);
      const cards = st.cards[ch.id] || [];
      const cur = ch.round_index ? cards.find((c) => c.round_index === ch.round_index) || null : null;
      const mine = !!ch.my_entry;
      const action = M().primaryAction(ch, { now, skew: st.skew, cards });

      let interactive = null;
      if (ch.status === "running" && mine && cur && cur.state === "open" && cur.questions && cur.questions.length) {
        interactive = cur;
      }

      SS.mount(
        el,
        html`${statusHtml(ch, tl)}
          ${ch.status === "running" && !mine ? enterHtml(ch, action) : ""}
          ${ch.status === "scheduled" ? html`<section class="card"><h2 class="card__title">${M().clockText(ch.starts_at)} 开赛</h2><p class="t2 sm">开赛后就可以参加，行情与全服一致。</p></section>` : ""}
          ${interactive ? roundCardHtml(ch, interactive, draftFor(ch, interactive)) : ""}
          ${mine && ch.status === "running" ? html`<a class="btn btn-ghost btn-block btn-lg" href="#/market">去交易</a>` : ""}
          ${ch.status === "settled" && mine ? html`<a class="btn btn-ghost btn-block btn-lg" href="#/challenge/${ch.id}/review">查看复盘</a>` : ""}
          <section class="ch-rounds"><h2 class="ch-past__title">本场各轮</h2>${roundsListHtml(ch, cards, !!interactive)}</section>
          ${pastHtml(past)}`
      );

      if (interactive) {
        const root = SS.$('[data-role="round"]', el);
        const st2 = { busy: false };
        PC().bind(root, interactive, draftFor(ch, interactive), st2, {
          onSubmit: (answers) => submit(ch, interactive, answers, st2, root),
        });
      }
    }

    const onClick = (e) => {
      const b = e.target.closest('[data-action="enter"]');
      if (!b || b.disabled) return;
      b.disabled = true;
      SS.challengeFlow.enter(store().state.challenge.today.id);
    };
    const el0 = view;
    el0.addEventListener("click", onClick);

    const unsub = store().on("challenge:update", draw);
    const timer = setInterval(() => {
      const st = store().state.challenge;
      const ch = st.today;
      if (!ch || !body()) return;
      const now = Date.now();
      const tl = M().timeline(ch, st.skew, now);
      const next = SS.$('[data-cd="next"]', view);
      if (next) next.textContent = tl.big || "—";
      const hint = SS.$('[data-role="hint"]', view);
      if (hint) hint.textContent = tl.hint;
      const closes = SS.$('[data-cd="closes"]', view);
      if (closes && tl.closes) closes.textContent = tl.closes.text;
      if (SS.challengeFlow.needsRefresh(tl, lastRefresh, now)) {
        lastRefresh = now;
        SS.challengeFlow.refresh();
      }
    }, 1000);

    store()
      .listChallenges({ limit: 10 })
      .then((r) => {
        past = r.items.filter((c) => c.status === "settled");
        draw();
      })
      .catch(() => {});

    draw();
    SS.challengeFlow.refresh();

    return () => {
      clearInterval(timer);
      unsub();
      el0.removeEventListener("click", onClick);
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.challenge = { tab: null, render };
})();
