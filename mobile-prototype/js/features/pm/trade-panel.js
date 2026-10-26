/**
 * 合约详情的买卖面板（SS.pmTrade.mount(host, {onDone}) → {render, setOutcome, refreshQuote, destroy}）。
 *   - 买入/卖出两种模式：主按钮提交当前方向，次按钮切换到另一方向（与画板的“买入 / 卖出”一致）。
 *   - 份数用 .stepper（1–200；卖出时上限为持有份额）；改份数或方向后 300 ms 防抖请求 quote。
 *   - 滑点保护（04 §5.4）：提交时带 max_cost_points = ceil(报价·1.02)（卖出 min_proceeds_points = floor(报价·0.98)）；
 *     PM_SLIPPAGE_EXCEEDED → 自动重新报价并提示“价格已变动，请确认”，不自动重提。
 *   - Idempotency-Key 由 store 的真实版生成；mock 不需要。
 *   - 市场非 open：显示结果或“已停止交易”，不出买卖控件。
 * 数字区（预计花费/回款、滑点、持仓）只改文字，不重建整块面板，避免打断点按。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.pmModel;
  const store = () => SS.store;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function mount(host, { onDone } = {}) {
    const S = { market: null, outcome: 0, side: "buy", shares: 1, quote: null, quoteErr: null, reqSeq: 0, timer: null, busy: false, alive: true, stepper: null };

    const heldOf = (m, i) => M().positionOf(m.my, i).shares;
    const costOfHeld = (m, i) => M().positionOf(m.my, i).cost_points;
    const labelOf = (m, i) => M().outcomeLabels(m)[i] || "";
    const maxSharesOf = (m) => (S.side === "sell" ? clamp(heldOf(m, S.outcome), 1, M().MAX_SHARES) : M().MAX_SHARES);

    function requestQuote(delay = 300) {
      clearTimeout(S.timer);
      const seq = ++S.reqSeq;
      S.quote = null;
      S.quoteErr = null;
      patchQuote();
      if (!S.market || S.market.status !== "open") return;
      const m = S.market;
      if (S.side === "sell" && heldOf(m, S.outcome) < 1) return; // 没有持仓不报价（服务端会 422）
      S.timer = setTimeout(async () => {
        try {
          const q = await store().quotePredictionMarket(m.id, { side: S.side, outcome: S.outcome, shares: S.shares });
          if (!S.alive || seq !== S.reqSeq) return;
          S.quote = q;
        } catch (err) {
          if (!S.alive || seq !== S.reqSeq) return;
          S.quoteErr = err;
        }
        patchQuote();
      }, delay);
    }

    /** 只改数字与按钮状态 */
    function patchQuote() {
      if (!S.alive || !S.market || !host.querySelector(".pm-trade")) return;
      const m = S.market;
      const q = S.quote;
      const set = (role, text) => {
        const el = host.querySelector(`[data-role="${role}"]`);
        if (el) el.textContent = text;
      };
      set("points", q ? `${q.points} 积分` : S.quoteErr ? "—" : "报价中…");
      set("slip", q ? (S.side === "buy" ? `最多 ${M().slippageLimit(q.points, "buy")} 积分` : `最少 ${M().slippageLimit(q.points, "sell")} 积分`) : "—");
      set("slip-label", S.side === "buy" ? "滑点保护（+2%）" : "滑点保护（−2%）");
      const held = heldOf(m, S.outcome);
      const noHold = S.side === "sell" && held < 1;
      const err = noHold ? "没有可卖的份额" : S.quoteErr ? store().errorText(S.quoteErr.code) : "";
      const errEl = host.querySelector('[data-role="err"]');
      if (errEl) {
        errEl.textContent = err;
        errEl.hidden = !err;
      }
      const go = host.querySelector('[data-role="go"]');
      if (go) go.disabled = S.busy || !q || noHold;
      const alt = host.querySelector('[data-role="alt"]');
      if (alt) alt.disabled = S.busy;
    }

    async function submit() {
      if (S.busy || !S.market || !S.quote) return;
      const m = S.market;
      const q = S.quote;
      const body =
        S.side === "buy"
          ? { side: "buy", outcome: S.outcome, shares: S.shares, max_cost_points: M().slippageLimit(q.points, "buy") }
          : { side: "sell", outcome: S.outcome, shares: S.shares, min_proceeds_points: M().slippageLimit(q.points, "sell") };
      S.busy = true;
      patchQuote();
      try {
        const res = await store().tradePredictionMarket(m.id, body);
        if (!S.alive) return;
        const t = res.trade;
        SS.toast(t.side === "buy" ? `已买入 ${t.shares} 份，花费 ${t.points} 积分` : `已卖出 ${t.shares} 份，回款 ${t.points} 积分`, { duration: 2000 });
        SS.haptic(10);
        onDone && onDone(res);
      } catch (err) {
        if (!S.alive) return;
        if (err && err.code === "PM_SLIPPAGE_EXCEEDED") {
          SS.toast("价格已变动，请确认新的报价", { icon: null, duration: 2200 });
          requestQuote(0);
        } else store().notifyError(err);
      } finally {
        S.busy = false;
        patchQuote();
      }
    }

    function drawOpen(m) {
      const label = labelOf(m, S.outcome);
      const held = heldOf(m, S.outcome);
      const cost = costOfHeld(m, S.outcome);
      const holdText = held > 0 ? `已持有 “${label}” ${held} 份，成本 ${cost} 积分` : `尚未持有 “${label}”`;
      const lim = m.limits || {};
      const limitText = `本场已投入 ${Math.max(0, lim.market_net_cost_used_points || 0)} / 上限 ${lim.market_net_cost_cap_points || 0} 积分`;
      const buy = S.side === "buy";
      SS.mount(
        host,
        html`<section class="card pm-trade" data-side="${S.side}">
          <div class="pm-trade__head">
            <span class="pm-trade__title">${buy ? "买入" : "卖出"} “${label}”</span>
            <span class="t2 xs num">可用 ${m.balance_points} 积分</span>
          </div>
          <div class="stepper pm-trade__qty">
            <button type="button" class="stepper__btn" data-step="-1" aria-label="减少份数">${SS.icon("minus")}</button>
            <input type="text" inputmode="numeric" aria-label="份数" />
            <button type="button" class="stepper__btn" data-step="1" aria-label="增加份数">${SS.icon("plus")}</button>
          </div>
          <div class="pm-trade__rows">
            <div class="pm-trade__row"><span class="t2">${buy ? "预计花费" : "预计回款"}</span><span class="num" data-role="points">报价中…</span></div>
            ${buy ? html`<div class="pm-trade__row"><span class="t2">猜中可兑付</span><span class="num" data-role="payout">${S.shares * M().SHARE_POINTS} 积分</span></div>` : ""}
            <div class="pm-trade__row"><span class="t2" data-role="slip-label"></span><span class="num" data-role="slip">—</span></div>
          </div>
          <p class="t2 xs pm-trade__hold">${holdText}</p>
          <p class="t3 xs">${limitText}</p>
          <p class="pm-trade__err t2 xs" data-role="err" hidden></p>
          <div class="pm-trade__actions">
            <button type="button" class="btn btn-primary btn-lg pm-trade__go" data-role="go" disabled>${buy ? "买入" : "卖出"}</button>
            <button type="button" class="btn btn-lg pm-trade__alt" data-role="alt">${buy ? "卖出" : "买入"}</button>
          </div>
        </section>`
      );
      const el = host.querySelector(".stepper");
      S.stepper = SS.stepper(el, {
        value: S.shares,
        step: 1,
        min: 1,
        max: maxSharesOf(m),
        display: (n) => `${n} 份`,
        parse: (s) => parseInt(s, 10),
        onChange: (v) => {
          S.shares = v;
          const pay = host.querySelector('[data-role="payout"]');
          if (pay) pay.textContent = `${v * M().SHARE_POINTS} 积分`;
          requestQuote();
        },
      });
      host.querySelector('[data-role="go"]').addEventListener("click", submit);
      host.querySelector('[data-role="alt"]').addEventListener("click", () => {
        S.side = buy ? "sell" : "buy";
        S.shares = clamp(S.shares, 1, maxSharesOf(m));
        render(m, S.outcome);
      });
      requestQuote(0);
    }

    function drawClosed(m) {
      const label = labelOf(m, S.outcome);
      let text;
      if (m.status === "resolved") {
        const win = m.winning_outcome;
        const mine = M().positionOf(m.my, win).shares;
        const payout = mine * M().SHARE_POINTS;
        text = `结果：${labels(m)[win] || ""} · ${mine ? `你的兑付 ${payout} 积分` : "你没有持有获胜选项"}`;
      } else if (m.status === "voided") text = "本市场已作废，持仓按净投入退款";
      else text = M().closeText(m);
      const held = heldOf(m, S.outcome);
      SS.mount(
        host,
        html`<section class="card pm-trade pm-trade--closed">
          <div class="pm-trade__head"><span class="pm-trade__title">市场状态</span><span class="tag">${M().statusText(m.status)}</span></div>
          <p class="pm-trade__result">${text}</p>
          ${held > 0 ? html`<p class="t2 xs">你持有 “${label}” ${held} 份，成本 ${costOfHeld(m, S.outcome)} 积分</p>` : ""}
        </section>`
      );
    }

    function labels(m) {
      return M().outcomeLabels(m);
    }

    function render(market, outcome) {
      S.market = market;
      if (outcome != null) S.outcome = clamp(outcome, 0, market.outcomes.length - 1);
      if (market.status !== "open") {
        S.quote = null;
        clearTimeout(S.timer);
        drawClosed(market);
        return;
      }
      S.shares = clamp(S.shares, 1, maxSharesOf(market));
      drawOpen(market);
    }

    return {
      render,
      setOutcome(i) {
        if (S.market) render(S.market, i);
      },
      /** 行情推送后刷新报价（只在 open 时请求） */
      refreshQuote() {
        if (S.market && S.market.status === "open" && !S.busy) requestQuote(300);
      },
      destroy() {
        S.alive = false;
        clearTimeout(S.timer);
        host.innerHTML = "";
      },
    };
  }

  SS.pmTrade = { mount };
})();
