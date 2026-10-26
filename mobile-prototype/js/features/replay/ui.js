/**
 * 真实复盘的共用片段（SS.replayUi）：阶段条、股票卡、K 线（含“未来”分隔）、消息流、题目行、关卡卡、会话行。
 * 只产出 SafeHtml；用户可见文本一律经 SS.html 转义；行情数据颜色只用 .up / .down / .flat。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const M = () => SS.replayModel;
  const KIND_TEXT = { announcement: "公告", news: "新闻", policy: "政策" };
  const STATUS_TEXT = { open: "可作答", answered: "已答 · 可修改", closed: "已截止", skipped: "未答 · 0 分", scored: "已结算" };

  /** 阶段条：已过 .is-done（白字）、当前 .is-on（强调色描边） */
  function phaseStripHtml(phase) {
    const cur = M().phaseIdx(phase);
    return html`<div class="replay-phases" role="list" aria-label="当前阶段">
      ${M().PHASES.map((p, i) => html`<span class="replay-phase ${i < cur ? "is-done" : i === cur ? "is-on" : ""}" role="listitem" aria-current="${i === cur ? "step" : ""}">${M().PHASE_LABEL[p]}</span>`)}
    </div>`;
  }

  /** 股票切换胶囊（多只股票时） */
  function stockChipsHtml(list, activeCode) {
    if (list.length <= 1) return "";
    return html`<div class="replay-stocks" role="group" aria-label="切换股票">
      ${list.map((s) => html`<button type="button" class="replay-stock-chip ${s.code === activeCode ? "is-on" : ""}" data-stock="${s.code}" aria-pressed="${s.code === activeCode}">${s.name}</button>`)}
    </div>`;
  }

  /** K 线（SVG 由 SS.chart.kline 生成，内部数据）；右侧虚线与“未来”标签表示之后的日子 */
  function klineHtml(candles, { playRange = null } = {}) {
    if (!candles || !candles.length) return html`<p class="t3 sm replay-kline-empty">暂无行情</p>`;
    const view = candles.slice(-10);
    const c = SS.chart.kline(view, 343, 150, 36);
    const shade = playRange
      ? (() => {
          const idx = view.map((x, i) => (x.trading_day >= playRange[0] && x.trading_day <= playRange[1] ? i : -1)).filter((i) => i >= 0);
          if (!idx.length) return "";
          const l = (idx[0] / view.length) * 100;
          const w = ((idx[idx.length - 1] - idx[0] + 1) / view.length) * 100;
          return html`<span class="replay-kline__play" style="left:${l}%;width:${w}%" aria-hidden="true"></span>`;
        })()
      : "";
    return html`<div class="chart replay-kline" role="img" aria-label="近 ${view.length} 日 K 线，右侧虚线之后为未来">
      <div class="chart__plot">${shade}${SS.raw(c.svg)}<span class="replay-kline__edge" aria-hidden="true"></span><span class="replay-kline__future">未来</span></div>
      <div class="chart__vol">${SS.raw(c.volSvg)}</div>
    </div>`;
  }

  /** 股票卡头部：名称（匿名时带“名称已隐去”）、行业、现价与阶段涨跌 */
  function stockHeadHtml(quote, masked, phase) {
    const trend = SS.fmt.trend(quote.change_bp);
    const label = phase === "pre_open" ? "前收" : phase === "open" ? "开盘" : "收盘";
    const sub = phase === "pre_open" ? SS.fmt.price(quote.prev_close_cents) : SS.fmt.pctBp(quote.change_bp);
    // 标签与代码同一行（不拉伸），行业单独一行
    return html`<div class="replay-stock__head">
      <div class="replay-stock__name">
        <span class="replay-stock__title">${quote.name}
          ${masked ? html`<span class="tag">名称已隐去</span>` : ""}
          ${quote.suspended ? html`<span class="tag tag--strong">停牌</span>` : ""}
          <span class="t2 xs num">${quote.code}</span>
        </span>
        <span class="t2 xs">行业：${quote.industry}${masked ? " · 价格已按比例缩放" : ""}</span>
      </div>
      <div class="replay-stock__price">
        <span class="num ${trend} replay-stock__px">${SS.fmt.price(quote.price_cents)}</span>
        <span class="num xs ${phase === "pre_open" ? "flat" : trend}">${label} ${sub}</span>
      </div>
    </div>`;
  }

  /** 快讯 / 消息条目（feed 形状）：只显示标题与类别，时间用日期文案 */
  function feedRowHtml(it) {
    return html`<li class="replay-feed__item">
      <span class="tag">${KIND_TEXT[it.kind] || "消息"}</span>
      <span class="replay-feed__title">${it.title}</span>
      ${it.time_label ? html`<span class="t3 xs num">${it.time_label}</span>` : ""}
    </li>`;
  }

  /** 题目行（进入抽屉作答）：状态、截止、题干 */
  function questionRowHtml(q) {
    const cl = q.closes;
    const deadline = `截止 第 ${cl.day_idx + 1} 天 ${M().PHASE_LABEL[cl.phase]}`;
    // 积分不是行情数据，不用红绿（约定：红绿只用于行情）；用强调色
    const res = q.result ? html`<span class="num replay-q__pts">+${q.result.points} 积分</span>` : "";
    return html`<button type="button" class="replay-q" data-q="${q.id}">
      <span class="replay-q__main">
        <span class="replay-q__prompt">${q.prompt}</span>
        <span class="t2 xs">${deadline} · ${STATUS_TEXT[q.status] || q.status}</span>
      </span>
      ${res}
      <span class="t2" aria-hidden="true">›</span>
    </button>`;
  }

  /** 关卡卡（列表与玩法页共用）：标题、导语、标签、难度、交易日、股票数、我的最好成绩 */
  function levelCardHtml(lv, { href = null, tag = "button" } = {}) {
    const best = lv.my_best && lv.my_best.settled
      ? `最好 ${lv.my_best.best_points} 积分 · 超额 ${SS.fmt.pctBp(lv.my_best.best_excess_bp)}`
      : lv.my_best && lv.my_best.sessions
        ? "进行中或未结算"
        : "未开始";
    const inner = html`<span class="replay-level__head">
        <span class="replay-level__title">${lv.title}</span>
        <span class="t3" aria-hidden="true">›</span>
      </span>
      <span class="t2 sm replay-level__teaser">${lv.teaser}</span>
      <span class="replay-level__tags">
        ${(lv.tags || []).slice(0, 2).map((t) => html`<span class="tag">${t}</span>`)}
        <span class="tag">${M().difficultyText(lv.difficulty)}</span>
        <span class="tag">${lv.play_days} 个交易日</span>
        <span class="tag">${lv.stock_count} 只股票</span>
      </span>
      <span class="t2 xs">${best}</span>`;
    if (href) return html`<a class="card replay-level" href="${href}">${inner}</a>`;
    return html`<button type="button" class="card replay-level" data-slug="${lv.slug}">${inner}</button>`;
  }

  /** 进行中 / 已结算会话行 */
  function sessionRowHtml(s) {
    const done = s.status === "settled";
    const meta = done
      ? `已结算 · 积分 ${s.settled.points_total} · 超额 ${SS.fmt.pctBp(s.settled.excess_bp)}`
      : `第 ${s.day_idx + 1} / ${s.play_days} 天 · ${M().PHASE_LABEL[s.phase]}`;
    return html`<a class="card replay-row" href="${SS.href(done ? `/replay/${s.save_id}/reveal` : `/replay/${s.save_id}`)}">
      <span class="replay-row__main">
        <span class="replay-row__title">${s.level.title}</span>
        <span class="t2 xs">${s.masked ? "匿名" : "实名"} · ${meta}</span>
      </span>
      <span class="t2" aria-hidden="true">›</span>
    </a>`;
  }

  SS.replayUi = {
    phaseStripHtml,
    stockChipsHtml,
    klineHtml,
    stockHeadHtml,
    feedRowHtml,
    questionRowHtml,
    levelCardHtml,
    sessionRowHtml,
    STATUS_TEXT,
    KIND_TEXT,
  };
})();
