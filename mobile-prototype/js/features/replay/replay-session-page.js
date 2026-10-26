/**
 * 复盘会话（#/replay/:id，SS.pages.replaySession，二级页）：四阶段手动推进、匿名股票与缩放价格、当日消息、
 * 只按当前阶段价格（开盘价 / 收盘价）成交、预测题（复用 SS.predictionCard，抽屉作答）。
 *   - 推进：next_phase（主按钮）与 next_day（次按钮）；expected_tick = 当前 tick，过期则服务端 stale → 重新拉取。
 *   - 未答题越过截止 → REPLAY_PREDICTION_PENDING：toast 并直接打开该题。
 *   - 结算（最后一个盘后再推进，或提前结束）→ 跳到揭示页（replace）。
 * 不连 WS；每次状态变化整体重拉（reqSeq 丢弃过期响应）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const U = () => SS.replayUi;
  const M = () => SS.replayModel;
  const store = () => SS.store;
  const PHASE_TIME = { pre_open: "09:00", open: "09:30", close: "15:00", post_close: "16:00" };

  function render(view, params) {
    const saveId = params.id;
    let alive = true;
    let busy = false;
    let confirmFinish = false;
    let reqSeq = 0;
    let stockCode = null;
    let st = null; // { sess, mk, pf, feed, questions, stock }

    SS.mount(
      view,
      html`<header class="topbar replay-topbar">
          <a class="icon-btn" href="#/replay" aria-label="返回">${SS.icon("back")}</a>
          <h1 class="topbar__title replay-topbar__title" data-role="ttl">真实复盘</h1>
          <span class="num t2 xs" data-role="day"></span>
        </header>
        <div class="replay-page" data-role="body"><div class="skeleton" style="height:44px;margin-top:8px"></div><div class="skeleton" style="height:180px;margin-top:12px;border-radius:18px"></div></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    const navigateReveal = () => SS.router.replace(`/replay/${saveId}/reveal`);

    function handleErr(err) {
      if (!alive) return;
      if (err && err.code === "FEATURE_UNAVAILABLE") return SS.mount(body(), SS.soonCardHtml({ title: "真实复盘", desc: "回到真实历史，股票名已隐去" }));
      if (err && err.code === "REPLAY_SESSION_SETTLED") return navigateReveal();
      if (err && err.code === "SAVE_NOT_FOUND") {
        return SS.mount(body(), html`<div class="empty"><div class="empty__title">复盘存档不存在</div><a class="btn btn-sm" href="#/replay">回到关卡</a></div>`);
      }
      store().notifyError(err);
    }

    /** 拉取页面需要的全部数据；结算后返回 { settled: true } */
    async function fetchAll() {
      const sess = await store().getReplaySession(saveId);
      if (sess.status === "settled") return { settled: true, sess };
      const [mk, pf, fd, qs] = await Promise.all([
        store().loadReplayMarket(saveId),
        store().loadReplayPortfolio(saveId),
        store().getReplayFeed(saveId, { limit: 50 }),
        store().listReplayQuestions(saveId),
      ]);
      if (!mk.stocks.some((s) => s.code === stockCode)) stockCode = mk.stocks[0] && mk.stocks[0].code;
      const stock = await store().loadReplayStock(saveId, stockCode);
      return { sess, mk, pf, feed: fd.items, questions: qs.items, stock };
    }

    async function refresh() {
      const my = ++reqSeq;
      const out = await fetchAll();
      if (!alive || my !== reqSeq) return;
      if (out.settled) return navigateReveal();
      st = out;
      draw();
    }
    const refreshSafe = () => refresh().catch(handleErr);

    function codeOfName(name) {
      const s = st && st.mk.stocks.find((x) => x.name === name);
      return s ? s.code : name;
    }

    function draw() {
      if (!alive || !st) return;
      const { sess, mk, pf, feed, questions, stock } = st;
      const quote = stock;
      const phase = sess.phase;
      // 停牌（任何阶段）直接禁用买卖并标注；标志来自 StockMarketOut.suspended（服务端 replay_flags）
      const suspended = !!quote.suspended;
      const tradable = M().canTrade(phase, quote);
      const basis = M().basisText(phase);
      const holding = pf.holdings.find((h) => h.code === quote.code) || null;
      const sellable = holding ? holding.sellable_quantity : 0;
      const sellWhy = M().sellBlockedText(phase, quote, holding, sellable);
      const today = feed.filter((x) => x.trading_day === sess.day_idx);
      const nextLabel = M().nextActionLabel(sess.tick, sess.play_days);
      const ttl = SS.$('[data-role="ttl"]', view);
      const day = SS.$('[data-role="day"]', view);
      if (ttl) ttl.textContent = sess.level.title;
      if (day) day.textContent = `第 ${sess.day_idx + 1} / ${sess.play_days} 天`;

      SS.mount(
        body(),
        html`<div class="replay-session">
          ${U().phaseStripHtml(phase)}
          <p class="replay-when t2 xs num">${sess.date_label} · ${M().PHASE_LABEL[phase]} ${PHASE_TIME[phase]}${sess.masked ? "" : ` · ${sess.date}`}</p>
          ${U().stockChipsHtml(mk.stocks, quote.code)}
          <section class="card replay-stock">
            ${U().stockHeadHtml(quote, sess.masked, phase)}
            ${U().klineHtml(quote.candles, { playRange: [0, sess.day_idx] })}
            <p class="t2 xs replay-holding num">${holding ? `持有 ${SS.fmt.qty(holding.quantity)} 股 · 可卖 ${SS.fmt.qty(sellable)} 股 · 成本 ${SS.fmt.price(holding.avg_price_cents)}` : "未持有"}</p>
          </section>
          <section class="card replay-feed">
            <h3 class="card__title">${phase === "pre_open" ? "今天盘前看到的消息" : "今天看到的消息"}</h3>
            ${today.length
              ? html`<ul class="replay-feed__list">${today.slice(0, 6).map((it) => U().feedRowHtml(it))}</ul>`
              : html`<p class="t2 sm">今天暂无新消息</p>`}
          </section>
          ${questions.length
            ? html`<section class="card replay-questions">
                <h3 class="card__title">预测题</h3>
                ${questions.map((q) => U().questionRowHtml(q))}
                <p class="t3 xs">答对得积分，不影响你的资金；截止前可以修改答案。</p>
              </section>`
            : ""}
          <section class="card replay-trade">
            <div class="replay-trade__head">
              <span class="t2 sm">${suspended ? "今日停牌，不能买卖" : tradable ? `现在只能按${basis}成交` : M().blockedText(phase)}</span>
              <span class="num xs t2">可用 ${SS.fmt.yuan(pf.cash_cents)}</span>
            </div>
            <div class="replay-trade__btns">
              <button type="button" class="btn replay-btn-buy" data-act="buy" ${tradable ? "" : "disabled"}>${tradable ? `按${basis}买入` : "买入"}</button>
              <div class="replay-sell">
                <button type="button" class="btn" data-act="sell" ${tradable && sellable > 0 ? "" : "disabled"}>卖出</button>
                ${sellWhy ? html`<span class="replay-sell__why t3 xs" data-role="sell-why">${sellWhy}</span>` : ""}
              </div>
            </div>
            ${suspended ? html`<p class="t3 xs">该股票今天停牌，恢复交易后可买卖。</p>` : ""}
          </section>
          <div class="replay-foot" data-role="foot">
            <button type="button" class="btn btn-primary btn-block btn-lg" data-role="next" ${busy ? "disabled" : ""}>${nextLabel}</button>
            <p class="t2 xs replay-foot__note">第 ${sess.play_days} 天结束后揭晓真实走势和股票名称</p>
            <div class="replay-foot__row">
              <button type="button" class="btn-text" data-role="nextday" ${busy ? "disabled" : ""}>跳到下一天</button>
              <button type="button" class="btn-text" data-role="finish" ${busy ? "disabled" : ""}>${confirmFinish ? "再点一次：结束并揭晓" : "提前结束"}</button>
            </div>
          </div>
        </div>`
      );
    }

    async function advance(to) {
      if (busy || !st) return;
      busy = true;
      confirmFinish = false;
      draw();
      try {
        const out = await store().advanceReplay(saveId, { to, expected_tick: st.sess.tick, skip_pending: false });
        if (!alive) return;
        busy = false;
        if (out.session.status === "settled") return navigateReveal();
        if (out.stale) SS.toast("行情已同步，请再确认一次", { icon: null });
        else if (out.scored_question_ids.length) SS.toast("预测已结算，积分已入账", { duration: 2000 });
        else if (out.stopped_reason === "question_open") SS.toast("有新的预测题，先作答再继续", { icon: null, duration: 2000 });
        else if (out.stopped_reason === "question_due") SS.toast("预测题即将截止，先作答", { icon: null, duration: 2000 });
        await refresh();
      } catch (err) {
        if (!alive) return;
        busy = false;
        if (err && err.code === "REPLAY_PREDICTION_PENDING") {
          SS.toast(store().errorText(err.code), { icon: null, duration: 2200 });
          await refresh().catch(handleErr);
          const id = (err.params && err.params.question_ids || [])[0];
          if (id) openQuestion(id);
          return;
        }
        handleErr(err);
        draw();
      }
    }

    async function finish() {
      if (busy) return;
      busy = true;
      draw();
      try {
        await store().finishReplay(saveId);
        if (alive) navigateReveal();
      } catch (err) {
        if (!alive) return;
        busy = false;
        confirmFinish = false;
        handleErr(err);
        draw();
      }
    }

    function openOrder(side) {
      if (!st) return;
      const holding = st.pf.holdings.find((h) => h.code === st.stock.code) || null;
      SS.replayOrder.open({
        saveId,
        quote: st.stock,
        phase: st.sess.phase,
        side,
        cash_cents: st.pf.cash_cents,
        sellable: holding ? holding.sellable_quantity : 0,
        holdingQty: holding ? holding.quantity : 0,
        onDone: refreshSafe,
      });
    }

    function openQuestion(qid) {
      const q = st && st.questions.find((x) => x.id === qid);
      if (!q) return;
      const nameOf = (code) => {
        const s = st.mk.stocks.find((x) => x.code === code);
        return s ? s.name : code;
      };
      const card = M().predictionCardOf(q, saveId, nameOf);
      const draft = SS.predictionCard.draftFor(card);
      SS.sheet.open({
        title: "",
        className: "sheet-layer--tall sheet-layer--pred",
        render(root, api) {
          const sst = { api, card, draft, busy: false, root };
          SS.mount(
            root,
            SS.predictionCard.render(card, draft, {
              kicker: `第 ${q.opens.day_idx + 1} 天 · 预测题`,
              note: "答对得积分，不影响你的资金。截止前可以修改，以最后一次为准。",
              submitLabel: q.my_answer ? "更新答案" : "提交答案",
              skip: false,
            })
          );
          SS.predictionCard.bind(root, card, draft, sst, {
            onSubmit: (answers) => submitAnswer(q, answers, sst, api),
          });
        },
      });
    }

    async function submitAnswer(q, answers, sst, api) {
      const payload = answers.dir ? { probs: answers.dir.probs } : { order: (answers.rank.order || []).map(codeOfName) };
      SS.predictionCard.setBusy(sst, true);
      try {
        await store().answerReplayQuestion(saveId, q.id, payload);
        api.close();
        SS.toast("已提交，截止前可以修改", { duration: 1800 });
        refreshSafe();
      } catch (err) {
        if (!alive) return;
        if (err && (err.code === "REPLAY_QUESTION_CLOSED" || err.code === "REPLAY_SESSION_SETTLED")) {
          api.close();
          SS.toast(store().errorText(err.code), { icon: null, duration: 2000 });
          refreshSafe();
          return;
        }
        SS.predictionCard.setBusy(sst, false);
        if (err && err.code === "VALIDATION_ERROR") SS.predictionCard.showErr(sst.root, "答案不完整或不合法，请检查每一题后重试");
        else store().notifyError(err);
      }
    }

    async function selectStock(code) {
      stockCode = code;
      try {
        const stock = await store().loadReplayStock(saveId, code);
        if (!alive || stockCode !== code || !st) return;
        st.stock = stock;
        draw();
      } catch (err) {
        handleErr(err);
      }
    }

    const onClick = (e) => {
      const t = e.target;
      const stockBtn = t.closest("[data-stock]");
      if (stockBtn) return selectStock(stockBtn.dataset.stock);
      const act = t.closest("[data-act]");
      if (act && !act.disabled) return openOrder(act.dataset.act);
      const q = t.closest("[data-q]");
      if (q) return openQuestion(q.dataset.q);
      if (t.closest('[data-role="next"]')) return advance("next_phase");
      if (t.closest('[data-role="nextday"]')) return advance("next_day");
      if (t.closest('[data-role="finish"]')) {
        if (!confirmFinish) {
          confirmFinish = true;
          return draw();
        }
        return finish();
      }
    };
    view.addEventListener("click", onClick);

    /** 首次加载失败：没有任何数据时整页给出重试，不留骨架屏 */
    const loadFirst = () =>
      refresh().catch((err) => {
        if (!alive) return;
        if (st || (err && (err.code === "FEATURE_UNAVAILABLE" || err.code === "SAVE_NOT_FOUND" || err.code === "REPLAY_SESSION_SETTLED"))) return handleErr(err);
        SS.mount(
          body(),
          html`<div class="empty"><div class="empty__title">${store().errorText(err && err.code)}</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`
        );
        SS.$('[data-role="retry"]', body()).addEventListener("click", loadFirst);
      });
    loadFirst();
    return () => {
      alive = false;
      view.removeEventListener("click", onClick);
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.replaySession = { tab: null, render };
})();
