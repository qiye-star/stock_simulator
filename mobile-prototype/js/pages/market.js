/**
 * 行情 / 自选（#/market），布局对照画板 Main：
 *   - 顶栏“行情” + 搜索图标（展开输入框）；
 *   - 交易状态栏 SS.tradeBar（full）：状态、时间、倒计时、时段进度；点开交易时间说明（首次进入主动弹一次）；
 *   - banner 挂载点 market.banner（快讯条/挑战横幅由各玩法注册）；
 *   - 总资产卡（直接显示终值，无滚动动效；极淡 Aurora），今日/累计盈亏，可一键隐藏金额；点卡片进入持仓；
 *   - 自选 / 全部 分段；列表表头点“涨跌”循环排序，搜索（代码/名称）；
 *     自选来自本地缓存；「全部」走服务端分页（store.listQuotes：limit/cursor/q/sort），滚动到底自动加载更多；
 *   - 行：名称 + `代码 · 行业` | 迷你走势 | 现价 + 涨跌幅；左滑露出 买入/卖出，直接弹下单抽屉；点行进入详情；
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
  const SORT_TEXT = ["现价 / 涨跌", "涨跌 ↓", "涨跌 ↑"];
  /** 玩法分段（SS.marketLists）的行情缓存：value → {saveId, items, notes, at, loading, token, error} */
  const custom = {};

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

  /** note：行情分段的注记（如“事发”“传导”），可选 */
  function rowHtml(s, note) {
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
          <div class="xs t3 num">${s.code} · ${s.industry}${s.code === "999999" ? html` <span class="tag">彩蛋</span>` : ""}${note ? html` <span class="tag ${note === "事发" ? "tag--accent" : ""}">${note}</span>` : ""}</div>
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
    return html`<div class="skeleton" style="height:150px;border-radius:18px;margin-bottom:12px"></div>
      <div class="asset-card skeleton-card">
        <div class="skeleton" style="width:40%;height:12px"></div>
        <div class="skeleton" style="width:70%;height:34px;margin-top:12px"></div>
        <div class="skeleton" style="width:55%;height:12px;margin-top:14px"></div>
      </div>
      <div class="skeleton" style="height:36px;margin:12px 0 8px;border-radius:12px"></div>
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
      // 玩法注册的行情分段（如“事件相关”）；当前选中的分段已不可见时回到自选
      const extraLists = SS.marketLists.list();
      if (ui.list !== "watch" && ui.list !== "all" && !extraLists.some((v) => v.value === ui.list)) ui.list = "watch";
      SS.mount(
        view,
        html`<header class="topbar">
            <h1 class="topbar__title">行情</h1>
            <button type="button" class="icon-btn" data-role="search-toggle" aria-label="搜索" aria-expanded="false">${SS.icon("search")}</button>
          </header>

          <div data-role="tradebar"></div>
          <div data-role="recap"></div>
          <div class="market-banner" data-role="banner"></div>

          <section class="asset-card" data-role="asset" tabindex="0" role="link" aria-label="查看持仓">
            <div class="aurora" aria-hidden="true"></div>
            <div class="asset-card__head">
              <span class="t2 sm">总资产（元）</span>
              <button class="icon-btn icon-btn--sm" data-role="eye" aria-label="隐藏/显示金额">${SS.icon(prefs.hide ? "eyeOff" : "eye")}</button>
            </div>
            <div class="asset-card__total num" data-role="equity"></div>
            <div class="asset-card__row">
              <span class="t2 sm">今日 <span class="num" data-role="today"></span></span>
              <span class="t2 sm">累计 <span class="num" data-role="net"></span></span>
            </div>
          </section>

          <div class="seg seg--inline-full seg--list" data-role="list">
            <span class="seg__thumb" aria-hidden="true"></span>
            <button type="button" data-value="watch" class="${ui.list === "watch" ? "is-active" : ""}">自选</button>
            <button type="button" data-value="all" class="${ui.list === "all" ? "is-active" : ""}">全部</button>
            ${extraLists.map((v) => html`<button type="button" data-value="${v.value}" class="${ui.list === v.value ? "is-active" : ""}">${v.label}</button>`)}
          </div>
          <label class="search" data-role="search" hidden>
            ${SS.icon("search")}
            <input class="input" type="search" data-role="q" value="${ui.q}" placeholder="搜索代码 / 名称" autocomplete="off" enterkeyhint="search" aria-label="搜索股票" />
          </label>
          <div class="list-cols xs t3">
            <span>名称</span><span>走势</span>
            <button type="button" class="list-cols__sort" data-role="sort" aria-label="切换排序">${SORT_TEXT[ui.sort]}</button>
          </div>
          <div class="quote-list" data-role="rows"></div>
          <p class="hint xs t3">← 左滑行可快速买入 / 卖出</p>`
      );

      const $ = (r) => SS.$(`[data-role="${r}"]`, view);
      offs.push(SS.tradeBar.mount($("tradebar"), { variant: "full" }));
      offs.push(SS.closeSummary.mountRecap($("recap")));
      offs.push(SS.slots.mount("market.banner", $("banner")));
      paintAsset();

      $("eye").addEventListener("click", (e) => {
        e.stopPropagation();
        prefs.hide = !prefs.hide;
        SS.mount($("eye"), SS.icon(prefs.hide ? "eyeOff" : "eye"));
        paintAsset();
      });
      $("asset").addEventListener("click", () => SS.router.navigate("/portfolio"));
      $("asset").addEventListener("keydown", (e) => e.key === "Enter" && SS.router.navigate("/portfolio"));

      SS.segmented($("list"), (v) => {
        ui.list = v;
        paintRows();
      });
      $("sort").addEventListener("click", () => {
        ui.sort = (ui.sort + 1) % 3;
        $("sort").textContent = SORT_TEXT[ui.sort];
        $("sort").classList.toggle("is-on", ui.sort !== 0);
        SS.haptic(5);
        refresh();
      });
      $("sort").classList.toggle("is-on", ui.sort !== 0);

      // 搜索：图标展开输入框；有关键词时常开，清空并失焦后自动收起
      const showSearch = (on, focus) => {
        $("search").hidden = !on;
        $("search-toggle").setAttribute("aria-expanded", String(on));
        if (on && focus) $("q").focus();
      };
      showSearch(!!ui.q, false);
      $("search-toggle").addEventListener("click", () => {
        if ($("search").hidden) showSearch(true, true);
        else if ($("q").value.trim()) $("q").focus();
        else showSearch(false);
      });
      $("q").addEventListener("blur", () => {
        if (!$("q").value.trim()) showSearch(false);
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
        onAction: (side, code) => {
          // 不可交易时（午休 / 收盘 / 开盘前）左滑不打开抽屉，只提示原因（07 §7.4 第 7 条）
          const why = SS.orderSheet.untradable();
          if (why) return SS.toast(why, { icon: null, duration: 1800 });
          SS.orderSheet.open({ code, side });
        },
      });
      paintRows();
      // 首次进入先弹交易时间说明；弹出时本次不再做左滑提示
      setTimeout(() => {
        if (!alive) return;
        if (SS.clockHelp.maybeAutoOpen()) return;
        if (!ui.hintShown) {
          ui.hintShown = true;
          swipe.peek();
        }
      }, 400);

      offs.push(
        store.on("tick", ({ changed }) => {
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
          paintAsset();
        }),
        store.on("order", () => paintAsset()),
        // 分时历史加载完成：刷新对应行的迷你走势
        store.on("series", (codes) => {
          for (const code of codes) {
            const row = SS.$(`.swipe-row[data-code="${code}"]`, view);
            const s = store.quote(code);
            if (row && s) SS.mount(SS.$('[data-q="spark"]', row), raw(SS.chart.sparkline(s._spark || s._series, s.prev_close_cents)));
          }
        })
      );

      /** 总资产直接写终值（无滚动动效）；隐藏金额时显示 **** */
      function paintAsset() {
        const p = store.portfolio();
        $("equity").textContent = prefs.hide ? MASK : fmt.yuan(p.equity_cents);
        const set = (el, cents, text) => {
          el.className = `num ${prefs.hide ? "" : fmt.trend(cents)}`;
          el.textContent = prefs.hide ? MASK : text;
        };
        set($("today"), p.day_pnl_cents, fmt.yuan(p.day_pnl_cents, { sign: true }));
        const bp = p.initial_fund_cents ? Math.round((p.net_pnl_cents / p.initial_fund_cents) * 10000) : 0;
        set($("net"), p.net_pnl_cents, fmt.pctBp(bp));
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
        const def = extraLists.find((v) => v.value === ui.list);
        if (def) return paintCustom(def);
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

      /** 玩法分段：def.load() → {items, notes}；按存档缓存，切换分段时若超过 20 秒才重拉 */
      function paintCustom(def) {
        const rows = $("rows");
        io && io.disconnect();
        const sid = store.state.save.id;
        let c = custom[def.value];
        if (!c || c.saveId !== sid) c = custom[def.value] = { saveId: sid, items: null, notes: {}, error: null, at: 0, loading: false, token: 0 };
        if (!c.loading && (c.items == null || Date.now() - c.at > 20000)) loadCustom(def, c);
        if (c.items == null) {
          swipe.close();
          if (c.error && !c.loading)
            SS.mount(rows, html`<div class="empty"><button type="button" class="load-more" data-role="custom-retry">加载失败，点击重试</button></div>`);
          else SS.mount(rows, skeletonRows(6));
          const retry = SS.$('[data-role="custom-retry"]', rows);
          if (retry) retry.addEventListener("click", () => loadCustom(def, c));
          return;
        }
        let list = c.items.filter(matches);
        if (ui.sort === 1) list = list.slice().sort((a, b) => b.change_bp - a.change_bp);
        else if (ui.sort === 2) list = list.slice().sort((a, b) => a.change_bp - b.change_bp);
        swipe.close();
        if (!list.length) {
          SS.mount(rows, html`<div class="empty"><div class="empty__title">${ui.q ? "没有匹配的股票" : def.empty || "暂无"}</div></div>`);
          return;
        }
        SS.mount(rows, html`<div class="animated-list">${list.map((s) => rowHtml(s, c.notes[s.code]))}</div>`);
        SS.animatedList(rows);
        store.loadSeries(list.map((x) => x.code));
      }

      async function loadCustom(def, c) {
        const tk = ++c.token;
        c.loading = true;
        c.error = null;
        try {
          const r = await def.load();
          if (!alive || c.token !== tk) return;
          c.items = r.items || [];
          c.notes = r.notes || {};
          c.at = Date.now();
        } catch (e) {
          if (!alive || c.token !== tk) return;
          c.error = e;
          store.notifyError(e);
        } finally {
          if (alive && c.token === tk) c.loading = false;
        }
        if (alive && c.token === tk && ui.list === def.value) paintRows();
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
