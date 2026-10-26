/**
 * 交易状态栏 SS.tradeBar —— 取代旧的右上角时钟胶囊（08 §4.2）。
 *
 *   const unmount = SS.tradeBar.mount(el, { variant: "full" | "compact" });
 *   SS.tradeBar.setOverlay(key, overlay | null);   // ⑥/⑦ 用：{ priority, statusText?, nextMain?, nextSub?, action?: {label, run} }
 *
 * 唯一数据入口是 store.state.clock（经 SS.clockModel.normalize → view 得到全部文案），
 * 组件不自己推导时段/倒计时；所有页面复用同一组件：行情页用 full（大卡片），持仓/个股页用 compact（单行胶囊）。
 * 订阅 store 的 "tick" 事件，只就地改文本/属性/进度宽度，不重建 DOM（避免打断点按与动画）；
 * view.countdown_ms 有值（v2 停留/收盘/盘前倒计时）时开 1 秒计时器，只刷新副文案。
 * 点状态栏 → SS.clockHelp.open()；“继续”（暂停时）与“跳过”（v1 非交易时段）按钮在 full 变体的卡片下方。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  // ---------- overlay：其它功能（预测卡暂停、挑战停顿…）覆盖状态栏部分文案 ----------
  const overlays = new Map(); // key → overlay
  const repaints = new Set(); // 已挂载实例的重绘函数

  function setOverlay(key, overlay) {
    if (overlay) overlays.set(key, overlay);
    else overlays.delete(key);
    repaints.forEach((f) => f());
  }

  function topOverlay() {
    let best = null;
    for (const o of overlays.values()) if (!best || (o.priority || 0) > (best.priority || 0)) best = o;
    return best;
  }

  /** 把最高优先级的 overlay 叠到 view 上；overlay.action 的按钮用 action:"overlay" 表示；overlay.action 为 null 时隐藏按钮 */
  function applyOverlay(v) {
    const o = topOverlay();
    if (!o) return v;
    const out = { ...v };
    for (const k of ["statusText", "nextMain", "nextSub"]) if (o[k] != null) out[k] = o[k];
    // 写了 action 键（即使为 null）就接管动作区：null 表示隐藏按钮（入口由别处提供，如挑战横幅）
    if ("action" in o) {
      if (o.action) {
        out.action = "overlay";
        out.actionLabel = o.action.label;
        out.overlayAction = o.action;
      } else {
        out.action = null;
      }
    }
    return out;
  }

  // ---------- DOM ----------
  const fullHtml = () => html`<section class="trade-bar-wrap">
    <button type="button" class="trade-bar" data-state="live" aria-haspopup="dialog">
      <span class="trade-bar__head">
        <span class="trade-bar__lead">
          <span class="trade-bar__status" aria-live="polite"><i class="trade-bar__dot" aria-hidden="true"></i><span data-tb="status">交易中</span></span>
          <span class="tag" data-tb="classic" hidden>经典节奏</span>
        </span>
        <span class="trade-bar__day"><span data-tb="day"></span><span class="trade-bar__help" aria-hidden="true">?</span></span>
      </span>
      <span class="trade-bar__main">
        <span class="trade-bar__time num" data-tb="time"></span>
        <span class="trade-bar__next"><b data-tb="next"></b><span class="t2" data-tb="sub"></span></span>
      </span>
      <span class="trade-bar__track" aria-hidden="true">
        <span class="trade-bar__seg"><i></i></span><span class="trade-bar__gap"></span><span class="trade-bar__seg"><i></i></span>
      </span>
      <span class="trade-bar__ticks num" aria-hidden="true">
        <span><b>9:30</b><b>11:30</b></span><span></span><span><b>13:00</b><b>15:00</b></span>
      </span>
      <span class="sr-only">点按查看交易时间说明</span>
    </button>
    <div class="trade-bar__actions" hidden><button type="button" class="btn btn-block" data-tb="action">继续</button></div>
  </section>`;

  const compactHtml = () => html`<button type="button" class="trade-bar trade-bar--compact" data-state="live" aria-haspopup="dialog" aria-label="交易时间说明">
    <span class="trade-bar__status" aria-live="polite"><i class="trade-bar__dot" aria-hidden="true"></i><span data-tb="status">交易中</span></span>
    <span class="num t2" data-tb="time"></span>
    <span class="t3" data-tb="next"></span>
  </button>`;

  function mount(el, { variant = "full" } = {}) {
    const store = SS.store;
    const M = SS.clockModel;
    const compact = variant === "compact";
    SS.mount(el, compact ? compactHtml() : fullHtml());
    const bar = SS.$(".trade-bar", el);
    const node = (k) => SS.$(`[data-tb="${k}"]`, el);
    const segs = SS.$$(".trade-bar__seg", el);
    const actions = SS.$(".trade-bar__actions", el);
    const setText = (n, t) => {
      if (n && n.textContent !== t) n.textContent = t;
    };

    let clock2 = null;
    let view = null;
    let timer = null;

    const normalize = () => {
      const st = store.state;
      clock2 = M.normalize(st.clock, { refresh_rate_ms: st.user && st.user.refresh_rate_ms, save_rules: st.save && st.save.clock_rules, now: Date.now() });
    };

    /** 用最近一次 normalize 的结果重绘（计时器与 overlay 变化只走这里，不重新 normalize） */
    function paint() {
      if (!clock2) return;
      view = applyOverlay(M.view(clock2, { now: Date.now() }));
      bar.dataset.state = view.state;
      setText(node("status"), view.statusText);
      setText(node("time"), view.timeText);
      if (compact) {
        setText(node("next"), view.nextMain ? `· ${view.nextMain}` : "");
      } else {
        setText(node("day"), view.dayText);
        setText(node("next"), view.nextMain);
        setText(node("sub"), view.nextSub);
        node("classic").hidden = !view.classic;
        segs[0].style.setProperty("--p", view.progress.am.toFixed(4));
        segs[1].style.setProperty("--p", view.progress.pm.toFixed(4));
        const hasAction = !!view.action;
        actions.hidden = !hasAction;
        if (hasAction) setText(node("action"), view.actionLabel);
      }
      // 倒计时类副文案需要每秒刷新；其它情形随 tick 刷新即可
      const need = view.countdown_ms != null;
      if (need && !timer) timer = setInterval(paint, 1000);
      else if (!need && timer) {
        clearInterval(timer);
        timer = null;
      }
    }
    function refresh() {
      normalize();
      paint();
    }

    bar.addEventListener("click", () => SS.clockHelp && SS.clockHelp.open());
    const btn = node("action");
    if (btn)
      btn.addEventListener("click", async () => {
        const v = view;
        if (!v || !v.action) return;
        btn.disabled = true;
        try {
          if (v.action === "overlay") await v.overlayAction.run();
          else if (v.action === "resume") {
            if (await SS.guards.check("resume")) await store.setPaused(false);
          } else if (v.action === "skip") await store.skipClock();
        } catch (e) {
          store.notifyError(e);
        } finally {
          btn.disabled = false;
        }
      });

    const off = store.on("tick", refresh);
    repaints.add(paint);
    refresh();

    return function unmount() {
      off();
      repaints.delete(paint);
      clearInterval(timer);
      timer = null;
      el.textContent = "";
    };
  }

  SS.tradeBar = { mount, setOverlay };
})();
