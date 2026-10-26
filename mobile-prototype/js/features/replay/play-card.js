/**
 * 玩法页的真实复盘分区（SS.replayCard.mount，slot play:replay，order 30）：
 *   标题在卡外（同画板）：进行中的会话（继续 · 第 N / M 天）、精选关卡卡（前两关，链接到 #/replay?level=slug 直接打开抽屉）、“全部关卡 ›”。
 * 后端没有复盘接口（FEATURE_UNAVAILABLE）时显示“即将开放”占位。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const U = () => SS.replayUi;
  const store = () => SS.store;
  const DESC = "回到真实历史，股票名已隐去";

  function mount(host) {
    let alive = true;
    const draw = (levels, sessions) => {
      if (!alive) return;
      const active = sessions.filter((s) => s.status === "active");
      const cont = active[0];
      SS.mount(
        host,
        html`<section class="replay-block" data-role="replay-card">
          <div class="pm-section__head">
            <h2 class="pm-section__title">真实复盘</h2>
            <a class="ch-link" href="#/replay">全部关卡 ›</a>
          </div>
          <div class="card replay-card">
          <p class="t2 sm replay-card__desc">${DESC}</p>
          ${cont
            ? html`<a class="replay-continue" href="${SS.href(`/replay/${cont.save_id}`)}">
                <span class="tag tag--accent">继续</span>
                <span class="replay-continue__text">${cont.level.title} · 第 ${cont.day_idx + 1} / ${cont.play_days} 天</span>
                <span class="t2" aria-hidden="true">›</span>
              </a>`
            : ""}
          <div class="replay-list">
            ${levels.slice(0, 2).map((lv) => U().levelCardHtml(lv, { href: SS.href(`/replay?level=${encodeURIComponent(lv.slug)}`) }))}
          </div>
          </div>
        </section>`
      );
    };
    const unavailable = () => {
      if (alive) SS.mount(host, SS.soonCardHtml({ title: "真实复盘", desc: DESC }));
    };
    SS.mount(host, html`<section class="replay-block"><h2 class="pm-section__title">真实复盘</h2><div class="card replay-card"><div class="skeleton" style="height:20px;width:40%"></div><div class="skeleton" style="height:44px;margin-top:14px"></div></div></section>`);
    Promise.all([store().listReplayLevels({ limit: 2 }), store().listReplaySessions()])
      .then(([lv, ses]) => draw(lv.items, ses.items))
      .catch((err) => {
        if (err && err.code === "FEATURE_UNAVAILABLE") return unavailable();
        if (alive) SS.mount(host, html`<section class="replay-block"><h2 class="pm-section__title">真实复盘</h2><div class="card replay-card"><p class="t2 sm">${store().errorText(err && err.code)}</p></div></section>`);
      });
    return () => {
      alive = false;
    };
  }

  SS.replayCard = { mount };
})();
