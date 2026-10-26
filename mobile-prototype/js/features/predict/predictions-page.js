/**
 * 我的预测（#/predictions?status=open|pending|settled，SS.pages.predictions）：
 *   顶栏返回 + “我的预测”；积分余额小卡（loadPoints）；分段 待答(open) / 待揭晓(answered) / 已揭晓(settled+expired)，由 query.status 初始化；
 *   行 .pred-row：事件标题、题数与状态 tag、右侧积分（已结算 +N，强调色）；待答行打开弹层，其它行进入 #/prediction/:id；游标加载更多。
 * 已揭晓 tab 的接口用 status=all，前端过滤并至多续拉 5 页（与快讯页同一做法）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.predictModel;
  const TABS = [
    ["open", "待答"],
    ["pending", "待揭晓"],
    ["settled", "已揭晓"],
  ];
  const EMPTY = {
    open: ["没有待答的预测卡", "重大事件发生时会弹出预测卡，答完或放弃后这里会清空"],
    pending: ["没有待揭晓的预测", "作答后会在这里等待揭晓"],
    settled: ["还没有已揭晓的预测", "揭晓后会显示得分与积分"],
  };
  const PAGE = 20;
  const MAX_FILL_PAGES = 5;

  function render(view, params) {
    const store = SS.store;
    const offs = [];
    let alive = true;
    let tab = TABS.some((t) => t[0] === (params.query && params.query.status)) ? params.query.status : "open";
    let items = [];
    let cursor = null;
    let seq = 0;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">我的预测</h1>
        </header>
        <div class="pred-page">
          <div class="card pred-page__points" data-role="points"></div>
          <div class="seg seg--3 seg--inline-full" data-role="tabs">
            <span class="seg__thumb" aria-hidden="true"></span>
            ${TABS.map(([v, t]) => html`<button type="button" data-value="${v}" class="${tab === v ? "is-active" : ""}">${t}</button>`)}
          </div>
          <div class="pred-list" data-role="list"></div>
        </div>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    const seg = SS.segmented($("tabs"), (v) => {
      tab = v;
      SS.router.replace(`/predictions?status=${v}`);
      reload();
    });
    seg.set(tab);

    function paintPoints(p) {
      SS.mount(
        $("points"),
        p
          ? html`<div><span class="t2 sm">预测积分余额</span><span class="num pred-page__bal">${SS.fmt.qty(p.balance)}</span></div>
              <span class="t2 xs num">今日已得 ${p.today_prediction_points} / 上限 ${p.daily_cap}</span>`
          : soonOrEmpty()
      );
    }
    const soonOrEmpty = () => html`<span class="t2 sm">积分信息暂不可用</span>`;

    function row(c) {
      const q = (c.questions || []).length;
      const tag = M.STATUS_TAG[c.status] || c.status;
      const pts = c.status === "settled" ? html`<span class="num pred-row__pts">+${c.points || 0}</span>` : html`<span class="t3 xs">—</span>`;
      const title = c.event ? c.event.title : "重大事件";
      const href = c.status === "open" ? "" : SS.href(`/prediction/${c.id}`);
      const inner = html`<span class="pred-row__main">
          <span class="pred-row__title">${title}</span>
          <span class="pred-row__tags"><span class="tag">${q} 题</span><span class="tag ${c.status === "open" ? "tag--accent" : ""}">${tag}</span></span>
        </span>${pts}${SS.icon("chevron", "pred-row__chev")}`;
      return c.status === "open"
        ? html`<button type="button" class="pred-row" data-open="${c.id}">${inner}</button>`
        : html`<a class="pred-row" href="${href}">${inner}</a>`;
    }

    function paintList() {
      const list = $("list");
      if (!items.length) {
        const [t, d] = EMPTY[tab];
        return SS.mount(list, html`<div class="empty empty--sm"><div class="empty__title">${t}</div><p class="t3 sm">${d}</p></div>`);
      }
      SS.mount(
        list,
        html`${items.map(row)}${cursor ? html`<button type="button" class="load-more" data-role="more">加载更多</button>` : ""}`
      );
    }

    /** 拉一页；已揭晓 tab 用 status=all 并过滤，不足一页时至多续拉 MAX_FILL_PAGES 页 */
    async function fetchPage(cur) {
      if (tab === "settled") {
        let got = [];
        let next = cur;
        for (let i = 0; i < MAX_FILL_PAGES; i++) {
          const r = await store.listPredictions({ status: "all", cursor: next, limit: PAGE });
          got = got.concat(r.items.filter((c) => M.tabFilter("settled", c)));
          next = r.next_cursor;
          if (got.length >= PAGE || !next) break;
        }
        return { items: got, next_cursor: next };
      }
      return store.listPredictions({ status: TABS_STATUS[tab], cursor: cur, limit: PAGE });
    }
    const TABS_STATUS = Object.fromEntries(TABS.map(([v]) => [v, SS.predictModel.TAB_STATUS[v]]));

    async function reload() {
      const my = ++seq;
      items = [];
      cursor = null;
      SS.mount($("list"), html`<div class="skeleton" style="height:56px;margin-top:10px"></div><div class="skeleton" style="height:56px;margin-top:10px"></div>`);
      try {
        const r = await fetchPage(null);
        if (!alive || my !== seq) return;
        items = r.items;
        cursor = r.next_cursor;
        paintList();
      } catch (err) {
        if (!alive || my !== seq) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") SS.mount($("list"), SS.soonCardHtml({ title: "我的预测", desc: "预测记录暂未开放。" }));
        else {
          SS.mount($("list"), html`<div class="empty"><div class="empty__title">加载失败</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`);
          SS.$('[data-role="retry"]', $("list")).addEventListener("click", reload);
        }
      }
    }

    $("list").addEventListener("click", async (e) => {
      const open = e.target.closest("[data-open]");
      if (open) return SS.predictionCard.open(open.dataset.open);
      if (e.target.closest('[data-role="more"]')) {
        const more = e.target.closest('[data-role="more"]');
        more.disabled = true;
        try {
          const r = await fetchPage(cursor);
          items = items.concat(r.items);
          cursor = r.next_cursor;
          paintList();
        } catch (err) {
          more.disabled = false;
          store.notifyError(err);
        }
      }
    });

    if (!store.predictEnabled()) {
      SS.mount($("list"), html`<div class="empty"><div class="empty__title">本存档未开启事件模式</div><p class="t3 sm">开启事件模式的存档里，重大事件会生成预测卡</p></div>`);
    } else {
      reload();
    }
    store.loadPoints().then(paintPoints).catch((err) => SS.mount($("points"), err && err.code === "FEATURE_UNAVAILABLE" ? html`<span class="t2 sm">预测积分 · 即将开放</span>` : soonOrEmpty()));
    offs.push(
      store.on("ws:prediction", () => {
        if (!alive) return;
        if (store.predictEnabled()) reload();
        store.loadPoints().then(paintPoints).catch(() => {});
      })
    );
    return () => {
      alive = false;
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.predictions = { tab: null, render };
})();
