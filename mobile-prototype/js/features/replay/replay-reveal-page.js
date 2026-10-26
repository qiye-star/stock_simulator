/**
 * 复盘揭示（#/replay/:id/reveal，SS.pages.replayReveal，二级页）：结算后才能看（REPLAY_REVEAL_LOCKED 则回会话页）。
 * 内容：积分与收益（相对基准的超额）、股票真身（真实名称与代码，完整 K 线，游戏期加底色）、事件影响（相对基准的超额，红绿）、
 * 题目结果（真实档位 / 排序、得分）、资产曲线、买入持有与基准对比、作者讲解。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.replayModel;
  const store = () => SS.store;

  /** 完整 K 线（揭示期全部可见）：游戏期（0..play_days-1）加底色 */
  function fullKlineHtml(candles, playDays) {
    if (!candles || !candles.length) return html`<p class="t3 sm">暂无行情</p>`;
    const c = SS.chart.kline(candles, 343, 170, 36);
    const idx = candles.map((x, i) => (x.trading_day >= 0 && x.trading_day < playDays ? i : -1)).filter((i) => i >= 0);
    const l = (idx[0] / candles.length) * 100;
    const w = ((idx[idx.length - 1] - idx[0] + 1) / candles.length) * 100;
    return html`<div class="chart replay-kline replay-kline--full" role="img" aria-label="完整 K 线，底色为游戏期">
      <div class="chart__plot"><span class="replay-kline__play" style="left:${l}%;width:${w}%" aria-hidden="true"></span>${SS.raw(c.svg)}</div>
      <div class="chart__vol">${SS.raw(c.volSvg)}</div>
      <p class="t3 xs replay-kline__legend">底色 = 游戏期（${candles[0].date} 起）</p>
    </div>`;
  }

  function render(view, params) {
    const saveId = params.id;
    let alive = true;
    let rev = null;
    let pick = 0;
    SS.mount(
      view,
      html`<header class="topbar"><a class="icon-btn" href="#/replay" aria-label="返回">${SS.icon("back")}</a><h1 class="topbar__title">复盘揭晓</h1></header>
        <div class="replay-page reveal-page" data-role="body"><div class="skeleton" style="height:160px;border-radius:18px;margin-top:8px"></div></div>`
    );
    const body = () => SS.$('[data-role="body"]', view);

    function draw() {
      if (!alive || !rev) return;
      const s = rev.session;
      const st = s.settled;
      const stock = rev.stocks[pick] || rev.stocks[0];
      const nameOf = M().revealNameOf(rev.stocks);
      const eq = (rev.equity || []).map((p) => p.equity_cents);
      const area = eq.length > 1 ? SS.chart.area(eq, 343, 120) : null;
      SS.mount(
        body(),
        html`<section class="card reveal-hero">
            <span class="t2 xs">${s.level.title} · ${s.masked ? "匿名" : "实名"}</span>
            <span class="reveal-hero__points num">${st.points_total > 0 ? `+${st.points_total}` : st.points_total} <span class="t2 sm">积分</span></span>
            <div class="reveal-stats num">
              <div><span class="t2 xs">最终资产（元）</span><b>${SS.fmt.yuan(st.final_equity_cents)}</b></div>
              <div><span class="t2 xs">收益</span><b class="${SS.fmt.trend(st.return_bp)}">${SS.fmt.pctBp(st.return_bp)}</b></div>
              <div><span class="t2 xs">${rev.benchmark.name}</span><b class="${SS.fmt.trend(st.benchmark_return_bp)}">${SS.fmt.pctBp(st.benchmark_return_bp)}</b></div>
              <div><span class="t2 xs">超额收益</span><b class="${SS.fmt.trend(st.excess_bp)}">${SS.fmt.pctBp(st.excess_bp)}</b></div>
            </div>
            <p class="t2 xs">买入持有关卡全部股票 ${SS.fmt.pctBp(rev.hold_all_return_bp)} · 成交 ${rev.trades_count} 笔（积分与资金独立，交易盈亏不发积分）</p>
          </section>

          <h2 class="replay-group">股票真身</h2>
          <div class="replay-stocks" role="group" aria-label="切换股票">
            ${rev.stocks.map((x, i) => html`<button type="button" class="replay-stock-chip ${i === pick ? "is-on" : ""}" data-pick="${i}" aria-pressed="${i === pick}">${x.real_name}</button>`)}
          </div>
          <section class="card replay-stock reveal-stock">
            <div class="replay-stock__head">
              <div class="replay-stock__name">
                <span class="replay-stock__title reveal-name">${stock.real_name}</span>
                <span class="t2 xs num">${stock.real_code}</span>
                <span class="t2 xs">行业：${stock.industry}${s.masked ? ` · 游戏中的代号 ${stock.code}` : ""}</span>
              </div>
            </div>
            ${fullKlineHtml(stock.candles, s.play_days)}
          </section>

          <h2 class="replay-group">事件影响</h2>
          <section class="card reveal-events">
            ${rev.events.length
              ? html`<ul class="replay-feed__list">
                  ${rev.events.map(
                    (e) => html`<li class="reveal-event">
                      <span class="t3 xs num">${e.date_label}</span>
                      <span class="replay-feed__title">${e.major ? html`<span class="tag tag--accent">重大</span> ` : ""}${e.title}</span>
                      ${e.impact
                        ? html`<span class="xs num reveal-event__impact"><span class="${SS.fmt.trend(e.impact.ar_1d_bp)}">次日 ${SS.fmt.pctBp(e.impact.ar_1d_bp)}</span> <span class="${SS.fmt.trend(e.impact.ar_5d_bp)}">5 日 ${SS.fmt.pctBp(e.impact.ar_5d_bp)}</span></span>`
                        : ""}
                    </li>`
                  )}
                </ul>`
              : html`<p class="t2 sm">本关没有事件</p>`}
            <p class="t3 xs">影响为相对基准的超额收益。</p>
          </section>

          <h2 class="replay-group">预测题</h2>
          <section class="card reveal-questions">
            ${rev.questions.length
              ? rev.questions.map((q) => {
                  const r = q.result;
                  const mine = q.my_answer
                    ? q.kind === "rank"
                      ? `你的排序：${q.my_answer.order.map(nameOf).join(" › ")}`
                      : (() => {
                          const top = q.my_answer.probs.indexOf(Math.max(...q.my_answer.probs));
                          return `你选的档位：${q.buckets[top].label}（把握 ${q.my_answer.probs[top]}%）`;
                        })()
                    : "你没有作答";
                  const truth = r
                    ? q.kind === "rank"
                      ? `真实前三：${r.true_top.map(nameOf).join(" › ")}`
                      : `真实档位：${q.buckets[r.outcome_bucket].label}（${SS.fmt.pctBp(r.return_bp)}）`
                    : "";
                  return html`<div class="reveal-q">
                    <p class="reveal-q__prompt">${q.prompt}</p>
                    <p class="t2 xs">${mine}</p>
                    ${r ? html`<p class="t2 xs">${truth}</p><p class="reveal-q__score num"><span class="t2 xs">得分</span> ${r.score} · <span class="accent-text">+${r.points} 积分</span></p>` : html`<p class="t3 xs">${q.status === "skipped" ? "未答，记 0 分" : "未结算"}</p>`}
                  </div>`;
                })
              : html`<p class="t2 sm">本关没有预测题</p>`}
          </section>

          ${area
            ? html`<h2 class="replay-group">资产曲线</h2>
                <section class="card reveal-equity">
                  ${SS.raw(area.svg)}
                  <div class="reveal-equity__axis t3 xs num"><span>初始 ${SS.fmt.yuanCompact(eq[0])}</span><span>终值 ${SS.fmt.yuanCompact(eq[eq.length - 1])}</span></div>
                </section>`
            : ""}

          <h2 class="replay-group">作者讲解</h2>
          <section class="card"><p class="reveal-commentary">${rev.commentary}</p></section>

          <div class="reveal-actions">
            <button type="button" class="btn btn-primary btn-block btn-lg" data-role="again">再玩一次</button>
            <a class="btn btn-block" href="#/replay">回到关卡</a>
          </div>`
      );
    }

    async function load() {
      try {
        rev = await store().getReplayReveal(saveId);
        draw();
      } catch (err) {
        if (!alive) return;
        if (err && err.code === "REPLAY_REVEAL_LOCKED") {
          SS.toast(store().errorText(err.code), { icon: null, duration: 2000 });
          return SS.router.replace(`/replay/${saveId}`);
        }
        if (err && err.code === "FEATURE_UNAVAILABLE") return SS.mount(body(), SS.soonCardHtml({ title: "真实复盘", desc: "回到真实历史，股票名已隐去" }));
        SS.mount(body(), html`<div class="empty"><div class="empty__title">${store().errorText(err && err.code)}</div><a class="btn btn-sm" href="#/replay">回到关卡</a></div>`);
      }
    }

    const onClick = async (e) => {
      const p = e.target.closest("[data-pick]");
      if (p) {
        pick = Number(p.dataset.pick);
        return draw();
      }
      if (e.target.closest('[data-role="again"]')) {
        const btn = e.target.closest('[data-role="again"]');
        btn.disabled = true;
        try {
          const created = await store().createReplaySession(rev.session.level.slug, { masked: rev.session.masked });
          SS.router.navigate(`/replay/${created.save_id}`);
        } catch (err) {
          btn.disabled = false;
          store().notifyError(err);
        }
      }
    };
    view.addEventListener("click", onClick);
    load();
    return () => {
      alive = false;
      view.removeEventListener("click", onClick);
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.replayReveal = { tab: null, render };
})();
