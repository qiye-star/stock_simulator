/**
 * 交易时间说明弹层 SS.clockHelp（对照画板 ClockHelp，08 §4.3）。
 *
 *   SS.clockHelp.open({ focus })      打开弹层；focus:"speed" 时滚到“游戏速度”区
 *   SS.clockHelp.maybeAutoOpen()      首次进入主动弹一次，返回是否弹出了
 *
 * 首次弹出的记忆键 localStorage["ss.clockHelp"] = 看过的规则（"v1"/"v2"，切到另一种规则的存档会再看一次）；
 * localStorage 读写全部 try/catch，不可用时每种规则每次会话最多弹一次（模块变量 shownRules）。
 *
 * 速度档：v1 存档 = 行情刷新间隔（store.setRefreshRate，1s/3s/5s ≈ 4/12/20 分钟一天）；
 *        v2 存档 = 游戏速度（store.setClockSpeed，④ 实现 PATCH /me {clock_speed}）。
 *        v2 但 store 还没有 setClockSpeed 时，速度区置灰并标“即将开放”，不发任何请求。
 * 速度改变成功后 store.emitLocal("user")，“我的”页的速度行据此刷新。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const KEY = "ss.clockHelp";
  let shownRules = null; // 本次会话已自动弹过的规则

  const ls = {
    get() {
      try {
        return localStorage.getItem(KEY);
      } catch (_) {
        return null;
      }
    },
    set(v) {
      try {
        localStorage.setItem(KEY, v);
      } catch (_) {
        /* 隐私模式/禁用存储：忽略，退化为每会话一次 */
      }
    },
  };

  const currentClock = () => {
    const st = SS.store.state;
    return SS.clockModel.normalize(st.clock, { refresh_rate_ms: st.user && st.user.refresh_rate_ms, save_rules: st.save && st.save.clock_rules });
  };

  const row = (time, text, on) => html`<li class="timeline__row">
    <span class="timeline__time num">${time}</span><span class="timeline__dot ${on ? "timeline__dot--on" : ""}" aria-hidden="true"></span>
    <span class="timeline__text">${text}</span>
  </li>`;
  const line = (dashed) => html`<li class="timeline__line ${dashed ? "timeline__line--dashed" : ""}" aria-hidden="true"><span></span></li>`;
  const sub = (t) => html`<span class="t2 sm"> · ${t}</span>`;

  function content(body, api, focus) {
    const store = SS.store;
    const M = SS.clockModel;
    const c = currentClock();
    const v2 = c.rules === "v2";
    const t0 = !!(store.state.save && store.state.save.t0_mode);
    const speeds = v2 ? M.SPEEDS_V2 : M.SPEEDS_V1;
    const canSet = v2 ? typeof store.setClockSpeed === "function" : true;
    // 挑战存档：全服同一时间线，不给速度选择（08 §5.7）
    const inChallenge = !!(store.state.save && store.state.save.mode === "challenge");
    let cur = M.speedOf(c.rules, store.state.user);

    SS.mount(
      body,
      html`<div class="clock-help">
        <div>
          <h2 class="clock-help__title">什么时候能交易？</h2>
          <p class="clock-help__lead">和真实 A 股一样，一天分上午、下午两段。只有交易时段内价格会动、才能成交。</p>
        </div>
        <ol class="timeline">
          ${row("9:30", html`<b>开盘</b>${sub("上午盘开始")}`, true)}
          ${line(false)}
          ${row("11:30", html`<b>午休</b>${sub(v2 ? "自动快进，约 10 秒" : "照常计时，可在状态栏跳过")}`, false)}
          ${line(true)}
          ${row("13:00", html`<b>下午开盘</b>`, true)}
          ${line(false)}
          ${row("15:00", html`<b>收盘</b>${sub(v2 ? "看完收盘小结后快进到次日 9:30" : "可在状态栏跳到次日开盘")}`, false)}
        </ol>
        ${v2 ? html`<p class="clock-help__note xs t2">11:30 与 15:00 不接单；行情暂停时仍可手动下单。</p>` : ""}
        <div class="rule-cards">
          <div class="rule-card">
            <span class="t2 xs">${t0 ? "T+0" : "T+1"}</span><span class="sm">${t0 ? "当天买入当天可卖" : "今天买的明天才能卖"}</span>
          </div>
          <div class="rule-card"><span class="t2 xs">涨跌停</span><span class="sm">单日最多涨跌 10%</span></div>
          <div class="rule-card">
            ${v2
              ? html`<span class="t2 xs">一天 = 一根 K 线</span><span class="sm">收盘时生成日 K</span>`
              : html`<span class="t2 xs">老存档</span><span class="sm">约每 20 个游戏分钟生成一根日 K</span>`}
          </div>
        </div>
        ${inChallenge ? "" : html`<div class="speed-pick" data-role="speed">
          <div class="speed-pick__head">
            <span class="speed-pick__title">${v2 ? "游戏速度" : "行情刷新"}</span>
            <span class="t2 sm">${v2 ? "（交易时段一天在现实中多久）" : "（行情刷新间隔，交易时段一天在现实中多久）"}</span>
            ${canSet ? "" : html`<span class="tag">即将开放</span>`}
          </div>
          <div class="speed-seg" role="radiogroup" aria-label="${v2 ? "游戏速度" : "行情刷新间隔"}">
            ${M.SPEED_IDS.map(
              (id) => html`<button type="button" class="speed-seg__opt" role="radio" data-speed="${id}" aria-checked="${String(id === cur)}" tabindex="${id === cur ? 0 : -1}" ${canSet ? "" : "disabled"}>
                <span>${M.SPEED_LABEL[id]}</span><span class="num speed-seg__sub">约 ${M.dayMinutes(speeds[id])} 分钟</span>
              </button>`
            )}
          </div>
          ${v2 ? "" : html`<p class="speed-pick__note xs t2" data-role="rate-note"></p>`}
        </div>`}
        <button type="button" class="btn btn-primary btn-block" data-role="ok">知道了</button>
      </div>`
    );
    api.el.setAttribute("aria-label", "交易时间说明");

    const $ = (r) => SS.$(`[data-role="${r}"]`, body);
    const opts = SS.$$(".speed-seg__opt", body);
    const paintNote = () => {
      const n = $("rate-note");
      if (n) n.textContent = `行情每 ${speeds[cur] / 1000} 秒刷新一次`;
    };
    const paintSel = (id) => {
      opts.forEach((b) => {
        const on = b.dataset.speed === id;
        b.setAttribute("aria-checked", on);
        b.tabIndex = on ? 0 : -1;
      });
    };
    paintNote();

    async function choose(id) {
      if (!canSet || id === cur) return;
      const prev = cur;
      cur = id;
      paintSel(id);
      paintNote();
      SS.haptic(6);
      try {
        if (v2) await store.setClockSpeed(id);
        else await store.setRefreshRate(speeds[id]);
        store.emitLocal("user", store.state.user);
        SS.toast(v2 ? `游戏速度：${M.SPEED_LABEL[id]}` : `行情每 ${speeds[id] / 1000} 秒刷新`, { duration: 1400 });
      } catch (err) {
        cur = prev;
        paintSel(prev);
        paintNote();
        store.notifyError(err);
      }
    }
    opts.forEach((b, i) => {
      b.addEventListener("click", () => choose(b.dataset.speed));
      b.addEventListener("keydown", (e) => {
        const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        e.preventDefault();
        const nb = opts[(i + d + opts.length) % opts.length];
        nb.focus();
        choose(nb.dataset.speed);
      });
    });
    $("ok").addEventListener("click", api.close);

    if (focus === "speed") {
      // 不用 scrollIntoView（会连带滚动 overflow:hidden 的祖先）；差值与抽屉入场位移无关
      requestAnimationFrame(() => {
        const t = $("speed");
        if (!t) return; // 挑战存档没有速度区（inChallenge），不滚动
        body.scrollTop = Math.max(0, t.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 12);
      });
    }
  }

  function open({ focus } = {}) {
    const rules = currentClock().rules;
    return SS.sheet.open({
      title: "",
      className: "sheet-layer--help",
      render: (body, api) => content(body, api, focus),
      onClose: () => ls.set(rules),
    });
  }

  /**
   * 首次自动弹出。若此时已有抽屉（如待答预测卡，优先级更高）打开，则排队到所有抽屉关闭后再弹（不占用当前抽屉）。
   * 返回 true 表示已弹出或已排队（调用方据此跳过其它提示）。
   */
  function maybeAutoOpen() {
    if (!SS.ready || /^#\/login/.test(location.hash)) return false;
    const rules = currentClock().rules;
    if (shownRules === rules || ls.get() === rules) return false;
    shownRules = rules; // 排队也算本会话已处理，避免重复排队
    const pop = () => {
      // 排队期间可能已在别处看过（如另一标签页写入了记忆键）
      if (ls.get() === rules) return;
      open();
    };
    if (SS.sheet.hasOpen()) {
      SS.sheet.whenIdle(pop);
      return true;
    }
    open();
    return true;
  }

  SS.clockHelp = { open, maybeAutoOpen };
})();
