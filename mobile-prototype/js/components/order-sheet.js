/**
 * 下单抽屉（OrderIn：code, side, quantity, price_type, limit_price_cents）。
 * 可从任意位置调用：SS.orderSheet.open({ code, side: "buy"|"sell", quantity? })
 *
 * 设计取舍：
 *   - 买/卖切换放在最上方，切换后快捷仓位与“可用”信息随之变化；
 *   - 默认市价单，限价单才展开价格步进（±0.01 元，长按连跳），并提示涨跌停区间；
 *   - 数量按交易单位（trade_unit=100）步进；快捷仓位：买入按可用资金、卖出按可卖股数计算；
 *   - 确认按钮直接写出“买入 300 股 · ¥64,590.00”，减少一次确认弹窗；
 *   - 成交后在抽屉内显示结果，2.4 秒自动收起。
 * 按钮不使用红/绿：红涨绿跌只用于行情数据，买卖动作统一用强调色/中性色区分。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  function open({ code, side = "buy", quantity }) {
    const store = SS.store;
    const fmt = SS.fmt;
    const q = store.quote(code);
    const unit = store.state.save.trade_unit;
    let unsub = null;
    let autoCloseT = null;
    let confirmDev = false; // 后端返回 TRADE_PRICE_DEVIATION_CONFIRM 后，下一次提交带 confirm_deviation

    return SS.sheet.open({
      title: "",
      className: "order-sheet",
      onClose: () => {
        unsub && unsub();
        clearTimeout(autoCloseT);
      },
      render(body, api) {
        SS.mount(
          body,
          html`<div class="order">
            <div class="seg seg--lg" data-role="side">
              <span class="seg__thumb" aria-hidden="true"></span>
              <button type="button" data-value="buy" class="${side === "buy" ? "is-active" : ""}">买入</button>
              <button type="button" data-value="sell" class="${side === "sell" ? "is-active" : ""}">卖出</button>
            </div>

            <div class="order__stock">
              <div>
                <div class="order__name">${q.name}</div>
                <div class="xs t3 num">${q.code} · ${q.industry}</div>
              </div>
              <div class="order__quote">
                <div class="num order__price" data-role="price"></div>
                <div class="num xs" data-role="chg"></div>
              </div>
            </div>

            <div class="field">
              <div class="field__label">
                <span>委托方式</span>
              </div>
              <div class="seg" data-role="ptype">
                <span class="seg__thumb" aria-hidden="true"></span>
                <button type="button" data-value="market" class="is-active">市价</button>
                <button type="button" data-value="limit">限价</button>
              </div>
            </div>

            <div class="field" data-role="limit-field" hidden>
              <div class="field__label">
                <span>委托价（元）</span>
                <span class="xs t3 num" data-role="limits"></span>
              </div>
              <div class="stepper" data-role="limit">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="降低 0.01">${SS.icon("minus")}</button>
                <input class="num" inputmode="decimal" aria-label="委托价" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="提高 0.01">${SS.icon("plus")}</button>
              </div>
            </div>

            <div class="field">
              <div class="field__label">
                <span>数量（股）</span>
                <span class="xs t3" data-role="avail-qty"></span>
              </div>
              <div class="stepper" data-role="qty">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="减少 ${unit} 股">${SS.icon("minus")}</button>
                <input class="num" inputmode="numeric" aria-label="数量" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="增加 ${unit} 股">${SS.icon("plus")}</button>
              </div>
              <div class="chips" data-role="chips">
                ${[
                  ["1/4", 0.25],
                  ["1/2", 0.5],
                  ["3/4", 0.75],
                  ["全仓", 1],
                ].map(([t, f]) => html`<button type="button" class="chip" data-frac="${f}">${t}</button>`)}
              </div>
            </div>

            <dl class="order__summary">
              <div><dt>预估金额</dt><dd class="num" data-role="gross"></dd></div>
              <div><dt>手续费</dt><dd class="num" data-role="fee"></dd></div>
              <div><dt data-role="cash-label">可用资金</dt><dd class="num" data-role="cash"></dd></div>
            </dl>

            <p class="order__error" data-role="error" role="alert"></p>

            <button type="button" class="btn btn-primary btn-block btn-lg" data-role="submit"></button>
          </div>`
        );

        const $ = (r) => SS.$(`[data-role="${r}"]`, body);
        const st = { side, ptype: "market" };
        // 提交产生的错误（placeOrder 失败）：持续显示到用户改输入/切买卖/再次提交；校验类提示（warn）仍随 tick 实时刷新
        let submitErr = "";

        const maxQty = () => {
          if (st.side === "buy") return store.maxBuy(code, st.ptype === "limit" ? limit.get() : q.price_cents);
          const h = store.holding(code);
          return h ? h.sellable_quantity : 0;
        };

        const limit = SS.stepper($("limit"), {
          value: q.price_cents,
          step: 1,
          min: q.limit_down_cents,
          max: q.limit_up_cents,
          display: fmt.toInput,
          parse: fmt.parseYuan,
          onChange: refresh,
        });
        const h0 = store.holding(code);
        const qty = SS.stepper($("qty"), {
          value: quantity || (side === "sell" && h0 ? Math.min(h0.sellable_quantity, unit) || unit : unit),
          step: unit,
          min: 0,
          display: fmt.qty,
          parse: (s) => Number(String(s).replace(/[^\d]/g, "")),
          onChange: refresh,
        });

        SS.segmented($("side"), (v) => {
          st.side = v;
          if (v === "sell") {
            const h = store.holding(code);
            qty.set(h ? Math.min(h.sellable_quantity, Math.max(unit, qty.get())) : 0, false);
          }
          refresh();
        });
        SS.segmented($("ptype"), (v) => {
          st.ptype = v;
          $("limit-field").hidden = v !== "limit";
          if (v === "limit") limit.set(q.price_cents, false);
          refresh();
        });

        $("chips").addEventListener("click", (e) => {
          const c = e.target.closest(".chip");
          if (!c) return;
          SS.haptic(5);
          const m = maxQty();
          const f = Number(c.dataset.frac);
          // 卖出“全仓”允许零股一次卖完；其余按交易单位向下取整
          let n = st.side === "sell" && f === 1 ? m : Math.floor((m * f) / unit) * unit;
          if (n === 0 && m >= unit) n = unit; // 高价股资金只够几手时，小比例至少给 1 手
          qty.set(n);
          SS.$$(".chip", body).forEach((x) => x.classList.toggle("is-active", x === c));
        });

        function refresh() {
          const priceC = q.price_cents;
          $("price").textContent = fmt.price(priceC);
          $("price").className = `num order__price ${fmt.trend(q.change_bp)}`;
          $("chg").textContent = fmt.pctBp(q.change_bp);
          $("chg").className = `num xs ${fmt.trend(q.change_bp)}`;
          $("limits").textContent = `跌停 ${fmt.price(q.limit_down_cents)} · 涨停 ${fmt.price(q.limit_up_cents)}`;

          const n = qty.get();
          const est = store.estimate({ code, side: st.side, quantity: n, price_type: st.ptype, limit_price_cents: limit.get() });
          const m = maxQty();
          $("gross").textContent = fmt.yuan(est.gross_cents, { symbol: true });
          $("fee").textContent = fmt.yuan(est.fee_cents, { symbol: true });
          if (st.side === "buy") {
            $("cash-label").textContent = "可用资金";
            $("cash").textContent = fmt.yuan(store.state.cash_cents, { symbol: true });
            $("avail-qty").textContent = `最多可买 ${fmt.qty(m)}`;
          } else {
            const h = store.holding(code);
            $("cash-label").textContent = "预计到账";
            $("cash").textContent = fmt.yuan(est.total_cents, { symbol: true });
            $("avail-qty").textContent = h
              ? `可卖 ${fmt.qty(h.sellable_quantity)}${h.quantity > h.sellable_quantity ? ` · T+1 冻结 ${fmt.qty(h.quantity - h.sellable_quantity)}` : ""}`
              : "暂无持仓";
          }
          // 预校验，提前给出提示（最终以 placeOrder 的错误码为准）
          let warn = "";
          if (!store.isTrading()) warn = store.errorText("MARKET_CLOSED");
          else if (n <= 0) warn = "";
          else if (n > m) warn = st.side === "buy" ? store.errorText("TRADE_INSUFFICIENT_FUNDS") : (store.holding(code) && n <= store.holding(code).quantity ? store.errorText("TRADE_T1_SELL_BLOCKED") : store.errorText("TRADE_INSUFFICIENT_HOLDINGS"));
          $("error").textContent = warn || submitErr || (confirmDev ? store.errorText("TRADE_PRICE_DEVIATION_CONFIRM") + "，再点一次确认下单" : "");
          const label = st.side === "buy" ? "买入" : "卖出";
          const sub = $("submit");
          sub.textContent = n > 0 ? `${label} ${fmt.qty(n)} 股 · ${fmt.yuan(est.total_cents, { symbol: true })}` : `请输入${label}数量`;
          sub.disabled = n <= 0 || !!warn;
        }

        // 价格/数量/方向任何变化都需要重新确认偏离提示
        // 同时清掉“提交错误”并立即重绘（chips/步进按钮的 refresh 先于本委托执行，需补一次）
        const resetConfirm = () => {
          confirmDev = false;
          if (submitErr) {
            submitErr = "";
            refresh();
          }
        };
        body.addEventListener("input", resetConfirm);
        body.addEventListener("click", (e) => e.target.closest("button:not([data-role=submit])") && resetConfirm());

        $("submit").addEventListener("click", async () => {
          const sub = $("submit");
          if (sub.dataset.busy) return; // 防重复提交
          sub.dataset.busy = "1";
          sub.disabled = true;
          submitErr = "";
          try {
            // 假数据版同步返回，真实版返回 Promise；await 两者通用
            const out = await store.placeOrder({
              code,
              side: st.side,
              quantity: qty.get(),
              price_type: st.ptype,
              limit_price_cents: st.ptype === "limit" ? limit.get() : null,
              confirm_deviation: confirmDev,
            });
            SS.haptic([10, 40, 10]);
            success(body, out.trade, api);
          } catch (err) {
            if (!(err instanceof store.ApiError) && !(SS.ApiError && err instanceof SS.ApiError)) throw err;
            if (!$("error")) return; // 抽屉已关闭
            if (err.code === "TRADE_PRICE_DEVIATION_CONFIRM") confirmDev = true;
            // 偏离确认由 refresh 依 confirmDev 渲染；其余错误存入 submitErr 持续显示
            submitErr = err.code === "TRADE_PRICE_DEVIATION_CONFIRM" ? "" : store.errorText(err.code);
            refresh();
            body.querySelector(".order").classList.remove("shake");
            void body.offsetWidth;
            body.querySelector(".order").classList.add("shake");
            delete sub.dataset.busy;
            sub.disabled = false;
          }
        });

        unsub = store.on("tick", () => {
          if ($("price")) refresh();
        });
        refresh();
      },
    });

    function success(body, t, api) {
      unsub && unsub();
      const label = t.side === "buy" ? "买入" : "卖出";
      SS.mount(
        body,
        html`<div class="order-done">
          <div class="order-done__mark">${SS.icon("check")}</div>
          <h3>${label}成交</h3>
          <p class="t2 sm">${t.name} · ${fmt.qty(t.quantity)} 股 @ <span class="num">${fmt.price(t.price_cents)}</span></p>
          <dl class="order__summary">
            <div><dt>成交金额</dt><dd class="num">${fmt.yuan(t.gross_cents, { symbol: true })}</dd></div>
            <div><dt>手续费</dt><dd class="num">${fmt.yuan(t.fee_cents, { symbol: true })}</dd></div>
            ${t.side === "sell"
              ? html`<div><dt>本笔盈亏</dt><dd class="num ${fmt.trend(t.realized_pnl_cents)}">${fmt.yuan(t.realized_pnl_cents, { sign: true, symbol: true })}</dd></div>`
              : html`<div><dt>剩余资金</dt><dd class="num">${fmt.yuan(SS.store.state.cash_cents, { symbol: true })}</dd></div>`}
          </dl>
          <div class="order-done__actions">
            <a class="btn btn-block" href="#/portfolio" data-role="to-portfolio">查看持仓</a>
            <button type="button" class="btn btn-primary btn-block" data-role="done">完成</button>
          </div>
        </div>`
      );
      SS.$('[data-role="done"]', body).addEventListener("click", api.close);
      SS.$('[data-role="to-portfolio"]', body).addEventListener("click", api.close);
      // 用户有触碰就取消自动关闭
      autoCloseT = setTimeout(api.close, 2400);
      body.addEventListener("pointerdown", () => clearTimeout(autoCloseT), { once: true });
    }
  }

  SS.orderSheet = { open };
})();
