/**
 * 复盘下单抽屉（SS.replayOrder.open）：只按当前阶段价格（开盘价 / 收盘价）市价成交。
 * 数量按 100 股步进；“1/4 · 1/2 · 3/4 · 全仓”按可买（买入）或可卖（卖出）计算；预估金额与手续费只做预览，成交以服务端为准。
 * 成功后 onDone() 通知页面刷新；失败保留抽屉并按错误码给 toast（T+1、封板、停牌等）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.replayModel;

  /**
   * opts: { saveId, quote（当前阶段的报价）, phase, side, cash_cents, sellable, holdingQty, onDone }
   */
  function open(opts) {
    const { saveId, quote, phase, side, cash_cents: cash, sellable = 0, holdingQty = 0, onDone } = opts;
    const buy = side === "buy";
    const basis = M().basisText(phase);
    const price = quote.price_cents;
    const maxQty = buy ? M().maxBuyQty(cash, price) : sellable;
    const unit = M().LOT;
    let qty = 0;
    let stepper = null;
    let busy = false;

    SS.sheet.open({
      title: buy ? "买入" : "卖出",
      className: "sheet-layer--replay-order",
      render(body, api) {
        SS.mount(
          body,
          html`<div class="replay-order" data-role="order">
            <div class="replay-order__stock">
              <span class="replay-order__name">${quote.name}</span>
              <span class="t2 xs num">${quote.code}</span>
            </div>
            <p class="replay-order__basis t2 sm">按${basis}成交 <span class="num ${SS.fmt.trend(quote.change_bp)}">${SS.fmt.price(price)}</span></p>
            <div class="field">
              <div class="field__label"><span>数量（股）</span><span class="xs t3 num">${buy ? `可用 ${SS.fmt.yuan(cash)}` : `可卖 ${SS.fmt.qty(sellable)} 股 · 持有 ${SS.fmt.qty(holdingQty)}`}</span></div>
              <div class="stepper" data-role="qty">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="减少 ${unit} 股">${SS.icon("minus")}</button>
                <input class="num" inputmode="numeric" aria-label="数量" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="增加 ${unit} 股">${SS.icon("plus")}</button>
              </div>
              <div class="chips" data-role="chips">
                ${[["1/4", 0.25], ["1/2", 0.5], ["3/4", 0.75], ["全仓", 1]].map(([t, r]) => html`<button type="button" class="chip" data-ratio="${r}">${t}</button>`)}
              </div>
            </div>
            <dl class="replay-order__sum num">
              <div><dt class="t2">成交价</dt><dd>${SS.fmt.price(price)}</dd></div>
              <div><dt class="t2">预估金额</dt><dd data-role="amount">—</dd></div>
              <div><dt class="t2">预估手续费</dt><dd data-role="fee">—</dd></div>
              <div><dt class="t2">${buy ? "预计花费" : "预计到账"}</dt><dd data-role="total">—</dd></div>
            </dl>
            <p class="replay-order__warn t2 xs" data-role="warn" hidden></p>
            <button type="button" class="btn btn-primary btn-block btn-lg" data-role="confirm" disabled>${buy ? "确认买入" : "确认卖出"}</button>
          </div>`
        );
        const root = body;
        const warn = (t) => {
          const w = SS.$('[data-role="warn"]', root);
          w.hidden = !t;
          w.textContent = t || "";
        };
        const paint = () => {
          const est = M().estimateOrder({ side, quantity: qty || 0, price_cents: price });
          SS.$('[data-role="amount"]', root).textContent = qty ? SS.fmt.yuan(est.amount_cents) : "—";
          SS.$('[data-role="fee"]', root).textContent = qty ? SS.fmt.yuan(est.fee_cents) : "—";
          SS.$('[data-role="total"]', root).textContent = qty ? SS.fmt.yuan(est.total_cents) : "—";
          const can = qty > 0 && qty <= maxQty && !busy;
          SS.$('[data-role="confirm"]', root).disabled = !can;
          if (maxQty < unit) warn(buy ? "可用资金不够买一手（100 股）" : sellable === 0 && holdingQty > 0 ? "今日买入的股票明天才能卖出（T+1）" : "没有可卖的持仓");
          else if (qty > maxQty) warn(buy ? "超过可用资金" : "超过可卖数量");
          else warn("");
        };
        stepper = SS.stepper(SS.$('[data-role="qty"]', root), {
          value: 0,
          step: unit,
          min: 0,
          max: Math.max(maxQty, 0),
          display: (v) => (v ? String(v) : ""),
          onChange: (v) => {
            qty = v;
            paint();
          },
        });
        SS.$$("[data-ratio]", root).forEach((b) =>
          b.addEventListener("click", () => {
            const r = Number(b.dataset.ratio);
            stepper.set(Math.min(maxQty, Math.floor((maxQty * r) / unit) * unit));
          })
        );
        SS.$('[data-role="confirm"]', root).addEventListener("click", async () => {
          if (busy || !(qty > 0 && qty <= maxQty)) return;
          busy = true;
          paint();
          try {
            const out = await SS.store.replayOrder(saveId, { code: quote.code, side, quantity: qty });
            SS.toast(`${buy ? "买入" : "卖出"} ${SS.fmt.qty(qty)} 股 · 成交价 ${SS.fmt.price(out.trade.price_cents)}`, { duration: 2200 });
            api.close();
            onDone && onDone(out);
          } catch (err) {
            busy = false;
            paint();
            SS.store.notifyError(err);
          }
        });
        paint();
      },
    });
  }

  SS.replayOrder = { open };
})();
