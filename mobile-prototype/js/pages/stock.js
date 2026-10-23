/**
 * 个股详情（#/stock/:code）—— 对应 GET /saves/{id}/market/{code} 与 /market/{code}/intraday（分时历史，WS 追加增量）
 *   - 顶栏：返回 / 名称代码 / 自选星标；
 *   - 大号现价 + 涨跌额/幅（红涨绿跌），关键指标网格；
 *   - 分时 / 日K 切换；按住图表拖动显示十字线读数；
 *   - 五档盘口、我的持仓摘要；
 *   - 底部吸附操作栏：卖出 / 买入 → 下单抽屉。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html, raw } = SS;
  let chartMode = "intraday";

  function render(view, { code }) {
    const store = SS.store;
    const fmt = SS.fmt;
    const s = store.quote(code);
    if (!s) {
      const notFound = () => {
        SS.mount(
          view,
          html`<header class="topbar topbar--sub"><button class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button></header>
            <div class="empty"><div class="empty__title">${SS.blurText("没有找到这只股票")}</div><p class="t3 sm">代码 ${code}</p></div>`
        );
        SS.$('[data-role="back"]', view).addEventListener("click", SS.router.back);
      };
      // 缓存里没有（直接打开链接、行情分页尚未翻到）：按代码向后端取一次，取到后重新渲染
      let gone = false;
      let inner = null;
      Promise.resolve(store.loadQuote(code))
        .then((q) => {
          if (gone) return;
          if (q) inner = render(view, { code });
          else notFound();
        })
        .catch(() => !gone && notFound());
      return () => {
        gone = true;
        if (inner) inner();
      };
    }

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <div class="topbar__center">
            <div class="topbar__name">${s.name}</div>
            <div class="xs t3 num">${s.code} · ${s.industry}</div>
          </div>
          <button class="icon-btn star ${s.watchlisted ? "is-on" : ""}" data-role="star" aria-pressed="${s.watchlisted}" aria-label="自选">${SS.icon("star")}</button>
        </header>

        <section class="quote-hero">
          <div class="quote-hero__price num" data-role="price"></div>
          <div class="quote-hero__chg num" data-role="chg"></div>
          <div class="quote-hero__clock" data-role="clock"></div>
        </section>

        <dl class="stat-grid" data-role="stats"></dl>

        <section class="card chart-card">
          <div class="chart-card__head">
            <div class="seg seg--inline" data-role="mode">
              <span class="seg__thumb" aria-hidden="true"></span>
              <button type="button" data-value="intraday" class="${chartMode === "intraday" ? "is-active" : ""}">分时</button>
              <button type="button" data-value="kline" class="${chartMode === "kline" ? "is-active" : ""}">日K</button>
            </div>
            <div class="chart-readout xs num" data-role="readout"></div>
          </div>
          <div class="chart" data-role="chart"></div>
        </section>

        <section class="card">
          <h3 class="card__title">五档盘口</h3>
          <div class="book" data-role="book"></div>
        </section>

        <div data-role="mine"></div>

        <div class="action-bar">
          <button type="button" class="btn btn-lg" data-role="sell">卖出</button>
          <button type="button" class="btn btn-primary btn-lg" data-role="buy">买入</button>
        </div>`
    );

    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    $("back").addEventListener("click", SS.router.back);
    $("star").addEventListener("click", () => {
      const on = store.toggleWatch(code);
      $("star").classList.toggle("is-on", on);
      $("star").setAttribute("aria-pressed", on);
      SS.haptic();
      SS.toast(on ? "已加入自选" : "已移出自选", { icon: on ? "star" : null, duration: 1400 });
    });
    $("buy").addEventListener("click", () => SS.orderSheet.open({ code, side: "buy" }));
    $("sell").addEventListener("click", () => SS.orderSheet.open({ code, side: "sell" }));
    SS.segmented($("mode"), (v) => {
      chartMode = v;
      paintChart();
    });

    function paintHead() {
      const tr = fmt.trend(s.change_bp);
      $("price").className = `quote-hero__price num ${tr}`;
      $("price").textContent = fmt.price(s.price_cents);
      $("chg").className = `quote-hero__chg num ${tr}`;
      $("chg").textContent = `${fmt.yuan(s.price_cents - s.prev_close_cents, { sign: true })}  ${fmt.pctBp(s.change_bp)}`;
      SS.mount($("clock"), SS.clockChip(store.state.clock));
      const vs = (v) => fmt.trend(v - s.prev_close_cents);
      const cell = (k, v, cls = "") => html`<div><dt>${k}</dt><dd class="num ${cls}">${v}</dd></div>`;
      SS.mount(
        $("stats"),
        html`${cell("今开", fmt.price(s.open_cents), vs(s.open_cents))}
        ${cell("最高", fmt.price(s.high_cents), vs(s.high_cents))}
        ${cell("最低", fmt.price(s.low_cents), vs(s.low_cents))}
        ${cell("昨收", fmt.price(s.prev_close_cents))}
        ${cell("涨停", fmt.price(s.limit_up_cents), "up")}
        ${cell("跌停", fmt.price(s.limit_down_cents), "down")}
        ${cell("成交量", fmt.volume(s.volume))}
        ${cell("振幅", fmt.pctBp(Math.round(((s.high_cents - s.low_cents) / s.prev_close_cents) * 10000), { sign: false }))}
        ${cell("行业", s.industry)}`
      );
    }

    function readoutDefault() {
      if (chartMode === "intraday")
        SS.mount($("readout"), html`<span class="legend legend--line ${fmt.trend(s.change_bp)}">价格</span><span class="legend legend--avg">均价</span>`);
      else SS.mount($("readout"), html`<span class="legend legend--avg">MA5</span><span class="t3">近 ${Math.min(40, s._candles.length + 1)} 日</span>`);
    }

    function paintChart() {
      const host = $("chart");
      const fresh = host.cloneNode(false); // 丢弃旧的十字线监听
      host.replaceWith(fresh);
      if (chartMode === "intraday") {
        const c = SS.chart.intraday(s._series, s.prev_close_cents);
        const pct = (v) => fmt.pctBp(Math.round(((v - s.prev_close_cents) / s.prev_close_cents) * 10000));
        SS.mount(
          fresh,
          html`<div class="chart__plot">${raw(c.svg)}
              <span class="axis axis--tl num up">${fmt.price(c.hi)}</span>
              <span class="axis axis--bl num down">${fmt.price(c.lo)}</span>
              <span class="axis axis--tr num up">${pct(c.hi)}</span>
              <span class="axis axis--br num down">${pct(c.lo)}</span>
            </div>
            <div class="chart__time xs t3 num"><span>09:30</span><span>11:30 / 13:00</span><span>15:00</span></div>`
        );
        const plot = SS.$(".chart__plot", fresh);
        SS.chart.crosshair(plot, {
          count: s._series.length,
          total: c.total,
          onMove(i) {
            if (i == null) return readoutDefault();
            const v = s._series[i];
            const m = i <= 120 ? 570 + i : 780 + (i - 121);
            SS.mount(
              SS.$('[data-role="readout"]', view),
              html`<span class="t2">${fmt.clock(m)}</span><span class="${fmt.trend(v - s.prev_close_cents)}">${fmt.price(v)} ${pct(v)}</span>`
            );
          },
        });
      } else {
        // 历史日 K + 今日实时 K
        const today = {
          trading_day: store.state.clock.trading_day,
          date: "今日",
          open_cents: s.open_cents,
          high_cents: s.high_cents,
          low_cents: s.low_cents,
          close_cents: s.price_cents,
          volume: s.volume,
        };
        const candles = s._candles.slice(-39).concat(today);
        const c = SS.chart.kline(candles);
        SS.mount(
          fresh,
          html`<div class="chart__plot">${raw(c.svg)}
              <span class="axis axis--tl num t3">${fmt.price(c.hi)}</span>
              <span class="axis axis--bl num t3">${fmt.price(c.lo)}</span>
            </div>
            <div class="chart__vol">${raw(c.volSvg)}</div>
            <div class="chart__time xs t3 num"><span>${candles[0].date.slice(5)}</span><span>今日</span></div>`
        );
        SS.chart.crosshair(SS.$(".chart__plot", fresh), {
          count: candles.length,
          total: candles.length,
          slotMode: true,
          onMove(i) {
            if (i == null) return readoutDefault();
            const k = candles[i];
            const ch = k.close_cents - (i > 0 ? candles[i - 1].close_cents : k.open_cents);
            SS.mount(
              SS.$('[data-role="readout"]', view),
              html`<span class="t2">${k.date.length > 5 ? k.date.slice(5) : k.date}</span><span class="t3">开</span><span>${fmt.price(k.open_cents)}</span><span class="t3">收</span><span class="${fmt.trend(ch)}">${fmt.price(k.close_cents)}</span>`
            );
          },
        });
      }
      readoutDefault();
    }

    function paintBook() {
      const b = store.orderBook(code);
      const maxV = Math.max(1, ...b.asks.concat(b.bids).map((l) => l.volume));
      const lvl = (l, label, side) =>
        html`<div class="book__row">
          <span class="t3 xs">${label}</span>
          <span class="num ${fmt.trend(l.price_cents - s.prev_close_cents)}">${fmt.price(l.price_cents)}</span>
          <span class="num t2 book__vol"><i class="book__bar book__bar--${side}" style="width:${((l.volume / maxV) * 100).toFixed(1)}%"></i>${fmt.qty(l.volume / 100)}</span>
        </div>`;
      SS.mount(
        $("book"),
        html`<div class="book__side">${b.asks
          .slice()
          .reverse()
          .map((l, i) => lvl(l, `卖${5 - i}`, "ask"))}</div>
          <div class="book__side">${b.bids.map((l, i) => lvl(l, `买${i + 1}`, "bid"))}</div>`
      );
    }

    function paintMine() {
      const h = store.portfolio().holdings.find((x) => x.code === code);
      if (!h) {
        SS.mount($("mine"), "");
        return;
      }
      const tr = fmt.trend(h.pnl_cents);
      SS.mount(
        $("mine"),
        html`<section class="card mine">
          <h3 class="card__title">我的持仓</h3>
          <dl class="stat-grid stat-grid--3">
            <div><dt>持仓 / 可卖</dt><dd class="num">${fmt.qty(h.quantity)} / ${fmt.qty(h.sellable_quantity)}</dd></div>
            <div><dt>成本价</dt><dd class="num">${fmt.price(h.avg_price_cents)}</dd></div>
            <div><dt>浮动盈亏</dt><dd class="num ${tr}">${fmt.yuanCompact(h.pnl_cents, { sign: true })}<small> ${fmt.pctBp(h.pnl_bp)}</small></dd></div>
          </dl>
        </section>`
      );
    }

    paintHead();
    paintChart();
    paintBook();
    paintMine();

    // 真实模式：日 K 与五档需单独请求（假数据版为空操作）。五档随行情变化节流刷新。
    let alive = true;
    let warned = false;
    const loadDetail = (repaintChart) =>
      store
        .loadDetail(code)
        .then(() => {
          if (!alive) return;
          if (repaintChart && !SS.$(".crosshair.on", view)) paintChart();
          paintBook();
        })
        .catch((e) => {
          if (alive && !warned) {
            warned = true;
            store.notifyError(e);
          }
        });
    loadDetail(true);

    const offs = [
      store.on("tick", ({ changed }) => {
        paintHead();
        if (changed.some((c) => c.code === code)) {
          // 十字线拖动中不重绘图表
          if (!SS.$(".crosshair.on", view)) paintChart();
          paintBook();
          paintMine();
          loadDetail(false);
        }
      }),
      store.on("order", paintMine),
      // 分时历史（重新）加载完成：重绘分时图
      store.on("series", (codes) => {
        if (codes.includes(code) && !SS.$(".crosshair.on", view)) paintChart();
      }),
    ];
    return () => {
      alive = false;
      offs.forEach((f) => f());
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.stock = { tab: null, render };
})();
