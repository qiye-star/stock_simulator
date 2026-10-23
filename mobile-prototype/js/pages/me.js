/**
 * 我的（#/me）
 *   - 账户卡（UserOut + 当前存档信息）；
 *   - 交易统计（由成交推导）；
 *   - 成交记录（TradeOut，AnimatedList），可按 买入/卖出/自动 过滤，点行看明细，“加载更多”模拟游标分页；
 *   - 设置：行情刷新频率可用（改 refresh_rate_ms），其余为占位。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const PAGE = 6;
  let filter = "all";

  function render(view) {
    const store = SS.store;
    const fmt = SS.fmt;
    const u = store.state.user;
    const sv = store.state.save;
    let shown = PAGE;

    SS.mount(
      view,
      html`<header class="topbar"><h1 class="topbar__title">我的</h1></header>

        <section class="profile">
          <div class="profile__avatar" aria-hidden="true">${u.username.slice(0, 1).toUpperCase()}</div>
          <div class="profile__main">
            <div class="profile__name">${u.username}</div>
            <div class="xs t3">注册于 ${u.created_at.slice(0, 10)}</div>
          </div>
          <button type="button" class="btn btn-sm" data-role="switch-save">切换存档</button>
        </section>
        <div class="save-chip xs">
          <span>${sv.name}</span><span class="t3">·</span><span>${sv.mode === "normal" ? "普通模式" : sv.mode}</span><span class="t3">·</span>
          <span class="num">${sv.trade_unit === 100 ? "每手 100 股" : "1 股起"}</span><span class="t3">·</span><span>${sv.t0_mode ? "T+0" : "T+1"}</span>
        </div>

        <dl class="stat-grid stat-grid--3 card" data-role="stats"></dl>

        <div class="section-head">
          <h2 class="section-title">成交记录</h2>
        </div>
        <div class="seg seg--4 seg--inline-full" data-role="filter">
          <span class="seg__thumb" aria-hidden="true"></span>
          ${[["all", "全部"], ["buy", "买入"], ["sell", "卖出"], ["auto", "自动"]].map(
            ([v, t]) => html`<button type="button" data-value="${v}" class="${filter === v ? "is-active" : ""}">${t}</button>`
          )}
        </div>
        <div class="card card--flush trade-list" data-role="trades"></div>

        <div class="section-head"><h2 class="section-title">设置</h2></div>
        <div class="card card--flush settings">
          <div class="set-row">
            <span class="set-row__icon">${SS.icon("refresh")}</span>
            <span class="set-row__label">行情刷新</span>
            <div class="seg seg--3 seg--mini" data-role="rate">
              <span class="seg__thumb" aria-hidden="true"></span>
              ${[1000, 3000, 5000].map((ms) => html`<button type="button" data-value="${ms}" class="${u.refresh_rate_ms === ms ? "is-active" : ""}">${ms / 1000}s</button>`)}
            </div>
          </div>
          <button type="button" class="set-row" data-ph="语言切换">
            <span class="set-row__icon">${SS.icon("globe")}</span><span class="set-row__label">语言</span><span class="t3 sm">简体中文</span>${SS.icon("chevron", "set-row__chev")}
          </button>
          <button type="button" class="set-row" data-ph="主题切换">
            <span class="set-row__icon">${SS.icon("moon")}</span><span class="set-row__label">主题</span><span class="t3 sm">深色</span>${SS.icon("chevron", "set-row__chev")}
          </button>
          <div class="set-row">
            <span class="set-row__icon">${SS.icon("clock")}</span><span class="set-row__label">行情暂停</span>
            <button type="button" class="switch ${store.state.clock.paused ? "is-on" : ""}" role="switch" aria-checked="${store.state.clock.paused}" data-role="pause" aria-label="暂停行情"><i></i></button>
          </div>
          <button type="button" class="set-row" data-ph="导出存档">
            <span class="set-row__icon">${SS.icon("download")}</span><span class="set-row__label">导出存档</span>${SS.icon("chevron", "set-row__chev")}
          </button>
          <button type="button" class="set-row" data-ph="退出登录">
            <span class="set-row__icon">${SS.icon("logout")}</span><span class="set-row__label">退出登录</span>${SS.icon("chevron", "set-row__chev")}
          </button>
        </div>
        <p class="foot xs t3"><span class="shiny-text">股市模拟器</span> · ${store.mode === "real" ? "已连接后端" : "移动端原型 · 本地假数据"}</p>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);

    function paintStats() {
      const t = store.trades();
      const sells = t.filter((x) => x.side === "sell");
      const wins = sells.filter((x) => x.realized_pnl_cents > 0).length;
      const realized = sells.reduce((a, x) => a + x.realized_pnl_cents, 0);
      SS.mount(
        $("stats"),
        html`<div><dt>交易笔数</dt><dd class="num">${t.length}</dd></div>
          <div><dt>卖出胜率</dt><dd class="num">${sells.length ? Math.round((wins / sells.length) * 100) + "%" : "—"}</dd></div>
          <div><dt>已实现盈亏</dt><dd class="num ${fmt.trend(realized)}">${fmt.yuanCompact(realized, { sign: true })}</dd></div>`
      );
    }

    const filtered = () =>
      store.trades().filter((x) => (filter === "all" ? true : filter === "auto" ? x.source === "auto" : x.side === filter));

    function row(t) {
      return html`<button type="button" class="trade-row animated-list__item" data-id="${t.id}">
        <span class="side-badge ${t.side === "buy" ? "is-buy" : ""}">${t.side === "buy" ? "买" : "卖"}</span>
        <span class="trade-row__main">
          <span class="trade-row__name">${t.name}${t.source === "auto" ? html` <span class="tag">自动</span>` : ""}</span>
          <span class="xs t3 num">D${t.trading_day} ${fmt.clock(t.clock_minute)} · ${fmt.qty(t.quantity)} 股 @ ${fmt.price(t.price_cents)}</span>
        </span>
        <span class="trade-row__right">
          <span class="num sm">${fmt.yuan(t.gross_cents)}</span>
          ${t.side === "sell"
            ? html`<span class="num xs ${fmt.trend(t.realized_pnl_cents)}">${fmt.yuan(t.realized_pnl_cents, { sign: true })}</span>`
            : html`<span class="xs t3">${t.price_type === "limit" ? "限价" : "市价"}</span>`}
        </span>
      </button>`;
    }

    function paintTrades(append) {
      const list = filtered();
      const host = $("trades");
      if (!list.length) {
        SS.mount(host, html`<div class="empty empty--sm"><div class="empty__title">${SS.blurText("暂无成交")}</div></div>`);
        return;
      }
      const items = list.slice(0, shown);
      const more = list.length > shown || store.tradesHasMore();
      SS.mount(
        host,
        html`<div class="animated-list" data-role="tl">${items.map(row)}</div>
          ${more ? html`<button type="button" class="load-more" data-role="more">加载更多 ${list.length > shown ? html`<span class="t3 num">${list.length - shown}</span>` : ""}</button>` : ""}`
      );
      // 已显示过的项不再重复入场
      if (append) SS.$$(".animated-list__item", host).slice(0, append).forEach((el) => el.classList.add("is-in"));
      SS.animatedList(host);
    }

    $("trades").addEventListener("click", (e) => {
      const more = e.target.closest('[data-role="more"]');
      if (more) {
        // 模拟游标分页的网络延迟：骨架占位
        SS.mount(more, html`<span class="skeleton" style="display:block;width:100%;height:14px"></span>`);
        more.disabled = true;
        // 真实版：本地已加载的不足一页时，按游标向后端再取一页（GET /trades?cursor=）
        const prev = shown;
        shown += PAGE;
        const need = filtered().length < shown && store.tradesHasMore() ? store.loadMoreTrades() : Promise.resolve();
        Promise.resolve(need)
          .catch((err) => store.notifyError(err))
          .then(() => paintTrades(prev));
        return;
      }
      const r = e.target.closest(".trade-row");
      if (r) openTrade(store.trades().find((t) => t.id === r.dataset.id));
    });

    SS.segmented($("filter"), (v) => {
      filter = v;
      shown = PAGE;
      paintTrades();
    });
    SS.segmented($("rate"), async (v) => {
      try {
        await store.setRefreshRate(Number(v)); // 真实版：PATCH /me 并重连实时流
        SS.toast(`行情每 ${Number(v) / 1000} 秒刷新`, { duration: 1200 });
      } catch (err) {
        store.notifyError(err);
      }
    });
    $("pause").addEventListener("click", async () => {
      const on = !store.state.clock.paused;
      const paint = (v) => {
        $("pause").classList.toggle("is-on", v);
        $("pause").setAttribute("aria-checked", v);
      };
      paint(on);
      SS.haptic(6);
      try {
        await store.setPaused(on); // 真实版：POST /clock/pause|resume
      } catch (err) {
        paint(!on);
        store.notifyError(err);
      }
    });
    const real = store.mode === "real";
    // 设置里的语言 / 主题：后端虽有 PATCH /me {theme,lang}，但原型只有深色中文界面，仍为占位
    SS.$$("[data-ph]", view).forEach((b) =>
      b.addEventListener("click", async () => {
        if (real && b.dataset.ph === "导出存档") {
          try {
            await store.exportSave();
            SS.toast("存档已导出", { duration: 1400 });
          } catch (err) {
            store.notifyError(err);
          }
        } else if (real && b.dataset.ph === "退出登录") {
          await store.logout();
          SS.ready = false;
          location.hash = "#/login";
        } else SS.toast(`${b.dataset.ph}：原型暂未实现`, { icon: null, duration: 1400 });
      })
    );
    $("switch-save").addEventListener("click", () => (real ? openSaves() : SS.toast("存档切换：假数据模式不可用", { icon: null, duration: 1400 })));

    paintStats();
    paintTrades();
    const off = store.on("order", () => {
      paintStats();
      paintTrades();
    });
    return off;
  }

  /** 存档切换抽屉（真实模式）：GET /saves、POST /saves */
  function openSaves() {
    const store = SS.store;
    SS.sheet.open({
      title: "切换存档",
      render(body, api) {
        const paint = (list) => {
          SS.mount(
            body,
            html`<div class="save-list">
                ${list.map(
                  (v) => html`<button type="button" class="set-row" data-id="${v.id}">
                    <span class="set-row__label">${v.name || "未命名存档"}</span>
                    <span class="t3 sm num">${SS.fmt.yuanCompact(v.initial_fund_cents)} · D${v.trading_day}</span>
                    ${v.id === store.state.save.id ? html`<span class="tag">当前</span>` : ""}
                  </button>`
                )}
              </div>
              <button type="button" class="btn btn-block" data-role="new-save" style="margin-top:12px">新建存档（100 万 · 每手 100 股 · T+1）</button>`
          );
        };
        paint(store.state.savesList);
        store.listSaves().then(paint).catch((e) => store.notifyError(e));
        body.addEventListener("click", async (e) => {
          const row = e.target.closest("[data-id]");
          const add = e.target.closest('[data-role="new-save"]');
          if (!row && !add) return;
          try {
            if (add) await store.createSave(`存档 ${store.state.savesList.length + 1}`);
            else if (row.dataset.id !== store.state.save.id) await store.switchSave(row.dataset.id);
            api.close();
            SS.router.navigate("/market");
          } catch (err) {
            store.notifyError(err);
          }
        });
      },
    });
  }

  /** 成交明细抽屉（展示 TradeOut 的关键字段） */
  function openTrade(t) {
    const fmt = SS.fmt;
    SS.sheet.open({
      title: "成交明细",
      render(body) {
        const row = (k, v, cls = "") => html`<div><dt>${k}</dt><dd class="num ${cls}">${v}</dd></div>`;
        SS.mount(
          body,
          html`<div class="trade-detail">
            <div class="trade-detail__head">
              <span class="side-badge side-badge--lg ${t.side === "buy" ? "is-buy" : ""}">${t.side === "buy" ? "买" : "卖"}</span>
              <div><div class="profile__name">${t.name}</div><div class="xs t3 num">${t.code} · #${t.seq}</div></div>
            </div>
            <dl class="kv">
              ${row("成交价", fmt.price(t.price_cents))}
              ${row("数量", `${fmt.qty(t.quantity)} 股`)}
              ${row("成交金额", fmt.yuan(t.gross_cents, { symbol: true }))}
              ${row("手续费", fmt.yuan(t.fee_cents, { symbol: true }))}
              ${row("资金变动", fmt.yuan(t.cash_delta_cents, { sign: true, symbol: true }))}
              ${t.side === "sell" ? row("实现盈亏", fmt.yuan(t.realized_pnl_cents, { sign: true, symbol: true }), fmt.trend(t.realized_pnl_cents)) : ""}
              ${row("委托方式", t.price_type === "limit" ? `限价 ${fmt.price(t.limit_price_cents)}` : "市价")}
              ${row("来源", t.source === "auto" ? "自动交易" : "手动")}
              ${row("时间", `第 ${t.trading_day} 日 ${fmt.clock(t.clock_minute)}`)}
            </dl>
            <a class="btn btn-block" href="#/stock/${t.code}">查看 ${t.name}</a>
          </div>`
        );
      },
    });
  }

  SS.pages = SS.pages || {};
  SS.pages.me = { tab: "me", render };
})();
