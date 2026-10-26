/**
 * 预测卡弹层（对照 Predict 画板）：SS.predictionCard
 *   open(cardId)        拉取卡片并弹出（同卡已开则忽略；卡已不是 open 则只刷新状态）
 *   isOpen(cardId)      当前弹层是否为该卡
 *   refreshOverlay()    按缓存的待答卡刷新交易状态栏的 overlay（收起时显示“去作答”，弹层打开时清除）
 *   render(card, draft) → SafeHtml（弹层内容）；bind(root, card, draft, st) 绑定交互
 * 草稿按卡片 id 保存在内存里：收起后再打开保留选择。提交 = answerPrediction(resume=true)；“这张不答” = skipPrediction(resume=true)。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const PM = SS.predictMath;
  const M = SS.predictModel;
  const store = () => SS.store;
  const drafts = new Map();
  let cur = null; // { id, api, busy } —— 当前打开的弹层
  const KIND_TEXT = { announcement: "公告", news: "新闻", policy: "政策", sudden: "突发", rumor: "传闻" };

  function initialDraft(card) {
    const d5 = PM.confRange(5);
    const d2 = PM.confRange(2);
    const d = { dir: { pick: null, conf: d5.def }, rank: { order: [] }, rumor: { pick: null, conf: d2.def } };
    const a = M.aOf(card, "dir");
    if (a && a.probs) {
      d.dir.pick = PM.argmaxPick(a.probs);
      d.dir.conf = Math.max(...a.probs);
    }
    const r = M.aOf(card, "rank");
    if (r && r.order) d.rank.order = r.order.slice();
    const u = M.aOf(card, "rumor");
    if (u && u.probs) {
      d.rumor.pick = PM.argmaxPick(u.probs);
      d.rumor.conf = Math.max(...u.probs);
    }
    return d;
  }
  const draftFor = (card) => {
    if (!drafts.has(card.id)) drafts.set(card.id, initialDraft(card));
    return drafts.get(card.id);
  };

  /**
   * 弹层主体（也被挑战回合页内联复用）。opts（均可缺省）：
   *   kicker 标签文字（缺省“第 N 个交易日”）；note 底部说明；submitLabel 提交按钮文字；skip=false 不显示“这张不答”
   */
  function render(card, draft, opts = {}) {
    const qs = M.sortQuestions(card.questions);
    const rev = M.revealDay(card);
    const ev = card.event;
    const day = card.opened_trading_day != null ? SS.fmt.dayNo(card.opened_trading_day) : null;
    const kicker = opts.kicker != null ? opts.kicker : day != null ? `第 ${day} 个交易日` : "";
    const r5 = PM.confRange(5);
    const r2 = PM.confRange(2);
    let i = 0;
    const blocks = qs.map((q) => {
      i += 1;
      if (q.qid === "dir") {
        const labels = PM.bucketLabels(q.edges_bp);
        return html`<section class="pred-q" data-qid="dir">
          <h3 class="pred-q__title">${M.dirTitle(q, i)}</h3>
          <div class="pred-seg" role="group" aria-label="涨跌档位">
            ${labels.map((l, k) => html`<button type="button" class="pred-seg__opt num" data-q="dir" data-pick="${k}" aria-pressed="false">${l}</button>`)}
          </div>
          <div class="pred-conf">
            <label class="t2 pred-conf__label" for="pred-conf-dir">把握</label>
            <input id="pred-conf-dir" class="pred-slider" type="range" data-q="dir-conf" min="${r5.min}" max="${r5.max}" step="${r5.step}" value="${draft.dir.conf}" />
            <span class="num pred-conf__val" data-role="dir-conf">${draft.dir.conf}%</span>
          </div>
        </section>`;
      }
      if (q.qid === "rank") {
        const names = (q.candidates || []).filter((x) => x !== q.exclude);
        return html`<section class="pred-q" data-qid="rank">
          <h3 class="pred-q__title">${M.rankTitle(q, i)}</h3>
          <div class="pred-chips">
            ${names.map((name) => html`<button type="button" class="pred-chip" data-q="rank" data-name="${name}" aria-pressed="false"><span class="pred-chip__rk" data-role="rk" hidden></span>${name}</button>`)}
          </div>
        </section>`;
      }
      return html`<section class="pred-q" data-qid="rumor">
        <h3 class="pred-q__title">${M.rumorTitle(i)}</h3>
        <div class="pred-seg pred-seg--2" role="group" aria-label="传闻走向">
          <button type="button" class="pred-seg__opt" data-q="rumor" data-pick="0" aria-pressed="false">会被辟谣</button>
          <button type="button" class="pred-seg__opt" data-q="rumor" data-pick="1" aria-pressed="false">会被证实</button>
        </div>
        <div class="pred-conf">
          <label class="t2 pred-conf__label" for="pred-conf-rumor">把握</label>
          <input id="pred-conf-rumor" class="pred-slider" type="range" data-q="rumor-conf" min="${r2.min}" max="${r2.max}" step="${r2.step}" value="${draft.rumor.conf}" />
          <span class="num pred-conf__val" data-role="rumor-conf">${draft.rumor.conf}%</span>
        </div>
      </section>`;
    });
    const note =
      opts.note != null ? opts.note : rev == null ? "答对得积分，不影响你的资金。传闻揭晓后结算。" : `答对得积分，不影响你的资金。第 ${SS.fmt.dayNo(rev)} 个交易日揭晓。`;
    return html`<div class="pred-card">
      <div class="pred-card__head">
        <div class="pred-card__tags">
          ${ev && ev.major ? html`<span class="tag tag--accent">重大</span>` : ""}
          ${ev && KIND_TEXT[ev.kind] ? html`<span class="tag">${KIND_TEXT[ev.kind]}</span>` : ""}
          ${kicker ? html`<span class="t2 num xs">${kicker}</span>` : ""}
        </div>
        <h2 class="pred-card__title">${ev ? ev.title : "重大事件"}</h2>
      </div>
      ${blocks}
      <div class="pred-card__foot">
        <p class="t2 xs pred-card__note">${note}</p>
        <p class="pred-card__err" data-role="err" hidden></p>
        <button type="button" class="btn btn-primary btn-block btn-lg" data-role="submit" disabled>${opts.submitLabel || "提交，继续行情"}</button>
        ${opts.skip === false ? "" : html`<button type="button" class="btn-text" data-role="skip">这张不答</button>`}
      </div>
    </div>`;
  }

  const complete = (card, draft) =>
    M.sortQuestions(card.questions).every((q) => (q.qid === "dir" ? draft.dir.pick != null : q.qid === "rank" ? draft.rank.order.length === 3 : draft.rumor.pick != null));

  /** 按草稿刷新控件状态（不重建 DOM，避免打断滑块拖动） */
  function paint(root, card, draft) {
    SS.$$('[data-q="dir"]', root).forEach((b) => {
      const on = Number(b.dataset.pick) === draft.dir.pick;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    SS.$$('[data-q="rumor"]', root).forEach((b) => {
      const on = Number(b.dataset.pick) === draft.rumor.pick;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const dc = SS.$('[data-role="dir-conf"]', root);
    if (dc) dc.textContent = `${draft.dir.conf}%`;
    const rc = SS.$('[data-role="rumor-conf"]', root);
    if (rc) rc.textContent = `${draft.rumor.conf}%`;
    const full = draft.rank.order.length >= 3;
    SS.$$('[data-q="rank"]', root).forEach((b) => {
      const idx = draft.rank.order.indexOf(b.dataset.name);
      const on = idx >= 0;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
      b.disabled = !on && full;
      const rk = SS.$('[data-role="rk"]', b);
      if (rk) {
        rk.hidden = !on;
        rk.textContent = on ? String(idx + 1) : "";
      }
    });
    const submit = SS.$('[data-role="submit"]', root);
    if (submit) submit.disabled = !complete(card, draft) || (cur && cur.busy);
  }

  function setBusy(st, busy) {
    st.busy = busy;
    const root = st.root || (st.api && st.api.body);
    if (!root) return;
    if (busy) SS.$$("button", root).forEach((b) => (b.disabled = true));
    else paint(root, st.card, st.draft); // 恢复各控件的真实状态（芯片上限、提交可用性）
  }

  function showErr(root, text) {
    const e = SS.$('[data-role="err"]', root);
    if (!e) return;
    e.hidden = !text;
    e.textContent = text || "";
  }

  /** 草稿 → PredictionAnswersIn（02 §10.2）；只包含卡上有的题 */
  function buildAnswers(card, draft) {
    const answers = {};
    if (card.questions.some((q) => q.qid === "dir")) answers.dir = { probs: PM.probsFromPick(draft.dir.pick, draft.dir.conf, 5) };
    if (card.questions.some((q) => q.qid === "rank")) answers.rank = { order: draft.rank.order.slice() };
    if (card.questions.some((q) => q.qid === "rumor")) answers.rumor = { probs: PM.probsFromPick(draft.rumor.pick, draft.rumor.conf, 2) };
    return answers;
  }

  async function submit(st) {
    const { card, draft } = st;
    const answers = buildAnswers(card, draft);
    setBusy(st, true);
    try {
      await store().answerPrediction(card.id, answers, { resume: true });
      drafts.delete(card.id);
      const others = store().state.predict.openCards.some((c) => c.id !== card.id);
      st.api.close();
      SS.toast(others ? "已提交，还有预测卡待答" : "已提交，行情继续", { duration: 1800 });
    } catch (err) {
      if (err && err.code === "PREDICTION_CLOSED") {
        drafts.delete(card.id);
        st.api.close();
        SS.toast("这张预测已截止", { icon: null, duration: 2000 });
        store().ensureCards({ force: true }).catch(() => {});
      } else if (err && err.code === "VALIDATION_ERROR") {
        showErr(st.api.body, "答案不完整或不合法，请检查每一题后重试");
        setBusy(st, false);
      } else {
        store().notifyError(err);
        setBusy(st, false);
      }
    }
  }

  async function skip(st) {
    setBusy(st, true);
    try {
      await store().skipPrediction(st.card.id, { resume: true });
      drafts.delete(st.card.id);
      st.api.close();
      SS.toast("已放弃本张，行情继续", { icon: null, duration: 1800 });
    } catch (err) {
      store().notifyError(err);
      setBusy(st, false);
    }
  }

  /**
   * 绑定交互：点选分段/芯片、拖动把握、提交与不答。
   * handlers 缺省时走弹层流程（answerPrediction / skipPrediction + 关闭弹层）；挑战回合传 { onSubmit(answers) → Promise, skip: false }，
   * 由调用方自己处理提交结果与忙碌态（setBusy）。
   */
  function bindCard(root, card, draft, st, handlers) {
    st.card = card;
    st.draft = draft;
    st.root = root;
    const h = handlers || {};
    root.addEventListener("click", (e) => {
      const seg = e.target.closest("[data-q][data-pick]");
      if (seg && !seg.disabled) {
        SS.haptic(5);
        const k = Number(seg.dataset.pick);
        if (seg.dataset.q === "dir") draft.dir.pick = k;
        else draft.rumor.pick = k;
        return paint(root, card, draft);
      }
      const chip = e.target.closest('[data-q="rank"][data-name]');
      if (chip && !chip.disabled) {
        SS.haptic(5);
        const name = chip.dataset.name;
        const idx = draft.rank.order.indexOf(name);
        if (idx >= 0) draft.rank.order.splice(idx, 1);
        else if (draft.rank.order.length < 3) draft.rank.order.push(name);
        return paint(root, card, draft);
      }
      if (e.target.closest('[data-role="submit"]') && !st.busy && complete(card, draft)) {
        if (!h.onSubmit) return submit(st);
        return h.onSubmit(buildAnswers(card, draft), st);
      }
      if (e.target.closest('[data-role="skip"]') && !st.busy && !h.onSubmit) return skip(st);
    });
    root.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.q === "dir-conf") draft.dir.conf = Number(t.value);
      else if (t.dataset.q === "rumor-conf") draft.rumor.conf = Number(t.value);
      else return;
      paint(root, card, draft);
    });
    paint(root, card, draft);
  }

  /** 弹层打开时清除 overlay；收起时若仍有待答卡则显示“去作答” */
  function refreshOverlay() {
    const open = ((store().state.predict && store().state.predict.openCards) || []).filter((c) => c.status === "open");
    if (!open.length || cur) return SS.tradeBar.setOverlay("predict", null);
    SS.tradeBar.setOverlay("predict", {
      priority: 20,
      statusText: "已暂停",
      nextSub: `有 ${open.length} 张预测卡待答`,
      action: { label: "去作答", run: () => open_(open[0].id) },
    });
  }

  function show(card) {
    const st = { id: card.id, api: null, busy: false, card, draft: draftFor(card) };
    cur = st;
    st.api = SS.sheet.open({
      className: "sheet-layer--tall sheet-layer--pred",
      render(body, api) {
        st.api = api;
        SS.mount(body, render(card, st.draft));
        bindCard(body, card, st.draft, st);
        const banner = SS.el(html`<div class="pred-banner" role="status">${SS.icon("pause")}<span>行情已暂停 · 答完自动继续</span></div>`);
        api.el.parentElement.appendChild(banner);
      },
      onClose() {
        if (cur === st) cur = null;
        refreshOverlay();
      },
    });
  }

  async function open_(cardId) {
    if (isOpen(cardId) || cur) return;
    // 真实复盘页（#/replay*）不被主存档的预测卡打断：复盘与主存档互不相关，卡片留给行情页顶部的“去作答”
    if (/^#\/replay/.test(location.hash)) return refreshOverlay();
    let card;
    try {
      card = await store().loadPrediction(cardId);
    } catch (err) {
      if (err && err.code !== "PREDICTION_NOT_FOUND") store().notifyError(err);
      return refreshOverlay();
    }
    if (card.status !== "open") return refreshOverlay();
    if (cur) return; // 等待期间已有别的卡打开
    show(card);
  }

  const isOpen = (cardId) => !!cur && cur.id === cardId;
  /** 关闭弹层（cardId 缺省则关闭任意一张）：WS 报告已作答/截止/切存档时使用 */
  const close = (cardId) => {
    if (cur && (cardId == null || cur.id === cardId)) cur.api.close();
  };

  SS.predictionCard = {
    render,
    bind: bindCard,
    open: open_,
    isOpen,
    close,
    refreshOverlay,
    // 挑战回合页复用的草稿与忙碌态
    initialDraft,
    draftFor,
    buildAnswers,
    setBusy,
    showErr,
    paint,
    complete,
  };
  SS.components = SS.components || {};
  SS.components.predictionCard = SS.predictionCard;
})();
