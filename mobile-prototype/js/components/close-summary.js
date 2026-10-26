/**
 * 收盘小结 SS.closeSummary（08 §4.4；数据来自 GET /day-summary，07 §1.4 / §5.4）。
 *
 *   const unwatch = SS.closeSummary.watch();     订阅 phase / tick / save：v2 收盘时自动打开（每个交易日一次）
 *   SS.closeSummary.open({ tradingDay? })         手动打开；缺省为当前交易日（有倒计时），历史日只读
 *   SS.closeSummary.close();
 *   const unmount = SS.closeSummary.mountRecap(el);  行情页顶部“查看昨日小结”条（离线错过收盘时补看）
 *
 * 倒计时只经 SS.clockModel.closeTimer（07 §5.4：停留到 fast_forward_at 自动快进，文案说 9:30 开盘）；
 * “现在就开盘” = 恢复（若暂停）+ store.skipClock()（v2 跳过 §6.5）；“先暂停” = store.setPaused(true)。
 * 展示记录：localStorage["ss.lastDay." + saveId] = 最近已展示 / 已补看的交易日（try/catch，失败时退化为会话内记忆）。
 * 层级：.close-summary 在 .app 内 z-index 30（高于 Dock 20，低于抽屉 50）；不响应遮罩点击。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  let layer = null; // 当前打开的 DOM
  let cur = null; // { day, live, total, paused, token }
  let timer = null;
  let resyncT = null;
  let seq = 0; // 请求序号：丢弃过期的 loadDaySummary 结果
  let shownDay = null; // 本会话内已展示过的交易日（存档切换时清空）
  let lastDay = null; // 最近一次看到的 trading_day（用于“开盘”提示）
  let watching = false;

  const ls = {
    get(k) {
      try {
        return localStorage.getItem(k);
      } catch (_) {
        return null;
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(k, String(v));
      } catch (_) {}
    },
  };
  const saveId = () => (SS.store.state.save && SS.store.state.save.id) || "";
  const recordKey = () => `ss.lastDay.${saveId()}`;
  /** 最近已展示 / 已补看的交易日；未记录时返回 null */
  function seenDay() {
    const v = ls.get(recordKey());
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isInteger(n) ? n : null;
  }
  const markSeen = (day) => ls.set(recordKey(), day);

  const clock2 = () => {
    const st = SS.store.state;
    return SS.clockModel.normalize(st.clock, { refresh_rate_ms: st.user && st.user.refresh_rate_ms, save_rules: st.save && st.save.clock_rules, now: Date.now() });
  };
  const blocked = () => !SS.ready || /^#\/(login|replay)/.test(location.hash) || !!SS.$(".app .sheet-layer");

  // ---------- 数据：板块前三（行业等权）、个股前三 ----------
  /** 按行业等权平均 change_bp → { up:[{name,bp}], down:[…] }，各 3 个 */
  function sectorTop(list) {
    const g = new Map();
    for (const s of list) {
      if (!s.industry) continue;
      const a = g.get(s.industry) || { sum: 0, n: 0 };
      a.sum += s.change_bp;
      a.n += 1;
      g.set(s.industry, a);
    }
    const rows = [...g].map(([name, a]) => ({ name, bp: Math.round(a.sum / a.n) })).sort((a, b) => b.bp - a.bp);
    return { up: rows.slice(0, 3), down: rows.slice(-3).reverse() };
  }

  // ---------- 渲染 ----------
  const cell = (label, value, cls = "", big = true) => html`<div class="cs-cell">
    <span class="t2 xs">${label}</span><span class="num ${big ? "cs-cell__v" : "cs-cell__v cs-cell__v--sm"} ${cls}">${value}</span>
  </div>`;
  const listRow = (name, bp) => html`<div class="sector-list__row"><span>${name}</span><span class="num ${SS.fmt.trend(bp)}">${SS.fmt.pctBp(bp)}</span></div>`;
  const skel = () => html`<div class="skeleton cs-skel"></div>`;

  /** 2×2 卡：今日盈亏 / 今日收益率 / 成交 / 明日可卖（t0 与历史日隐藏最后一格） */
  function gridHtml(sum, live, t0) {
    const fmt = SS.fmt;
    const pnl = sum.day_pnl_cents;
    const holdings = SS.store.portfolio().holdings.filter((h) => h.quantity - h.sellable_quantity > 0);
    const frozen = holdings[0] ? holdings[0].quantity - holdings[0].sellable_quantity : 0;
    const sellable = holdings.length
      ? `${holdings[0].name} ${fmt.qty(frozen)} 股${holdings.length > 1 ? ` 等 ${holdings.length} 只` : ""}`
      : "—";
    return html`${cell("今日盈亏", pnl == null ? "—" : fmt.yuan(pnl, { sign: true }), fmt.trend(pnl))}
      ${cell("今日收益率", sum.day_pnl_bp == null ? "—" : fmt.pctBp(sum.day_pnl_bp), fmt.trend(sum.day_pnl_bp))}
      ${cell("成交", `${sum.trades.count} 笔`, "", false)}
      ${live && !t0 ? cell("明日可卖", sellable, "", false) : ""}`;
  }

  function sectorsHtml(title, rows, emptyText) {
    return html`<div class="sector-list"><span class="t2 xs">${title}</span>${rows.length ? rows.map((r) => listRow(r.name, r.bp)) : html`<span class="t3 sm">${emptyText}</span>`}</div>`;
  }

  function open({ tradingDay } = {}) {
    if (layer || blocked()) return false;
    const c = clock2();
    const store = SS.store;
    const day = tradingDay == null ? c.trading_day : Number(tradingDay);
    const live = day === c.trading_day;
    if (live && c.phase !== "closed") return false; // 当日小结只在收盘停留中出现；盘中不展示
    if (live) {
      shownDay = c.trading_day;
      markSeen(c.trading_day);
    }
    const t0 = !!(store.state.save && store.state.save.t0_mode);
    const token = ++seq;
    cur = { day, live, total: null, paused: null, token, t0 };

    layer = SS.el(html`<div class="close-summary" role="dialog" aria-modal="true" aria-labelledby="cs-title">
      <div class="close-summary__scroll">
        <div class="close-summary__head">
          <span class="close-summary__badge"><i aria-hidden="true"></i>已收盘 · 15:00</span>
          <span class="t2 sm num" data-role="day">第 ${SS.fmt.dayNo(day)} 个交易日</span>
        </div>
        <div>
          <h2 class="close-summary__title" id="cs-title" tabindex="-1">${live ? "今日收盘小结" : "收盘小结"}</h2>
          <p class="close-summary__lead">${live ? "今天这根日 K 已经生成。看完后会自动进入下一个交易日。" : "这一天的收盘数据，仅供查看。"}</p>
        </div>
        <div class="close-summary__card close-summary__grid" data-role="grid">${skel()}${skel()}</div>
        <section class="close-summary__card" data-role="events-card" hidden>
          <h3 class="close-summary__h">今天的大事</h3>
          <div data-role="events"></div>
        </section>
        <section class="close-summary__card close-summary__sectors" data-role="sectors">${skel()}</section>
      </div>
      <div class="close-summary__foot" data-role="foot">
        <div class="close-summary__countdown" data-role="countdown" hidden>
          <div class="close-summary__track"><i data-role="bar"></i></div>
          <span class="num t2 sm" data-role="count"></span>
        </div>
        <div class="close-summary__actions" data-role="actions"></div>
      </div>
    </div>`);
    SS.$(".app").appendChild(layer);
    SS.$("#cs-title", layer).focus({ preventScroll: true });
    SS.$('[data-role="actions"]', layer).addEventListener("click", onAction); // 只挂一次；按钮随 paintFoot 替换

    paintFoot();
    if (live) timer = setInterval(paintTimer, 1000);
    paintTimer();
    loadData(day, live, token);
    return true;
  }

  async function loadData(day, live, token) {
    const store = SS.store;
    let sum = null;
    try {
      sum = await store.loadDaySummary(day);
    } catch (e) {
      if (e && e.status === 401) return;
      sum = null; // 旧后端 404 / 网络失败：用本地数据兜底
    }
    if (token !== seq || !layer) return;
    const grid = SS.$('[data-role="grid"]', layer);
    if (sum) {
      SS.mount(grid, gridHtml(sum, live, cur.t0));
    } else {
      const local = { day_pnl_cents: store.portfolio().day_pnl_cents, day_pnl_bp: store.portfolio().day_pnl_bp, trades: { count: store.trades().filter((t) => t.trading_day === day).length } };
      SS.mount(grid, gridHtml(local, live, cur.t0));
    }

    // 今天的大事：玩法挂载点 closeSummary.extra（无 provider 或全空时整卡隐藏）
    const evHost = SS.$('[data-role="events"]', layer);
    SS.mount(evHost, "");
    SS.slots.mount("closeSummary.extra", evHost, { trading_day: day });
    SS.$('[data-role="events-card"]', layer).hidden = !SS.$$(".slot", evHost).some((n) => n.childElementCount || n.textContent.trim());

    // 板块前三（行业等权，行情数据用红绿）；历史日或失败时退回个股前三
    const secEl = SS.$('[data-role="sectors"]', layer);
    let sectors = null;
    if (live) {
      try {
        sectors = sectorTop(await store.loadAllQuotes());
      } catch (e) {
        if (e && e.status === 401) return;
      }
    }
    if (token !== seq || !layer) return;
    if (sectors) {
      SS.mount(secEl, html`${sectorsHtml("板块涨幅前三", sectors.up, "—")}${sectorsHtml("板块跌幅前三", sectors.down, "—")}`);
    } else if (sum) {
      SS.mount(secEl, html`${sectorsHtml("个股涨幅前三", sum.top_gainers.map((q) => ({ name: q.name, bp: q.change_bp })), "—")}${sectorsHtml("个股跌幅前三", sum.top_losers.map((q) => ({ name: q.name, bp: q.change_bp })), "—")}`);
    } else {
      SS.mount(secEl, html`<span class="t3 sm">收盘数据暂不可用</span>`);
    }
  }

  /** 底部按钮：随暂停状态切换（倒计时中：现在就开盘 / 先暂停；暂停中：继续 / 收起；历史日：关闭） */
  function paintFoot() {
    if (!layer || !cur) return;
    const c = clock2();
    const paused = cur.live ? c.paused : false;
    cur.paused = paused;
    const actions = SS.$('[data-role="actions"]', layer);
    SS.$('[data-role="countdown"]', layer).hidden = !cur.live;
    let btns;
    if (!cur.live) btns = html`<button type="button" class="btn btn-primary cs-btn" data-act="close">关闭</button>`;
    else if (paused) btns = html`<button type="button" class="btn btn-primary cs-btn" data-act="resume">继续</button><button type="button" class="btn cs-btn cs-btn--ghost" data-act="collapse">收起</button>`;
    else btns = html`<button type="button" class="btn btn-primary cs-btn" data-act="open-now">现在就开盘</button><button type="button" class="btn cs-btn cs-btn--ghost" data-act="pause">先暂停</button>`;
    SS.mount(actions, btns);
  }

  /** 每秒（以及每个 tick）刷新倒计时：只改进度条与文字 */
  function paintTimer() {
    if (!layer || !cur) return;
    const c = clock2();
    if (!cur.live) return;
    if (c.paused !== cur.paused) paintFoot();
    const t = SS.clockModel.closeTimer(c, { now: Date.now(), total_ms: cur.total });
    if (t.paused) cur.total = null;
    else if (cur.total == null && t.remain_ms > 0) cur.total = t.remain_ms;
    SS.$('[data-role="bar"]', layer).style.width = `${(t.progress * 100).toFixed(2)}%`;
    SS.$('[data-role="count"]', layer).textContent = t.text;
    // 剩余为 0 后 5 秒内没有新 tick：重新同步（07 §7.4 第 3 条 / 08 §4.4）
    if (t.done && !resyncT) {
      resyncT = setTimeout(() => {
        resyncT = null;
        SS.store.start();
      }, 5000);
    } else if (!t.done && resyncT) {
      clearTimeout(resyncT);
      resyncT = null;
    }
  }

  async function onAction(e) {
    const btn = e.target.closest("[data-act]");
    if (!btn || !layer) return;
    const act = btn.dataset.act;
    const store = SS.store;
    try {
      if (act === "close" || act === "collapse") return close();
      if (act === "pause") {
        await store.setPaused(true);
        paintFoot();
      } else if (act === "resume") {
        if (!(await SS.guards.check("resume"))) return;
        await store.setPaused(false);
        paintFoot();
      } else if (act === "open-now") {
        if (!(await SS.guards.check("resume"))) return;
        btn.disabled = true;
        if (clock2().paused) await store.setPaused(false);
        await store.skipClock();
        close();
      }
    } catch (err) {
      if (btn) btn.disabled = false;
      store.notifyError(err);
    }
  }

  function close() {
    if (!layer) return;
    layer.remove();
    layer = null;
    cur = null;
    clearInterval(timer);
    timer = null;
    clearTimeout(resyncT);
    resyncT = null;
    seq++; // 作废未完成的请求
  }

  /** 时段/时钟变化：收盘进入 → 打开（每个交易日一次）；离开收盘 → 关闭；交易日增加 → 开盘提示（v2） */
  function onTick() {
    if (!SS.ready) return close();
    const c = clock2();
    if (lastDay != null && c.trading_day > lastDay && c.rules === "v2") SS.toast(`第 ${SS.fmt.dayNo(c.trading_day)} 个交易日开盘`, { icon: null, duration: 1600 });
    lastDay = c.trading_day;
    if (layer && cur && cur.live && c.phase !== "closed") return close();
    if (c.rules === "v2" && c.phase === "closed" && shownDay !== c.trading_day && !layer) open();
    if (layer && cur && cur.live) {
      paintTimer();
    }
  }

  function onPhase(msg) {
    if (!SS.ready) return;
    if (msg.to === "closed") {
      const c = clock2();
      if (c.rules === "v2" && shownDay !== msg.trading_day && !layer) open();
    } else if (msg.from === "closed" && layer && cur && cur.live) close();
  }

  /** 订阅：返回取消函数。存档切换时清空会话记忆 */
  function watch() {
    if (watching) return () => {};
    watching = true;
    const offs = [
      SS.store.on("phase", onPhase),
      SS.store.on("tick", onTick),
      SS.store.on("save", () => {
        shownDay = null;
        lastDay = null;
        close();
      }),
    ];
    return () => {
      watching = false;
      offs.forEach((f) => f());
      close();
    };
  }

  // ---------- 行情页：昨日小结补看条 ----------
  /** 上次记录之后又收过盘（且不是本次）→ 返回要补看的交易日（cur-1），否则 null */
  function recapDay(c) {
    if (c.rules !== "v2") return null;
    const seen = seenDay();
    if (seen == null) {
      markSeen(c.trading_day - 1); // 第一次进入：不补看以前的
      return null;
    }
    return c.trading_day - 1 > seen ? c.trading_day - 1 : null;
  }

  function mountRecap(el) {
    const paint = () => {
      if (!SS.ready) return SS.mount(el, "");
      const day = recapDay(clock2());
      if (day == null) return SS.mount(el, "");
      SS.mount(
        el,
        html`<div class="recap-strip" role="group" aria-label="昨日小结">
          <button type="button" class="recap-strip__open" data-role="recap-open">查看昨日小结 ›</button>
          <button type="button" class="icon-btn recap-strip__close" data-role="recap-close" aria-label="关闭">${SS.icon("close")}</button>
        </div>`
      );
      SS.$('[data-role="recap-open"]', el).addEventListener("click", () => {
        markSeen(day);
        SS.mount(el, "");
        open({ tradingDay: day });
      });
      SS.$('[data-role="recap-close"]', el).addEventListener("click", () => {
        markSeen(day);
        SS.mount(el, "");
      });
    };
    paint();
    const off = SS.store.on("tick", paint);
    const off2 = SS.store.on("save", paint);
    return () => {
      off();
      off2();
      SS.mount(el, "");
    };
  }

  SS.closeSummary = { watch, open, close, mountRecap };
})();
