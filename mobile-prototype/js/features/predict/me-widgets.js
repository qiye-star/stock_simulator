/**
 * “我的”页的预测挂件（对照 Me 画板），由 index.js 注册到挂载点：
 *   me.badges  称号 tag（佩戴的用强调色；另显示一个最近解锁）；点击打开称号墙（佩戴 / 取下）
 *   me.cards   积分卡（10）→ #/predictions；校准卡（20）；情报卡（30，仅事件模式存档）
 *   me.rows    “预测记录 ›”（10）；“预测卡”模式 seg（20，仅事件模式存档；挑战中固定时禁用）
 * 降级：FEATURE_UNAVAILABLE → 对应区域显示 SS.soonCard；不影响其它挂件。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = SS.predictModel;
  const store = () => SS.store;
  const soon = (host, title) => SS.mount(host, SS.soonCardHtml({ title, desc: "" }));
  const unavailable = (err) => !!err && err.code === "FEATURE_UNAVAILABLE";

  // ---------- 称号 ----------
  function titlesOf(list) {
    return list.map((t) => ({ ...SS.predictTitles.byId(t.id), unlocked: !!t.unlocked_at, at: t.unlocked_at })).filter((x) => x.name);
  }

  function mountBadges(host) {
    let seq = 0;
    const draw = (data) => {
      const equipped = data.equipped;
      const list = titlesOf(data.items);
      const eq = list.find((t) => t.id === equipped);
      const recent = list.filter((t) => t.unlocked && t.id !== equipped).sort((a, b) => (a.at < b.at ? 1 : -1))[0];
      SS.mount(
        host,
        html`<button type="button" class="pred-badges" data-role="titles" aria-label="称号">
          ${eq ? html`<span class="tag tag--accent">${eq.name}</span>` : html`<span class="tag">未佩戴称号</span>`}
          ${recent ? html`<span class="tag">${recent.name}</span>` : ""}
          <span class="t3 xs">称号 ›</span>
        </button>`
      );
      SS.$('[data-role="titles"]', host).addEventListener("click", openWall);
    };
    const my = ++seq;
    store()
      .loadTitles()
      .then((t) => my === seq && draw({ items: t.items, equipped: t.equipped }))
      .catch((err) => {
        if (!unavailable(err)) return;
        SS.mount(host, "");
        host.hidden = true;
      });
    return () => {
      seq++;
    };
  }

  function openWall() {
    SS.sheet.open({
      title: "称号",
      render(body) {
        const paint = (data) => {
          const list = titlesOf(data.items);
          SS.mount(
            body,
            html`<p class="t2 xs">已解锁的称号可以佩戴，显示在你的排行中。</p>
              <div class="title-wall">
                ${list.map(
                  (t) => html`<div class="title-wall__row ${t.unlocked ? "" : "is-locked"}">
                    <div class="title-wall__main">
                      <span class="title-wall__name">${t.name}${t.unlocked ? "" : html` ${SS.icon("lock", "title-wall__lock")}`}</span>
                      <span class="t2 xs">${t.desc}</span>
                    </div>
                    <span class="tag ${t.level === "gold" || t.level === "legend" ? "tag--accent" : ""}">${M.LEVEL_TEXT[t.level] || t.level}</span>
                    ${t.unlocked
                      ? html`<button type="button" class="btn btn-sm ${data.equipped === t.id ? "" : "btn-ghost"}" data-equip="${data.equipped === t.id ? "" : t.id}">${data.equipped === t.id ? "取下" : "佩戴"}</button>`
                      : ""}
                  </div>`
                )}
              </div>`
          );
          SS.$$("[data-equip]", body).forEach((b) =>
            b.addEventListener("click", async () => {
              try {
                await store().equipTitle(b.dataset.equip || null);
                const t = await store().loadTitles();
                paint({ items: t.items, equipped: t.equipped });
              } catch (err) {
                store().notifyError(err);
              }
            })
          );
        };
        store()
          .loadTitles()
          .then((t) => paint({ items: t.items, equipped: t.equipped }))
          .catch((err) => store().notifyError(err));
      },
    });
  }

  // ---------- 积分卡 ----------
  function mountPoints(host) {
    SS.mount(host, html`<div class="skeleton" style="height:76px;border-radius:var(--r-lg)"></div>`);
    const paint = (p, stats) => {
      SS.mount(
        host,
        html`<a class="card points-card" href="#/predictions">
          <span class="points-card__main">
            <span class="t2 sm">预测积分</span>
            <span class="num points-card__bal">${SS.fmt.qty(p.balance)}</span>
            <span class="t2 xs num">今日已得 ${SS.fmt.qty(p.today_prediction_points)} / 上限 ${SS.fmt.qty(p.daily_cap)}</span>
          </span>
          <span class="points-card__side">
            <span class="t2 sm">已答</span>
            <span class="num points-card__answered">${stats ? stats.cards_answered : 0} 张</span>
          </span>
          ${SS.icon("chevron", "points-card__chev")}
        </a>`
      );
    };
    let seq = 0;
    const my = ++seq;
    Promise.all([store().loadPoints(), store().loadPointStats().catch(() => null)])
      .then(([p, stats]) => {
        if (my === seq) paint(p, stats);
      })
      .catch((err) => {
        if (my === seq) soon(host, "预测积分");
      });
    return () => {
      seq++;
    };
  }

  // ---------- 校准卡 ----------
  function mountCalib(host) {
    SS.mount(host, html`<div class="skeleton" style="height:180px;border-radius:var(--r-lg)"></div>`);
    store()
      .loadPointStats()
      .then((s) => {
        const g = M.calibrationPoints(s.calibration || [], 320, 150);
        const body = g.ready
          ? html`${SS.predictChart.calibration(s.calibration, 320, 150)}<p class="t3 xs">平均偏差 ${M.errorText(s.calibration_error_bp)}</p>`
          : html`<p class="t2 sm calib-card__empty">作答更多卡片后会出现校准曲线</p>`;
        SS.mount(
          host,
          html`<section class="card calib-card" data-role="calib">
            <div class="calib-card__head"><span class="card__title">校准曲线</span><span class="t2 xs">越贴近虚线，说明你的“把握”越准</span></div>
            ${body}
          </section>`
        );
        if (/focus=calib/.test(location.hash)) {
          const el = SS.$('[data-role="calib"]', host);
          if (el) requestAnimationFrame(() => el.scrollIntoView({ block: "center" }));
        }
      })
      .catch((err) => soon(host, "校准曲线"));
  }

  // ---------- 情报卡 ----------
  function mountIntel(host, ctx) {
    if (!store().predictEnabled()) return;
    const draw = (intel) => {
      const prices = intel.prices;
      SS.mount(
        host,
        html`<section class="card intel-card">
          <span class="card__title">情报卡</span>
          <a class="intel-row" href="#/chain" data-intel-go="chain">
            <span class="intel-row__text"><span>揭示一条边的强度</span><span class="t2 xs">看清某两个行业之间传导是强是弱</span></span>
            <span class="btn-outline-accent num">${prices.edge_l1} 分</span>
          </a>
          <a class="intel-row" href="#/news?filter=rumor" data-intel-go="rumor">
            <span class="intel-row__text"><span>传闻真假提示</span><span class="t2 xs">告诉你这条传闻更可能真还是假</span></span>
            <span class="btn-outline-accent num">${prices.rumor_hint} 分</span>
          </a>
          <p class="t3 xs num">今日已用 ${intel.used_today}/${intel.daily_limit}</p>
        </section>`
      );
    };
    store()
      .loadIntel()
      .then(draw)
      .catch((err) => {
        SS.mount(host, "");
        host.hidden = true;
      });
    host.addEventListener("click", (e) => {
      const a = e.target.closest("[data-intel-go]");
      if (a && a.dataset.intelGo === "chain") SS.toast("在产业链里点带锁的关系", { icon: null, duration: 1800 });
    });
    return store().on("intel", () => store().loadIntel().then(draw).catch(() => {}));
  }

  // ---------- 行：预测记录 / 预测卡模式 ----------
  function mountRecords(host) {
    const open = (cards) => (cards || []).filter((c) => c.status === "open").length;
    const draw = () => {
      const n = open(store().state.predict.openCards);
      SS.mount(
        host,
        html`<a class="set-row" href="#/predictions">
          <span class="set-row__icon">${SS.icon("games")}</span><span class="set-row__label">预测记录</span>
          ${n ? html`<span class="tag tag--accent">${n} 待答</span>` : ""}
          ${SS.icon("chevron", "set-row__chev")}
        </a>`
      );
    };
    if (!store().predictEnabled()) {
      host.hidden = true;
      return () => {};
    }
    draw();
    store()
      .listPredictions({ status: "open", limit: 20 })
      .then((r) => {
        store().state.predict.openCards = r.items;
        draw();
      })
      .catch(() => {});
    return store().on("predict:update", draw);
  }

  function mountMode(host) {
    if (!store().predictEnabled()) {
      host.hidden = true;
      return () => {};
    }
    SS.mount(
      host,
      html`<div class="set-row">
        <span class="set-row__icon">${SS.icon("clock")}</span>
        <span class="set-row__label">预测卡</span>
        <div class="seg seg--mini" data-role="pred-mode"><span class="seg__thumb" aria-hidden="true"></span>
          <button type="button" data-value="pause">暂停作答</button><button type="button" data-value="off">关闭</button>
        </div>
      </div>`
    );
    const seg = SS.segmented(SS.$('[data-role="pred-mode"]', host), async (v) => {
      try {
        const out = await store().setPredictionMode(v);
        SS.toast(out.mode === "off" ? "已关闭预测卡" : "预测卡：暂停作答", { icon: null, duration: 1400 });
      } catch (err) {
        store().notifyError(err);
        seg.set(prev);
      }
    });
    let prev = "pause";
    store()
      .loadPredictionSettings()
      .then((s) => {
        prev = s.mode;
        seg.set(s.mode);
        if (s.forced) {
          SS.$$("button", host).forEach((b) => (b.disabled = true));
          const note = html`<span class="t3 xs">挑战中固定</span>`;
          host.querySelector(".set-row").insertAdjacentHTML("beforeend", String(note));
        }
      })
      .catch((err) => {
        host.hidden = true;
      });
    return () => {};
  }

  SS.predictWidgets = { mountBadges, mountPoints, mountCalib, mountIntel, mountRecords, mountMode, openWall };
})();
