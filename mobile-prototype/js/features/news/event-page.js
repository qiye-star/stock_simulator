/**
 * 事件详情（#/event/:id）：对照 EventDetail 画板。
 *   - 头部：重大 / 类型 / 子类型 / 传闻状态 tag、第 N 个交易日 HH:MM、标题；
 *   - 传导回放：按交易日选择（窗口 3 日，未来日禁用）；只显示 arrived_trading_day ≤ 选中日的节点；
 *     涨跌数字是到达后 3 个交易日的行业涨跌（后端口径），切日不重算；
 *   - 已揭示的边：节点行显示“强度 N · 滞后 D 天”（来自 GET /intel 的 edges，边 id = "来源>行业"，即 via_industry>industry）；
 *     购买情报后 store 的 "intel" 事件触发重绘；
 *   - 锁提示：未揭示的强度/滞后隐藏，右侧 event.intel 槽（⑥ 情报卡），⑤ 之前退回“看产业链”；
 *   - 后续快讯、事件的 event.footer 槽（⑥“你的预测”）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.newsModel;

  function render(view, params) {
    const store = SS.store;
    const id = params.id;
    const offs = [];
    let alive = true;
    let detail = null;
    let day = null;
    let loadSeq = 0;
    let unmountFooter = null;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">事件详情</h1>
        </header>
        <div class="event-body" data-role="body"></div>
        <div class="event-footer" data-role="footer"></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    function skeleton() {
      SS.mount(body(), html`<div class="skeleton" style="height:96px;border-radius:var(--r-lg);margin-top:8px"></div><div class="skeleton" style="height:180px;border-radius:var(--r-lg);margin-top:12px"></div>`);
    }

    function notice(title, desc, action) {
      SS.mount(
        body(),
        html`<div class="empty"><div class="empty__title">${title}</div>${desc ? html`<p class="t3 sm">${desc}</p>` : ""}${action || ""}</div>`
      );
    }

    /** 已揭示的边（来自情报状态缓存）：{ "from>to": { revealed_level, strength, lag_days } } */
    function revealMap() {
      const out = {};
      const intel = store.state.predict && store.state.predict.intel;
      ((intel && intel.edges) || []).forEach((e) => {
        out[e.edge_id] = { revealed_level: e.level, strength: e.strength, lag_days: e.lag_days };
      });
      return out;
    }


    async function load({ silent = false } = {}) {
      const seq = ++loadSeq;
      if (!silent) {
        detail = null;
        day = null;
        skeleton();
      }
      try {
        // 情报状态与事件并发拉取：揭示强度、传闻提示都依赖它；失败不影响事件本身
        const [d] = await Promise.all([store.loadEvent(id), store.loadIntel().catch(() => null)]);
        if (!alive || seq !== loadSeq) return;
        detail = d;
        if (day == null) day = M.propWindow(d, store.state.clock.trading_day).defaultDay;
        paint();
        if (!unmountFooter) {
          const host = SS.$('[data-role="footer"]', view);
          const un = SS.slots.mount("event.footer", host, { event: d });
          unmountFooter = un;
        }
      } catch (err) {
        if (!alive || seq !== loadSeq) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") SS.mount(body(), SS.soonCardHtml({ title: "事件详情", desc: "事件详情暂未开放。" }));
        else if (err && err.code === "EVENTS_DISABLED") notice("本存档未开启事件模式", "事件模式需要在新建存档时开启");
        else if (err && err.code === "EVENT_NOT_FOUND")
          notice("事件不存在或尚未发布", "", html`<a class="btn btn-sm" href="${SS.href("/news")}">返回快讯</a>`);
        else
          SS.mount(body(), html`<div class="empty"><div class="empty__title">加载失败</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`);
        const retry = SS.$('[data-role="retry"]', body());
        if (retry) retry.addEventListener("click", () => load());
      }
    }

    /** 头部标签行与标题 */
    function headHtml(d) {
      const first = d.news && d.news.length ? d.news[0] : null;
      const rumor = d.kind === "rumor" && d.rumor_status ? M.RUMOR_TEXT[d.rumor_status] : null;
      return html`<div class="event-head">
        <div class="event-head__tags">
          ${d.major ? html`<span class="tag tag--accent">重大</span>` : ""}
          <span class="tag">${M.KIND_TEXT[d.kind] || d.kind}</span>
          ${d.subtype ? html`<span class="tag">${d.subtype}</span>` : ""}
          ${rumor ? html`<span class="tag tag--strong">${rumor}</span>` : ""}
          ${first ? html`<span class="num t2 xs">第 ${SS.fmt.dayNo(d.trading_day)} 个交易日 ${M.clockText(first.clock_minute)}</span>` : ""}
        </div>
        <h1 class="event-head__title">${d.title}</h1>
      </div>`;
    }

    function graphHtml(d, cur) {
      const steps = M.propSteps(d, day);
      if (!steps.length) return html`<p class="t3 sm prop-empty">${day > cur ? "这一天还没有节点到达" : "暂无可传导的行业节点"}</p>`;
      const rev = revealMap();
      return html`<div class="prop-steps">${steps.map((s) => {
        const rv = s.source ? "" : M.revealText(M.revealOf(rev, s));
        return s.source
          ? html`<div class="prop-step prop-step--source"><span class="prop-node prop-node--source"><span class="prop-node__name">${s.industry}</span><span class="xs t2">事发</span></span></div>`
          : html`<div class="prop-step" style="--hop:${s.hop}">
              <span class="prop-step__from">${s.from || "—"}</span>
              <span class="prop-step__rel">${s.relation_text}${rv ? html` · <span class="num">${rv}</span>` : ""}<span aria-hidden="true"> ›</span></span>
              <span class="prop-node prop-node--${s.tone}"><span class="prop-node__name">${s.industry}</span><span class="prop-node__v num">${s.change_bp == null ? "—" : SS.fmt.pctBp(s.change_bp)}</span></span>
            </div>`;
      })}</div>`;
    }

    const lockText = (d) => M.lockText(M.propSteps(d, day), revealMap());

    function paint() {
      const d = detail;
      const cur = store.state.clock.trading_day;
      const win = M.propWindow(d, cur);
      const intel = SS.slots.html("event.intel", { event: d });
      const link = d.source_industry ? html`<a href="${SS.href("/chain", { focus: d.source_industry })}">看产业链</a>` : "";
      const later = (d.news || []).slice(1);
      SS.mount(
        body(),
        html`${headHtml(d)}
          <section class="card prop-card">
            <div class="prop-card__head"><h2 class="prop-card__title">传导回放</h2><span class="t2 xs num">已走 ${win.elapsed} / ${M.PROP_DAYS} 个交易日</span></div>
            <div class="prop-graph" data-role="graph">${graphHtml(d, cur)}</div>
            <p class="t3 xs prop-note">涨跌为节点到达后 3 个交易日的行业等权涨跌</p>
            <div class="prop-days" role="tablist" aria-label="选择交易日">
              ${win.days.map((x) => {
                const future = x > cur;
                const on = x === day;
                return html`<button type="button" role="tab" class="prop-days__tab ${on ? "is-active" : ""} ${future ? "is-future" : ""}" aria-selected="${String(on)}" data-day="${x}" ${future ? "disabled" : ""}>第 ${SS.fmt.dayNo(x)} 日</button>`;
              })}
            </div>
            <div class="lock-note">
              ${SS.icon("lock", "lock-note__icon")}
              <span class="t2 lock-note__text">${lockText(d)}</span>
              <span class="lock-note__action">${String(intel) ? intel : link}</span>
            </div>
          </section>
          ${later.length
            ? html`<section class="card later-card"><h2 class="card__title">后续快讯</h2>
                ${later.map((x) => html`<div class="later-row"><span class="num t2 xs">${SS.fmt.dayNo(x.trading_day)} 日 ${M.clockText(x.clock_minute)}</span>
                  <span class="later-row__body">${x.title}${x.kind === "rumor" ? html` <span class="tag">${M.STAGE_TEXT[x.stage] || "传闻"}</span>` : ""}</span></div>`)}
              </section>`
            : ""}`
      );
      SS.$$('[role="tab"][data-day]', body()).forEach((b) =>
        b.addEventListener("click", () => {
          if (b.disabled) return;
          SS.haptic(5);
          day = Number(b.dataset.day);
          paint();
        })
      );
    }

    load();
    offs.push(
      store.on("news:update", ({ items }) => {
        if (alive && (items || []).some((x) => x.event_id === id)) load({ silent: true });
      }),
      // 情报卡购买成功（边揭示 / 传闻提示）：刷新锁提示与节点强度，不重新请求事件
      store.on("intel", () => {
        if (alive && detail) paint();
      })
    );
    return () => {
      alive = false;
      offs.forEach((f) => f());
      if (unmountFooter) unmountFooter();
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.event = { tab: null, render };
})();
