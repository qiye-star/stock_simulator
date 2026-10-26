/**
 * 复盘选关（#/replay，SS.pages.replayList，二级页）：说明、进行中 / 已结算会话、关卡卡片。
 * 点关卡 → 底部抽屉：导语、标签、“匿名模式（推荐）”开关（默认开；关闭时提示实名积分减半且不进排行）、开始 → 创建复盘存档并进入会话页。
 * 支持 query：?level=<slug> 直接打开该关卡的抽屉（玩法页的关卡卡链接到这里）。
 * 后端没有复盘接口（FEATURE_UNAVAILABLE）时显示“即将开放”。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const U = () => SS.replayUi;
  const M = () => SS.replayModel;
  const store = () => SS.store;

  function openLevel(lv) {
    let masked = lv.masked_allowed !== false;
    SS.sheet.open({
      title: lv.title,
      className: "sheet-layer--replay",
      render(body, api) {
        SS.mount(
          body,
          html`<div class="replay-drawer">
            <p class="t2 sm">${lv.teaser}</p>
            <div class="replay-level__tags">
              ${(lv.tags || []).map((t) => html`<span class="tag">${t}</span>`)}
              <span class="tag">${M().difficultyText(lv.difficulty)}</span>
              <span class="tag">${lv.play_days} 个交易日</span>
              <span class="tag">${lv.stock_count} 只股票</span>
            </div>
            ${lv.masked_allowed === false
              ? html`<p class="t2 xs">本关卡为实名关卡，股票名称与日期不做隐藏。</p>`
              : html`<div class="replay-switch-row">
                  <div class="replay-switch-row__text">
                    <span>匿名模式（推荐）</span>
                    <span class="t2 xs" data-role="mask-note"></span>
                  </div>
                  <button type="button" class="switch is-on" role="switch" aria-checked="true" aria-label="匿名模式" data-role="mask"><i></i></button>
                </div>`}
            <button type="button" class="btn btn-primary btn-block btn-lg" data-role="start">开始复盘</button>
            <p class="t3 xs replay-drawer__foot">复盘只在开盘价与收盘价成交，行情随你逐阶段推进，看不到未来。</p>
          </div>`
        );
        const root = body;
        const sw = SS.$('[data-role="mask"]', root);
        const note = SS.$('[data-role="mask-note"]', root);
        const paintMask = () => {
          if (!sw) return;
          sw.classList.toggle("is-on", masked);
          sw.setAttribute("aria-checked", String(masked));
          note.textContent = masked ? "股票名与价格已隐去，积分全额计入" : "实名：积分减半，且不进排行";
        };
        paintMask();
        sw &&
          sw.addEventListener("click", () => {
            masked = !masked;
            paintMask();
          });
        const start = SS.$('[data-role="start"]', root);
        start.addEventListener("click", async () => {
          if (start.disabled) return;
          start.disabled = true;
          try {
            const s = await store().createReplaySession(lv.slug, { masked });
            api.close();
            SS.router.navigate(`/replay/${s.save_id}`);
          } catch (err) {
            start.disabled = false;
            store().notifyError(err);
          }
        });
      },
    });
  }

  function render(view, params) {
    const q = params.query || {};
    let alive = true;
    let levels = [];
    SS.mount(
      view,
      html`<header class="topbar"><a class="icon-btn" href="#/play" aria-label="返回">${SS.icon("back")}</a><h1 class="topbar__title">真实复盘</h1></header>
        <div class="replay-page" data-role="body"><div class="skeleton" style="height:120px;border-radius:16px;margin-top:8px"></div></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);

    function draw(sessions) {
      if (!alive) return;
      const active = sessions.filter((s) => s.status === "active");
      const settled = sessions.filter((s) => s.status === "settled");
      SS.mount(
        body(),
        html`<section class="card replay-intro">
            <p class="t2 sm">回到真实历史，股票名已隐去。选一个关卡，逐日推进，只按开盘价或收盘价成交；结束后揭晓真实走势、事件影响和得分。</p>
          </section>
          ${active.length
            ? html`<h2 class="replay-group">进行中</h2><div class="replay-list">${active.map((s) => U().sessionRowHtml(s))}</div>`
            : ""}
          <h2 class="replay-group">关卡</h2>
          <div class="replay-list" data-role="levels">${levels.map((lv) => U().levelCardHtml(lv))}</div>
          ${settled.length
            ? html`<h2 class="replay-group">已结算</h2><div class="replay-list">${settled.map((s) => U().sessionRowHtml(s))}</div>`
            : ""}`
      );
    }

    function unavailable() {
      SS.mount(body(), SS.soonCardHtml({ title: "真实复盘", desc: "回到真实历史，股票名已隐去" }));
    }

    /** 关卡按游标读完（next_cursor 为 null 才停） */
    async function allLevels() {
      const items = [];
      let cursor = null;
      do {
        const page = await store().listReplayLevels({ cursor, limit: 100 });
        items.push(...page.items);
        cursor = page.next_cursor || null;
      } while (cursor);
      return items;
    }

    async function load() {
      try {
        const [items, ses] = await Promise.all([allLevels(), store().listReplaySessions()]);
        levels = items;
        draw(ses.items);
        if (q.level) {
          const hit = levels.find((x) => x.slug === q.level);
          if (hit) openLevel(hit);
        }
      } catch (err) {
        if (!alive) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") return unavailable();
        SS.mount(body(), html`<div class="empty"><div class="empty__title">${store().errorText(err && err.code)}</div><button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button></div>`);
        SS.$('[data-role="retry"]', body()).addEventListener("click", () => {
          SS.mount(body(), html`<div class="skeleton" style="height:120px;border-radius:16px;margin-top:8px"></div>`);
          load();
        });
      }
    }

    const onClick = (e) => {
      const b = e.target.closest("[data-slug]");
      if (!b) return;
      const hit = levels.find((x) => x.slug === b.dataset.slug);
      if (hit) openLevel(hit);
    };
    view.addEventListener("click", onClick);
    load();
    return () => {
      alive = false;
      view.removeEventListener("click", onClick);
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.replayList = { tab: null, render };
})();
