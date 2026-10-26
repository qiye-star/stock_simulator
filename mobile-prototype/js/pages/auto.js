/**
 * 自动交易（#/auto）—— 对应 /saves/{id}/auto-trade/*
 *   - 二级页（tab=null，无 Dock）：入口在“我的”页的“自动交易”行，顶栏“返回 + 标题 + 新建规则”；
 *   - 状态卡：运行/暂停/停止控制 + 次数进度 + 成功/失败/累计盈亏（AutoStatusOut）；
 *   - 规则卡片（AutoConfigOut）：一句话描述条件 + 开关；点卡片编辑；
 *   - 新建/编辑规则抽屉：字段与 AutoConfigIn 一致，前端按其校验规则预检；
 *   - 最近触发记录（AutoEventOut，AnimatedList）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  const COND = { price: "价格", percentage: "涨跌幅", profit: "持仓盈亏", time: "定时" };
  const OP = { above: "高于", below: "低于", equal: "等于" };
  const DIR = { buy: "买入", sell: "卖出" };

  /** 规则的一句话描述 */
  function sentence(c) {
    const fmt = SS.fmt;
    let cond;
    // 语义与 backend domain/auto_trade/conditions.py 一致
    if (c.condition_type === "time") cond = "定时（冷却结束即触发）";
    else if (c.condition_type === "percentage") cond = `当日涨跌幅${OP[c.condition_operator]} ${fmt.pctFloat(c.condition_percent)} 时`;
    else if (c.condition_type === "profit")
      cond = c.condition_operator === "below"
        ? `持仓亏损达到 ${fmt.yuanCompact(c.condition_value_cents, { symbol: true })} 时`
        : `持仓盈利达到 ${fmt.yuanCompact(c.condition_value_cents, { symbol: true })} 时`;
    else cond = `价格${OP[c.condition_operator]} ${fmt.yuan(c.condition_value_cents, { symbol: true })} 时`;
    const how = c.price_type === "limit" ? `以 ${fmt.yuan(c.limit_price_cents, { symbol: true })} 限价` : "市价";
    return { cond, act: `${how}${DIR[c.direction]} ${fmt.qty(c.quantity)} 股` };
  }

  function render(view) {
    const store = SS.store;
    const fmt = SS.fmt;

    const back = html`<button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>`;
    // 挑战存档（⑦）里自动交易不可用
    if (store.state.save.mode === "challenge") {
      SS.mount(
        view,
        html`<header class="topbar topbar--sub">${back}<h1 class="topbar__title topbar__title--sub">自动交易</h1></header>
          <section class="soon-card"><div class="soon-card__head"><h2 class="soon-card__title">挑战中不可用自动交易</h2></div>
          <p class="soon-card__desc t2 sm">每日挑战里所有玩家用同样的规则交易，结束挑战回到普通存档后即可使用。</p></section>`
      );
      SS.$('[data-role="back"]', view).addEventListener("click", SS.router.back);
      return null;
    }

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          ${back}
          <h1 class="topbar__title topbar__title--sub">自动交易</h1>
          <button type="button" class="btn btn-sm btn-primary" data-role="new">${SS.icon("plus")}新建规则</button>
        </header>
        <section class="card auto-status" data-role="status"></section>
        <div class="section-head">
          <h2 class="section-title">规则 <span class="t3 num" data-role="count"></span></h2>
          <span class="xs t3">同一股票同一方向仅一条</span>
        </div>
        <div class="rule-list" data-role="rules"></div>
        <div class="section-head"><h2 class="section-title">最近触发</h2></div>
        <div class="card card--flush" data-role="events"></div>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    $("back").addEventListener("click", SS.router.back);

    function paintStatus() {
      const s = store.state.auto.status;
      const state = !s.enabled ? "off" : s.paused ? "paused" : "on";
      const label = { off: "未启动", paused: "已暂停", on: "运行中" }[state];
      const pct = Math.min(100, (s.total_trades / (s.max_total_trades || 1)) * 100);
      SS.mount(
        $("status"),
        html`<div class="auto-status__top">
            <div class="auto-status__state is-${state}"><i aria-hidden="true"></i>${state === "on" ? html`<span class="shiny-text">${label}</span>` : label}</div>
            <div class="auto-status__ctrl">
              ${state === "off"
                ? html`<button type="button" class="btn btn-sm btn-primary" data-ctl="start">${SS.icon("play")}启动</button>`
                : html`<button type="button" class="btn btn-sm" data-ctl="${state === "on" ? "pause" : "resume"}">${SS.icon(state === "on" ? "pause" : "play")}${state === "on" ? "暂停" : "继续"}</button>
                    <button type="button" class="btn btn-sm btn-ghost" data-ctl="stop">停止</button>`}
            </div>
          </div>
          <div class="progress" role="progressbar" aria-valuenow="${s.total_trades}" aria-valuemax="${s.max_total_trades}"><i style="width:${pct}%"></i></div>
          <dl class="stat-grid stat-grid--4">
            <div><dt>已执行</dt><dd class="num">${s.total_trades}<small class="t3">/${s.max_total_trades}</small></dd></div>
            <div><dt>成功</dt><dd class="num">${s.success_trades}</dd></div>
            <div><dt>失败</dt><dd class="num">${s.failed_trades}</dd></div>
            <div><dt>累计盈亏</dt><dd class="num ${fmt.trend(s.total_pnl_cents)}">${fmt.yuanCompact(s.total_pnl_cents, { sign: true })}</dd></div>
          </dl>`
      );
    }
    $("status").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-ctl]");
      if (!b) return;
      SS.haptic();
      try {
        await store.autoControl(b.dataset.ctl);
        SS.toast({ start: "自动交易已启动", pause: "已暂停", resume: "已继续", stop: "已停止" }[b.dataset.ctl], { duration: 1200 });
      } catch (err) {
        store.notifyError(err);
      }
    });

    function paintRules() {
      const list = store.state.auto.configs;
      $("count").textContent = list.length;
      if (!list.length) {
        SS.mount(
          $("rules"),
          html`<div class="empty">
            <div class="empty__title">${SS.blurText("还没有规则")}</div>
            <p class="t3 sm">例如：招商银行跌破 34.50 元时买入 1000 股</p>
            <button type="button" class="btn btn-sm btn-primary" data-role="new2">新建第一条规则</button>
          </div>`
        );
        SS.$('[data-role="new2"]', view).addEventListener("click", () => openRule());
        return;
      }
      SS.mount(
        $("rules"),
        html`<div class="animated-list">${list.map((c) => {
          const s = sentence(c);
          const q = store.quote(c.code);
          return html`<article class="rule animated-list__item ${c.enabled ? "" : "is-off"}" data-id="${c.id}" tabindex="0">
            <div class="rule__top">
              <div class="rule__stock">
                <span class="tag ${c.direction === "buy" ? "tag--accent" : ""}">${DIR[c.direction]}</span>
                <span class="rule__name">${c.name}</span>
                <span class="xs t3 num">${c.code}</span>
              </div>
              <button type="button" class="switch ${c.enabled ? "is-on" : ""}" role="switch" aria-checked="${c.enabled}" aria-label="启用规则" data-toggle><i></i></button>
            </div>
            <p class="rule__text"><span class="t2">${s.cond}</span><br />${s.act}</p>
            <div class="rule__meta xs t3">
              <span>现价 <b class="num ${fmt.trend(q.change_bp)}">${fmt.price(q.price_cents)}</b></span>
              ${c.stop_loss_percent != null ? html`<span>止损 ${fmt.pctFloat(c.stop_loss_percent)}</span>` : ""}
              ${c.take_profit_percent != null ? html`<span>止盈 ${fmt.pctFloat(c.take_profit_percent)}</span>` : ""}
              <span>次数 ${c.max_trades ? c.max_trades : "不限"}</span>
              ${c.max_amount_cents != null ? html`<span>上限 ${fmt.yuanCompact(c.max_amount_cents, { symbol: true })}</span>` : ""}
            </div>
          </article>`;
        })}</div>`
      );
      SS.animatedList($("rules"));
    }
    $("rules").addEventListener("click", (e) => {
      const card = e.target.closest(".rule");
      if (!card) return;
      if (e.target.closest("[data-toggle]")) {
        SS.haptic(6);
        const on = store.autoToggle(card.dataset.id);
        const sw = SS.$(".switch", card);
        sw.classList.toggle("is-on", on);
        sw.setAttribute("aria-checked", on);
        card.classList.toggle("is-off", !on);
        return;
      }
      openRule(store.state.auto.configs.find((c) => c.id === card.dataset.id));
    });
    $("rules").addEventListener("keydown", (e) => {
      const card = e.target.closest(".rule");
      if (card && e.key === "Enter" && e.target === card) openRule(store.state.auto.configs.find((c) => c.id === card.dataset.id));
    });

    // 已渲染过的事件 id：重绘时这些行直接带 is-in，只有新增行播放入场动画，避免整列表重播/闪烁
    const seenEvents = new Set();
    let eventsKey = null;
    function paintEvents() {
      const ev = store.state.auto.events;
      // 事件列表（id + 结果 + 对应股票名是否已加载）没变就不重绘
      const key = ev.map((e) => `${e.id}:${e.success ? 1 : 0}:${store.quote(e.stock_code) ? 1 : 0}`).join("|");
      if (key === eventsKey) return;
      eventsKey = key;
      if (!ev.length) {
        SS.mount($("events"), html`<p class="t3 sm empty-inline">暂无触发记录</p>`);
        return;
      }
      SS.mount(
        $("events"),
        html`<div class="animated-list">${ev.map((e) => {
          const q = store.quote(e.stock_code);
          return html`<div class="event-row animated-list__item ${seenEvents.has(e.id) ? "is-in" : ""}">
            <span class="event-row__icon ${e.success ? "is-ok" : "is-fail"}">${SS.icon(e.success ? "check" : "close")}</span>
            <div class="event-row__main">
              <div>${q ? q.name : e.stock_code} · ${DIR[e.direction]} <span class="t3 xs">${COND[e.condition_type]}</span></div>
              <div class="xs t3">${e.success ? html`成交 <span class="num">${fmt.yuanCompact(e.amount_cents, { symbol: true })}</span>` : store.errorText(e.reason_code)} · D${fmt.dayNo(e.trading_day)}</div>
            </div>
            <div class="num sm ${e.pnl_cents ? fmt.trend(e.pnl_cents) : "t3"}">${e.pnl_cents ? fmt.yuan(e.pnl_cents, { sign: true }) : "—"}</div>
          </div>`;
        })}</div>`
      );
      SS.animatedList($("events"));
      ev.forEach((e) => seenEvents.add(e.id));
    }

    $("new").addEventListener("click", () => openRule());
    paintStatus();
    paintRules();
    paintEvents();

    const offs = [
      store.on("auto", () => {
        paintStatus();
        paintRules();
        paintEvents();
      }),
      store.on("tick", () => {
        // 只刷新规则卡里的现价
        SS.$$(".rule", view).forEach((el) => {
          const c = store.state.auto.configs.find((x) => x.id === el.dataset.id);
          if (!c) return;
          const q = store.quote(c.code);
          if (!q) return;
          const b = SS.$(".rule__meta b", el);
          b.textContent = fmt.price(q.price_cents);
          b.className = `num ${fmt.trend(q.change_bp)}`;
        });
      }),
    ];
    return () => offs.forEach((f) => f());
  }

  // ---------- 新建 / 编辑规则抽屉 ----------
  /** 选股器需要完整股票池：先 loadAllQuotes（真实版一次 GET /market?limit=500，假数据版即时返回）再开抽屉 */
  function openRule(existing) {
    Promise.resolve(SS.store.loadAllQuotes())
      .catch((e) => SS.store.notifyError(e))
      .then(() => openRuleSheet(existing));
  }
  function openRuleSheet(existing) {
    const store = SS.store;
    const fmt = SS.fmt;
    const unit = store.state.save.trade_unit;
    const c = existing
      ? { ...existing }
      : {
          code: (store.state.stocks.find((s) => s.watchlisted) || store.state.stocks[0]).code,
          direction: "buy",
          condition_type: "price",
          condition_operator: "below",
          condition_value_cents: null,
          condition_percent: 3,
          quantity: unit * 10,
          price_type: "market",
          limit_price_cents: null,
          stop_loss_percent: null,
          take_profit_percent: null,
          max_trades: 0,
          max_amount_cents: null,
          enabled: true,
        };

    SS.sheet.open({
      title: existing ? "编辑规则" : "新建规则",
      className: "rule-sheet",
      render(body, api) {
        SS.mount(
          body,
          html`<form class="form" novalidate>
            <label class="field">
              <span class="field__label"><span>股票</span><span class="xs t3 num" data-role="cur"></span></span>
              <span class="select">
                <select data-role="code" aria-label="股票">
                  ${store.state.stocks.map((s) => html`<option value="${s.code}" ${s.code === c.code ? "selected" : ""}>${s.name}  ${s.code}</option>`)}
                </select>
                ${SS.icon("chevron")}
              </span>
            </label>

            <div class="field">
              <span class="field__label"><span>方向</span></span>
              <div class="seg" data-role="direction">
                <span class="seg__thumb" aria-hidden="true"></span>
                ${["buy", "sell"].map((d) => html`<button type="button" data-value="${d}" class="${c.direction === d ? "is-active" : ""}">${DIR[d]}</button>`)}
              </div>
            </div>

            <div class="field">
              <span class="field__label"><span>触发条件</span></span>
              <div class="seg seg--4" data-role="ctype">
                <span class="seg__thumb" aria-hidden="true"></span>
                ${[["price", "价格"], ["percentage", "涨跌幅"], ["profit", "盈利"], ["time", "定时"]].map(
                  ([v, t]) => html`<button type="button" data-value="${v}" class="${c.condition_type === v ? "is-active" : ""}">${t}</button>`
                )}
              </div>
            </div>

            <div class="field" data-role="op-field">
              <span class="field__label"><span>比较</span></span>
              <div class="seg seg--3" data-role="op">
                <span class="seg__thumb" aria-hidden="true"></span>
                ${Object.entries(OP).map(([v, t]) => html`<button type="button" data-value="${v}" class="${(c.condition_operator || "below") === v ? "is-active" : ""}">${t}</button>`)}
              </div>
            </div>

            <div class="field" data-role="val-field">
              <span class="field__label"><span data-role="val-label">触发价（元）</span></span>
              <div class="stepper" data-role="val">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="减少">${SS.icon("minus")}</button>
                <input class="num" inputmode="decimal" aria-label="阈值" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="增加">${SS.icon("plus")}</button>
              </div>
            </div>

            <div class="field">
              <span class="field__label"><span>数量（股）</span></span>
              <div class="stepper" data-role="qty">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="减少">${SS.icon("minus")}</button>
                <input class="num" inputmode="numeric" aria-label="数量" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="增加">${SS.icon("plus")}</button>
              </div>
            </div>

            <div class="field">
              <span class="field__label"><span>委托方式</span></span>
              <div class="seg" data-role="ptype">
                <span class="seg__thumb" aria-hidden="true"></span>
                <button type="button" data-value="market" class="${c.price_type === "market" ? "is-active" : ""}">市价</button>
                <button type="button" data-value="limit" class="${c.price_type === "limit" ? "is-active" : ""}">限价</button>
              </div>
            </div>
            <div class="field" data-role="limit-field">
              <span class="field__label"><span>限价（元）</span></span>
              <div class="stepper" data-role="limit">
                <button type="button" class="stepper__btn" data-step="-1" aria-label="降低">${SS.icon("minus")}</button>
                <input class="num" inputmode="decimal" aria-label="限价" />
                <button type="button" class="stepper__btn" data-step="1" aria-label="提高">${SS.icon("plus")}</button>
              </div>
            </div>

            <details class="advanced" ${c.stop_loss_percent != null || c.take_profit_percent != null || c.max_amount_cents != null || c.max_trades ? "open" : ""}>
              <summary>风控（可选）${SS.icon("chevron")}</summary>
              <p class="xs t3 advanced__note">止损 / 止盈按持仓成本百分比计算，仅对卖出规则生效</p>
              <div class="grid-2">
                <label class="field"><span class="field__label"><span>止损 %</span></span><input class="input num" data-role="sl" inputmode="decimal" placeholder="不设置" value="${c.stop_loss_percent ?? ""}" /></label>
                <label class="field"><span class="field__label"><span>止盈 %</span></span><input class="input num" data-role="tp" inputmode="decimal" placeholder="不设置" value="${c.take_profit_percent ?? ""}" /></label>
                <label class="field"><span class="field__label"><span>最多执行次数</span></span><input class="input num" data-role="maxn" inputmode="numeric" placeholder="0 = 不限" value="${c.max_trades || ""}" /></label>
                <label class="field"><span class="field__label"><span>单规则金额上限（元）</span></span><input class="input num" data-role="maxa" inputmode="decimal" placeholder="不设置" value="${c.max_amount_cents != null ? fmt.toInput(c.max_amount_cents) : ""}" /></label>
              </div>
            </details>

            <p class="order__error" data-role="error" role="alert"></p>
            <div class="form__actions">
              ${existing ? html`<button type="button" class="btn btn-ghost" data-role="del">${SS.icon("trash")}删除</button>` : ""}
              <button type="submit" class="btn btn-primary btn-lg" data-role="save">${existing ? "保存修改" : "创建规则"}</button>
            </div>
          </form>`
        );

        const $ = (r) => SS.$(`[data-role="${r}"]`, body);
        const quote = () => store.quote($("code").value);

        // 阈值步进器：价格（分，步进 1 分）/ 涨跌幅（0.1%）/ 盈利（元，步进 100 元）
        let val = null;
        let op = null;
        function buildVal() {
          const t = c.condition_type;
          $("val-field").hidden = t === "time";
          $("op-field").hidden = t === "time";
          // 后端 profit 条件不支持“等于”
          SS.$('[data-value="equal"]', $("op")).disabled = t === "profit";
          if (t === "profit" && c.condition_operator === "equal") {
            c.condition_operator = "above";
            op && op.set("above");
          }
          if (t === "time") return;
          const host = $("val");
          const fresh = host.cloneNode(true);
          host.replaceWith(fresh);
          const q = quote();
          if (t === "price") {
            $("val-label").textContent = "触发价（元）";
            val = SS.stepper(fresh, { value: c.condition_value_cents ?? q.price_cents, step: 1, min: 1, display: fmt.toInput, parse: fmt.parseYuan, onChange: (v) => (c.condition_value_cents = v) });
            c.condition_value_cents = val.get();
          } else if (t === "profit") {
            $("val-label").textContent = "盈利金额（元）";
            val = SS.stepper(fresh, { value: c.condition_value_cents ?? 100000, step: 10000, min: 0, display: fmt.toInput, parse: fmt.parseYuan, onChange: (v) => (c.condition_value_cents = v) });
            c.condition_value_cents = val.get();
          } else {
            $("val-label").textContent = "涨跌幅阈值（%）";
            val = SS.stepper(fresh, {
              value: Math.round((c.condition_percent ?? 3) * 10),
              step: 1,
              min: 0,
              max: 1000,
              display: (v) => (v / 10).toFixed(1),
              parse: (s) => Math.round(parseFloat(s) * 10),
              onChange: (v) => (c.condition_percent = v / 10),
            });
            c.condition_percent = val.get() / 10;
          }
        }

        const qty = SS.stepper($("qty"), { value: c.quantity, step: unit, min: unit, display: fmt.qty, parse: (s) => Number(String(s).replace(/[^\d]/g, "")), onChange: (v) => (c.quantity = v) });
        const limit = SS.stepper($("limit"), { value: c.limit_price_cents ?? quote().price_cents, step: 1, min: 1, display: fmt.toInput, parse: fmt.parseYuan, onChange: (v) => (c.limit_price_cents = v) });

        const ctype = SS.segmented($("ctype"), (v) => {
          c.condition_type = v;
          c.condition_value_cents = null;
          buildVal();
        });
        SS.segmented($("direction"), (v) => {
          c.direction = v;
          syncProfit();
        });
        op = SS.segmented($("op"), (v) => (c.condition_operator = v));
        SS.segmented($("ptype"), (v) => {
          c.price_type = v;
          $("limit-field").hidden = v !== "limit";
        });
        $("limit-field").hidden = c.price_type !== "limit";

        // 契约：profit 条件仅适用于卖出
        function syncProfit() {
          const b = SS.$('[data-value="profit"]', $("ctype"));
          b.disabled = c.direction === "buy";
          if (c.direction === "buy" && c.condition_type === "profit") {
            c.condition_type = "price";
            c.condition_value_cents = null;
            ctype.set("price");
            buildVal();
          }
        }
        function paintCur() {
          const q = quote();
          SS.mount($("cur"), html`现价 <span class="${fmt.trend(q.change_bp)}">${fmt.price(q.price_cents)} ${fmt.pctBp(q.change_bp)}</span>`);
        }
        $("code").addEventListener("change", () => {
          c.code = $("code").value;
          c.condition_value_cents = null;
          paintCur();
          buildVal();
          limit.set(quote().price_cents, false);
        });

        if (!c.condition_operator) c.condition_operator = "below";
        syncProfit();
        buildVal();
        paintCur();

        const optNum = (el) => {
          const s = el.value.trim();
          if (!s) return null;
          const n = Number(s);
          return Number.isFinite(n) && n >= 0 ? n : NaN;
        };

        SS.$("form", body).addEventListener("submit", async (e) => {
          e.preventDefault();
          if ($("save").disabled) return;
          const out = {
            code: c.code,
            direction: c.direction,
            condition_type: c.condition_type,
            condition_operator: c.condition_type === "time" ? null : c.condition_operator,
            condition_value_cents: ["price", "profit"].includes(c.condition_type) ? c.condition_value_cents : null,
            condition_percent: c.condition_type === "percentage" ? c.condition_percent : null,
            quantity: qty.get(),
            price_type: c.price_type,
            limit_price_cents: c.price_type === "limit" ? limit.get() : null,
            stop_loss_percent: optNum($("sl")),
            take_profit_percent: optNum($("tp")),
            max_trades: optNum($("maxn")) || 0,
            max_amount_cents: $("maxa").value.trim() ? fmt.parseYuan($("maxa").value) : null,
            enabled: existing ? existing.enabled : true,
          };
          // 按 AutoConfigIn 的约束预检
          const bad =
            [out.stop_loss_percent, out.take_profit_percent, out.max_trades].some((v) => Number.isNaN(v)) ||
            (out.stop_loss_percent != null && out.stop_loss_percent > 100) ||
            (out.max_amount_cents === null && $("maxa").value.trim()) ||
            !Number.isInteger(out.max_trades) ||
            out.quantity <= 0;
          if (bad) {
            $("error").textContent = store.errorText("VALIDATION_ERROR");
            return;
          }
          $("save").disabled = true;
          try {
            await store.autoSave(out, existing && existing.id);
            SS.haptic([10, 40, 10]);
            api.close();
            SS.toast(existing ? "规则已更新" : "规则已创建");
          } catch (err) {
            if (!(err instanceof store.ApiError) && !(SS.ApiError && err instanceof SS.ApiError)) throw err;
            if ($("error")) $("error").textContent = store.errorText(err.code);
            if ($("save")) $("save").disabled = false;
          }
        });
        if (existing)
          $("del").addEventListener("click", async () => {
            if ($("del").dataset.confirm) {
              try {
                await store.autoDelete(existing.id);
                api.close();
                SS.toast("规则已删除", { icon: "trash" });
              } catch (err) {
                store.notifyError(err);
              }
            } else {
              $("del").dataset.confirm = "1";
              SS.mount($("del"), html`${SS.icon("trash")}再点一次确认`);
            }
          });
      },
    });
  }

  SS.pages = SS.pages || {};
  SS.pages.auto = { tab: null, render };
})();
