/**
 * 行情 / 自选（#/market）
 *   - 顶部资产概览卡（CountUp + 极淡 Aurora），可一键隐藏金额；点卡片进入持仓；
 *   - 自选 / 全部 分段切换，支持按涨跌幅排序与搜索（代码/名称）；
 *     自选来自本地缓存；「全部」走服务端分页（store.listQuotes：limit/cursor/q/sort），滚动到底自动加载更多；
 *   - 行：名称代码 | 迷你走势 | 现价 + 涨跌幅；左滑露出 买入/卖出，直接弹下单抽屉；点行进入详情；
 *   - 行情 tick 到来时就地更新数字与走势线（不重绘列表，避免打断滑动）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html, raw } = SS;

  const PAGE = 50;
  const ui = {
    list: "watch", // watch | all
    sort: 0, // 0 默认 1 涨幅降序 2 涨幅升序
    q: "", // 搜索关键词（代码/名称）
    hintShown: false,
  };
  /** 「全部」列表的分页状态（模块级：从详情页返回时保留已加载的页；token 用于丢弃过期请求） */
  const all = { saveId: null, items: [], cursor: null, total: 0, done: false, loading: false, error: false, started: false, token: 0 };
  const SORT_TEXT = ["默认", "涨幅↓", "涨幅↑"];

  /** 金额隐藏开关（每位浏览者的本地偏好） */
  const prefs = {
    get hide() {
      try {
        return localStorage.getItem("ss.hideAmounts") === "1";
      } catch (_) {
        return false;
      }
    },
    set hide(v) {
      try {
        localStorage.setItem("ss.hideAmounts", v ? "1" : "0");
      } catch (_) {
        /* 隐私模式下忽略 */
      }
    },
  };
  SS.prefs = prefs;
  const MASK = "****";

  function clockChip(c) {
    const live = !c.paused && c.session !== "closed";
    return html`<span class="clock-chip ${live ? "is-live" : ""}">
      <i class="clock-chip__dot" aria-hidden="true"></i>
      <span>${SS.fmt.session(c.session, c.paused)}</span>
      <span class="num t3">D${c.trading_day} ${SS.fmt.clock(c.clock_minute)}</span>
    </span>`;
  }
  SS.clockChip = clockChip;

  function rowHtml(s) {
    const fmt = SS.fmt;
    const tr = fmt.trend(s.change_bp);
    return html`<div class="swipe-row animated-list__item" data-code="${s.code}">
      <div class="swipe-row__actions">
        <button type="button" class="swipe-act swipe-act--buy" data-action="buy">买入</button>
        <button type="button" class="swipe-act" data-action="sell">卖出</button>
      </div>
      <a class="swipe-row__main quote-row" href="#/stock/${s.code}" draggable="false">
        <div class="quote-row__name">
          <div class="quote-row__title">${s.name}</div>
          <div class="xs t3 num">${s.code}${s.code === "999999" ? html` <span class="tag">彩蛋</span>` : ""}</div>
        </div>
        <div class="quote-row__spark" data-q="spark">${raw(SS.chart.sparkline(s._spark || s._series, s.prev_close_cents))}</div>
        <div class="quote-row__right">
          <div class="num quote-row__price ${tr}" data-q="price">${fmt.price(s.price_cents)}</div>
          <div class="num pill pill--${tr}" data-q="chg">${fmt.pctBp(s.change_bp)}</div>
        </div>
      </a>
    </div>`;
  }

  function skeleton() {
    return html`<div class="asset-card skeleton-card">
        <div class="skeleton" style="width:40%;height:12px"></div>
        <div class="skeleton" style="width:70%;height:34px;margin-top:12px"></div>
        <div class="skeleton" style="width:55%;height:12px;margin-top:14px"></div>
      </div>
      <div class="skeleton" style="height:36px;margin:20px 0 8px;border-radius:12px"></div>
      ${skeletonRows(7)}`;
  }
  function skeletonRows(n) {
    return Array.from({ length: n }).map(
      () => html`<div class="quote-row quote-row--sk">
        <div style="flex:1"><div class="skeleton" style="width:64px;height:14px"></div><div class="skeleton" style="width:44px;height:10px;margin-top:6px"></div></div>
        <div class="skeleton" style="width:64px;height:24px"></div>
        <div style="width:84px;display:grid;justify-items:end;gap:6px"><div class="skeleton" style="width:60px;height:14px"></div><div class="skeleton" style="width:56px;height:20px"></div></div>
      </div>`
    );
  }

  function render(view) {
    const store = SS.store;
    const fmt = SS.fmt;
    let offs = [];
    let alive = true;

    if (!SS.booted) {
      SS.mount(view, html`<div class="topbar"><h1 class="topbar__title">行情</h1></div>${skeleton()}`);
      setTimeout(() => {
        SS.booted = true;
        if (alive) draw();
      }, 650);
    } else draw();

    function draw() {
      const p = store.portfolio();
      const c = store.state.clock;
      SS.mount(
        view,
        html`<header class="topbar">
            <h1 class="topbar__title">行情</h1>
            <div data-q="clock">${clockChip(c)}</div>
          </header>

          <section class="asset-card" data-role="asset" tabindex="0" role="link" aria-label="查看持仓">
            <div class="aurora" aria-hidden="true"></div>
            <div class="asset-card__head">
              <span class="t2 sm">总资产（元）</span>
              <button class="icon-btn icon-btn--sm" data-role="eye" aria-label="隐藏/显示金额">${SS.icon(prefs.hide ? "eyeOff" : "eye")}</button>
            </div>
            <div class="asset-card__total num" data-role="equity"></div>
            <div class="asset-card__row">
              <div>
                <div class="xs t3">今日盈亏</div>
                <div class="num sm" data-role="today"></div>
              </div>
              <div>
                <div class="xs t3">累计盈亏</div>
                <div class="num sm" data-role="net"></div>
              </div>
              <div>
                <div class="xs t3">可用资金</div>
                <div class="num sm" data-role="cash"></div>
              </div>
            </div>
          </section>

          <div class="list-head">
            <div class="seg seg--inline" data-role="list">
              <span class="seg__thumb" aria-hidden="true"></span>
              <button type="button" data-value="watch" class="${ui.list === "watch" ? "is-active" : ""}">自选</button>
              <button type="button" data-value="all" class="${ui.list === "all" ? "is-active" : ""}">全部</button>
            </div>
            <button type="button" class="sort-btn" data-role="sort">${SS.icon("sort")}<span>${SORT_TEXT[ui.sort]}</span></button>
          </div>
          <label class="search">
            ${SS.icon("search")}
            <input class="input" type="search" data-role="q" value="${ui.q}" placeholder="搜索代码 / 名称" autocomplete="off" enterkeyhint="search" aria-label="搜索股票" />
          </label>
          <div class="list-cols xs t3"><span>名称</span><span>走势</span><span>现价 / 涨跌</span></div>
          <div class="quote-list" data-role="rows"></div>
          <p class="hint xs t3">← 左滑行可快速买入 / 卖出</p>`
      );

      const $ = (r) => SS.$(`[data-role="${r}"]`, view);
      paintAsset(true);

      $("eye").addEventListener("click", (e) => {
        e.stopPropagation();
        prefs.hide = !prefs.hide;
        SS.mount($("eye"), SS.icon(prefs.hide ? "eyeOff" : "eye"));
        paintAsset(false);
      });
      $("asset").addEventListener("click", () => SS.router.navigate("/portfolio"));
      $("asset").addEventListener("keydown", (e) => e.key === "Enter" && SS.router.navigate("/portfolio"));

      SS.segmented($("list"), (v) => {
        ui.list = v;
        paintRows();
      });
      $("sort").addEventListener("click", () => {
        ui.sort = (ui.sort + 1) % 3;
        SS.$("span", $("sort")).textContent = SORT_TEXT[ui.sort];
        SS.haptic(5);
        refresh();
      });
      let qT = null;
      $("q").addEventListener("input", (e) => {
        clearTimeout(qT);
        qT = setTimeout(() => {
          const q = e.target.value.trim();
          if (q === ui.q) return;
          ui.q = q;
          refresh();
        }, 250);
      });
      $("rows").addEventListener("click", (e) => {
        if (e.target.closest('[data-role="more"],[data-role="retry"]')) loadAll(false);
      });
      // 滚动到列表底部自动加载下一页（按钮保留作为无 IntersectionObserver 时的兜底）
      const io =
        "IntersectionObserver" in window
          ? new IntersectionObserver((es) => es.some((en) => en.isIntersecting) && loadAll(false), { rootMargin: "320px 0px" })
          : null;
      if (all.saveId !== store.state.save.id) Object.assign(all, { saveId: store.state.save.id, items: [], cursor: null, total: 0, done: false, error: false, started: false });
      all.token++; // 丢弃上一次渲染遗留的请求
      all.loading = false;
      offs.push(() => io && io.disconnect());

      const swipe = SS.swipeRows($("rows"), {
        onAction: (side, code) => SS.orderSheet.open({ code, side }),
      });
      paintRows();
      if (!ui.hintShown) {
        ui.hintShown = true;
        setTimeout(swipe.peek, 900);
      }

      offs.push(
        store.on("tick", ({ clock, changed }) => {
          SS.mount(SS.$('[data-q="clock"]', view), clockChip(clock));
          for (const { code, dir } of changed) {
            const row = SS.$(`.swipe-row[data-code="${code}"]`, view);
            if (!row) continue;
            const s = store.quote(code);
            const tr = fmt.trend(s.change_bp);
            const pe = SS.$('[data-q="price"]', row);
            pe.textContent = fmt.price(s.price_cents);
            pe.className = `num quote-row__price ${tr}`;
            if (!SS.reducedMotion()) {
              pe.classList.remove("flash-up", "flash-down");
              void pe.offsetWidth;
              pe.classList.add(dir > 0 ? "flash-up" : "flash-down");
            }
            const ce = SS.$('[data-q="chg"]', row);
            ce.textContent = fmt.pctBp(s.change_bp);
            ce.className = `num pill pill--${tr}`;
            SS.mount(SS.$('[data-q="spark"]', row), raw(SS.chart.sparkline(s._spark || s._series, s.prev_close_cents)));
          }
          paintAsset(false);
        }),
        store.on("order", () => paintAsset(false)),
        // 分时历史加载完成：刷新对应行的迷你走势
        store.on("series", (codes) => {
          for (const code of codes) {
            const row = SS.$(`.swipe-row[data-code="${code}"]`, view);
            const s = store.quote(code);
            if (row && s) SS.mount(SS.$('[data-q="spark"]', row), raw(SS.chart.sparkline(s._spark || s._series, s.prev_close_cents)));
          }
        })
      );

      function paintAsset(first) {
        const p = store.portfolio();
        const eq = $("equity");
        if (prefs.hide) {
          cancelAnimationFrame(eq._cuRaf);
          eq.textContent = MASK;
          eq._cuValue = undefined;
        } else SS.countUp(eq, p.equity_cents, { format: (v) => fmt.yuan(v), duration: first ? 1400 : 600, from: first ? Math.round(p.equity_cents * 0.96) : undefined });
        const set = (el, cents, pct) => {
          el.className = `num sm ${prefs.hide ? "" : fmt.trend(cents)}`;
          el.textContent = prefs.hide ? MASK : fmt.yuanCompact(cents, { sign: true }) + (pct != null ? ` ${fmt.pctBp(pct)}` : "");
        };
        set($("today"), p._today_pnl_cents);
        set($("net"), p.net_pnl_cents);
        $("cash").textContent = prefs.hide ? MASK : fmt.yuanCompact(p.cash_cents);
      }

      /** 切换排序/搜索：「全部」重置分页并重新请求，「自选」本地重排 */
      function refresh() {
        if (ui.list === "all") {
          Object.assign(all, { items: [], cursor: null, total: 0, done: false, error: false, started: false });
          all.token++;
          all.loading = false;
        }
        paintRows();
      }

      function matches(s) {
        return !ui.q || s.code.includes(ui.q) || s.name.toLowerCase().includes(ui.q.toLowerCase());
      }

      /** 请求「全部」的下一页（reset 由 refresh 完成，这里只负责取下一页） */
      async function loadAll() {
        if (all.loading || all.done) return;
        const tk = all.token;
        all.loading = true;
        all.error = false;
        all.started = true;
        const from = all.items.length;
        paintRows(from);
        try {
          const sortArgs = ui.sort === 0 ? {} : { sort: "change", order: ui.sort === 1 ? "desc" : "asc" };
          const r = await store.listQuotes({ ...sortArgs, q: ui.q, cursor: all.cursor, limit: PAGE });
          if (!alive || tk !== all.token) return;
          const seen = new Set(all.items.map((x) => x.code));
          all.items.push(...r.items.filter((x) => !seen.has(x.code)));
          all.cursor = r.next_cursor;
          all.done = !r.next_cursor;
          all.total = r.total;
          store.loadSeries(r.items.map((x) => x.code));
        } catch (e) {
          if (alive && tk === all.token) {
            all.error = true;
            store.notifyError(e);
          }
        } finally {
          if (alive && tk === all.token) {
            all.loading = false;
            paintRows(from);
          }
        }
      }

      function paintFoot(rows) {
        const foot = SS.$('[data-role="foot"]', rows);
        if (!foot) return;
        if (all.loading) SS.mount(foot, skeletonRows(all.items.length ? 3 : 7));
        else if (all.error) SS.mount(foot, html`<button type="button" class="load-more" data-role="retry">加载失败，点击重试</button>`);
        else if (!all.done) SS.mount(foot, html`<button type="button" class="load-more" data-role="more">加载更多</button>`);
        else if (!all.items.length)
          SS.mount(
            foot,
            html`<div class="empty">
              <div class="empty__title">${ui.q ? "没有匹配的股票" : "暂无行情"}</div>
              ${ui.q ? html`<p class="t3 sm">换个代码或名称试试</p>` : ""}
            </div>`
          );
        else SS.mount(foot, html`<p class="hint xs t3">已显示全部 ${all.total} 只</p>`);
        if (io) {
          io.disconnect();
          const more = SS.$('[data-role="more"]', foot);
          if (more) io.observe(more);
        }
      }

      /** appendFrom > 0：「全部」追加新到的页，不重绘已有行（保持滑动状态与入场动画） */
      function paintRows(appendFrom = 0) {
        const rows = $("rows");
        if (ui.list === "all") {
          if (!all.started) {
            SS.mount(rows, html`<div class="animated-list" data-role="items"></div><div data-role="foot"></div>`);
            loadAll();
            return;
          }
          let host = SS.$('[data-role="items"]', rows);
          if (appendFrom > 0 && host) {
            host.insertAdjacentHTML("beforeend", all.items.slice(appendFrom).map((s) => String(rowHtml(s))).join(""));
          } else {
            swipe.close();
            SS.mount(rows, html`<div class="animated-list" data-role="items">${all.items.map(rowHtml)}</div><div data-role="foot"></div>`);
            host = SS.$('[data-role="items"]', rows);
          }
          SS.animatedList(host);
          paintFoot(rows);
          return;
        }
        io && io.disconnect();
        let list = store.state.stocks.filter((s) => s.watchlisted && matches(s));
        if (ui.sort === 1) list.sort((a, b) => b.change_bp - a.change_bp);
        else if (ui.sort === 2) list.sort((a, b) => a.change_bp - b.change_bp);
        else list.sort((a, b) => (a.code < b.code ? -1 : 1));
        swipe.close();
        if (!list.length) {
          SS.mount(
            rows,
            ui.q
              ? html`<div class="empty"><div class="empty__title">没有匹配的自选股</div><p class="t3 sm">切到「全部」可搜索全市场</p></div>`
              : html`<div class="empty">
                  <div class="empty__title">${SS.blurText("还没有自选股")}</div>
                  <p class="t3 sm">在个股详情页点右上角星标即可加入自选</p>
                  <button type="button" class="btn btn-sm" data-role="go-all">浏览全部行情</button>
                </div>`
          );
          const go = SS.$('[data-role="go-all"]', rows);
          if (go) go.addEventListener("click", () => SS.$('[data-value="all"]', view).click());
          return;
        }
        SS.mount(rows, html`<div class="animated-list">${list.map(rowHtml)}</div>`);
        SS.animatedList(rows);
        store.loadSeries(list.map((x) => x.code));
      }
    }

    return () => {
      alive = false;
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.market = { tab: "market", render };
})();
