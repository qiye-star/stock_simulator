/**
 * 时钟模型（纯函数，无 DOM、不读 store/localStorage；tests/ 在 node:vm 里直接加载）。
 *
 * 唯一的时钟字段读取入口：`SS.clockModel.normalize(state.clock, …)` 把后端的
 * ClockOut / WS tick.clock（07-时钟v2 §1.2）归一化为 Clock2。字段缺失（旧后端、v1 存档）时
 * 按 v1 规则从 clock_minute + refresh_rate_ms 推算（Clock2.derived = true）。
 * 07 实施时若字段改名，只改 normalize 这一处。
 *
 * 状态栏、说明弹层、（④）收盘小结都只通过本模块理解时钟，页面不得自己推导时段/倒计时。
 *
 * 分钟均为“当日分钟数”（0–1439）：9:30 = 570，11:30 = 690，13:00 = 780，15:00 = 900。
 * v1 时段端点是闭区间（11:30、15:00 仍可下单），v2 是半开区间（07 §1.3）。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  const OPEN = 570;
  const LUNCH = 690;
  const REOPEN = 780;
  const CLOSE = 900;
  const DAY = 1440;
  const TRADING_MINUTES = 242; // 一个交易日的交易分钟数（07 §5.1）

  /** 游戏速度：v2 为每游戏分钟的现实毫秒数；v1 为行情刷新间隔 */
  const SPEEDS_V2 = { fast: 2500, normal: 5000, slow: 7500 };
  const SPEEDS_V1 = { fast: 1000, normal: 3000, slow: 5000 };
  const SPEED_IDS = ["fast", "normal", "slow"];
  const SPEED_LABEL = { fast: "快", normal: "标准", slow: "慢" };

  const PHASE_TEXT = { pre_open: "盘前", morning: "上午盘", lunch: "午休", afternoon: "下午盘", closed: "已收盘" };
  const STATUS_TEXT = { live: "交易中", paused: "已暂停", dwell: "午间休市", closed: "已收盘", pre: "待开盘", manual: "手动推进" };

  const clamp01 = (x) => Math.min(1, Math.max(0, x));
  const isV2 = (rules) => rules === "v2";

  /** 当日分钟 → 时段（07 §1.3） */
  function phaseOf(m, rules) {
    if (m < OPEN) return "pre_open";
    if (isV2(rules)) {
      if (m < LUNCH) return "morning";
      if (m < REOPEN) return "lunch";
      if (m < CLOSE) return "afternoon";
      return "closed";
    }
    if (m <= LUNCH) return "morning";
    if (m < REOPEN) return "lunch";
    if (m <= CLOSE) return "afternoon";
    return "closed";
  }

  /** 此刻能否下单（与暂停无关）。v1 闭区间、v2 半开区间，都等于“处于上午盘/下午盘” */
  const tradingOf = (m, rules) => {
    const p = phaseOf(m, rules);
    return p === "morning" || p === "afternoon";
  };

  /** 时段 → 下一个时段变化（分钟为当日分钟；closed 指次日 9:30） */
  function nextEventOf(phase) {
    switch (phase) {
      case "morning":
        return { kind: "lunch", minute: LUNCH };
      case "lunch":
        return { kind: "reopen", minute: REOPEN };
      case "afternoon":
        return { kind: "close", minute: CLOSE };
      default:
        return { kind: "open", minute: OPEN };
    }
  }

  /** 从 from 走到 to 需要的游戏分钟（跨日取模） */
  const gap = (from, to) => (((to - from) % DAY) + DAY) % DAY;

  /**
   * v1 “跳过”的目标分钟（与后端 domain/clock.py::skip_target_minutes、常量见同文件 SKIP_*）。
   * null = 无需跳过（上午盘/下午盘内、11:39–11:40 夜猫窗口末段）。
   */
  function skipTargetOf(m) {
    if (m >= 570 && m <= 690) return m < 689 ? 689 : null; // 上午盘 → 11:29
    if (m >= 695 && m <= 700) return m < 699 ? 699 : null; // 夜猫窗口 11:35–11:40 → 11:39
    if (m >= 780 && m <= 900) return m < 899 ? 899 : null; // 下午盘 → 14:59
    if (m < 570) return 569; // 盘前 → 9:29
    if (m < 695) return 694; // 11:30–11:34 → 11:34
    if (m < 780) return 779; // 午休 → 12:59
    return 569; // 收盘后 → 次日 9:29
  }

  /** 交易日进度（07 §1.3 的公式拆成上午/下午两段，各 0..1） */
  function progress(m) {
    return { am: clamp01((m - OPEN) / 120), pm: clamp01((m - REOPEN) / 120) };
  }

  /** 现实时长 → “不到 1 分钟 / 约 N 分钟 / 约 H 小时 M 分”（M 为 0 时省略） */
  function formatReal(ms) {
    const v = Math.max(0, Number(ms) || 0);
    if (v < 60000) return "不到 1 分钟";
    const m = Math.max(1, Math.round(v / 60000));
    if (m < 60) return `约 ${m} 分钟`;
    const h = Math.floor(m / 60);
    const r = m % 60;
    return r ? `约 ${h} 小时 ${r} 分` : `约 ${h} 小时`;
  }

  /** 倒计时 → “8 秒 / m:ss / h:mm:ss”（向上取整到秒，负数按 0） */
  function formatCountdown(ms) {
    const s = Math.ceil(Math.max(0, Number(ms) || 0) / 1000);
    if (s < 60) return `${s} 秒`;
    const p2 = (x) => String(x).padStart(2, "0");
    if (s < 3600) return `${Math.floor(s / 60)}:${p2(s % 60)}`;
    return `${Math.floor(s / 3600)}:${p2(Math.floor((s % 3600) / 60))}:${p2(s % 60)}`;
  }

  /** 一个交易日（242 交易分钟）在现实中约多少分钟：msPerMinute 为每游戏分钟毫秒数或刷新间隔 */
  const dayMinutes = (msPerMinute) => Math.round((TRADING_MINUTES * msPerMinute) / 60000);

  /** 当前速度档：v2 取用户的 clock_speed，v1 取与 refresh_rate_ms 最接近的档 */
  function speedOf(rules, user) {
    const u = user || {};
    if (isV2(rules)) return SPEED_IDS.includes(u.clock_speed) ? u.clock_speed : "normal";
    const ms = Number(u.refresh_rate_ms) || SPEEDS_V1.normal;
    return SPEED_IDS.reduce((best, id) => (Math.abs(SPEEDS_V1[id] - ms) < Math.abs(SPEEDS_V1[best] - ms) ? id : best), "normal");
  }

  const parseAt = (v, offset) => {
    if (v == null) return null;
    const t = Date.parse(v);
    return Number.isFinite(t) ? t - offset : null;
  };

  /**
   * 原始时钟 → Clock2。
   * opts：refresh_rate_ms（v1 的 ms_per_minute 来源，缺省 3000）、save_rules（SaveOut.clock_rules）、
   *       now（缺省 Date.now()）、received_at（收到该响应的本机时刻，缺省 now；用于 server_time 校正）。
   * raw._offset_ms（store 在收到 server_time 时写入）优先于现算的偏差。
   */
  function normalize(raw, opts = {}) {
    const r = raw || {};
    const now = opts.now != null ? opts.now : Date.now();
    let derived = false;

    const rules = r.clock_rules || opts.save_rules || "v1";
    const minute = Number.isFinite(r.clock_minute) ? r.clock_minute : Number.isFinite(r.minute) ? r.minute : OPEN;

    let phase = r.phase;
    if (!phase) {
      phase = phaseOf(minute, rules);
      derived = true;
    }
    let trading = r.trading;
    if (typeof trading !== "boolean") {
      trading = tradingOf(minute, rules);
      derived = true;
    }

    let offset = 0;
    if (typeof r._offset_ms === "number" && Number.isFinite(r._offset_ms)) offset = r._offset_ms;
    else if (r.server_time) {
      const st = Date.parse(r.server_time);
      if (Number.isFinite(st)) offset = st - (opts.received_at != null ? opts.received_at : now);
    }

    let ms = r.ms_per_minute;
    if (ms === undefined) {
      ms = isV2(rules) ? SPEEDS_V2.normal : Number(opts.refresh_rate_ms) || SPEEDS_V1.normal;
      derived = true;
    }

    const base = nextEventOf(phase);
    const ne = r.next_event || null;
    const evMinute = ne && Number.isFinite(ne.minute) ? ne.minute : base.minute;
    const paused = !!r.paused;
    let at = ne ? parseAt(ne.at, offset) : null;
    if (at == null && !paused && ms != null) {
      at = now + gap(minute, evMinute) * ms;
      derived = true;
    }
    if (!ne) derived = true;

    return {
      rules,
      minute,
      trading_day: Number.isFinite(r.trading_day) ? r.trading_day : 0,
      tick: Number.isFinite(r.tick) ? r.tick : 0,
      paused,
      phase,
      trading,
      next_event: { kind: ne && ne.kind ? ne.kind : base.kind, minute: evMinute, at },
      ms_per_minute: ms,
      next_tick_at: parseAt(r.next_tick_at, offset),
      fast_forward_at: parseAt(r.fast_forward_at, offset),
      offset_ms: offset,
      derived,
    };
  }

  /** v2 停留时长（ms，07 §5.2 默认值；后端 Settings.CLOCK_*_DWELL_MS）。mock 与测试用，真实模式以服务端字段为准 */
  const DWELL_V2 = { lunch: 5000, close: 15000 };

  /**
   * v2 调度的一步（07 §5.2 next_step_v2 的前端镜像，纯函数）：
   *   kind "tick"：交易分钟之间，dur = ms_per_minute，to = m+1；
   *   kind "jump"：11:30 停留（dur = lunch）→ 12:59；15:00 停留（dur = close）→ 次日 9:29；
   *                其它非交易分钟立即跳到下一个 9:29 或 12:59（dur = 0）。
   * minutes 为推进的游戏分钟数（与后端 tick 计数一致）。
   */
  function stepV2(m, msPerMinute, dwell = DWELL_V2) {
    const LUNCH_TO = REOPEN - 1; // 11:30 停留后跳到 12:59
    const CLOSE_TO = OPEN - 1; // 15:00 停留后跳到次日 9:29
    if (m === LUNCH) return { kind: "jump", dur: dwell.lunch, to: LUNCH_TO, minutes: gap(LUNCH, LUNCH_TO) };
    if (m === CLOSE) return { kind: "jump", dur: dwell.close, to: CLOSE_TO, minutes: gap(CLOSE, CLOSE_TO) };
    if ((m >= OPEN - 1 && m < LUNCH) || (m >= REOPEN - 1 && m < CLOSE)) return { kind: "tick", dur: msPerMinute, to: m + 1, minutes: 1 };
    const to = m >= OPEN - 1 && m < REOPEN - 1 ? REOPEN - 1 : CLOSE_TO; // 691..778 → 12:59；其它非交易分钟 → 次日 9:29
    return { kind: "jump", dur: 0, to, minutes: gap(m, to) };
  }

  /** 从 m（锚点时刻为 0）走到 target 需要的毫秒数（沿 stepV2 推演；target 不可达时返回 null） */
  function msUntilV2(m, target, msPerMinute, dwell = DWELL_V2) {
    let t = 0;
    let cur = m;
    for (let i = 0; i < 2000 && cur !== target; i++) {
      const s = stepV2(cur, msPerMinute, dwell);
      t += s.dur;
      cur = s.to;
    }
    return cur === target ? t : null;
  }

  /**
   * v2 “现在就开盘”的跳转目标（07 §6.5 表，与后端 skip_target_v2 一致）。
   * 从 9:30 起连按 8 次正好走完一个交易日（570→689→690→779→780→899→900→569→570）。
   */
  function skipTargetV2(m) {
    if (m === OPEN - 1) return OPEN; // 569 → 570（开盘，换日 tick）
    if (m < OPEN - 1 || m >= CLOSE) return OPEN - 1; // 收盘后 / 盘前 → 次日 9:29
    if (m < 689) return 689; // 570..688 → 11:29
    if (m === 689) return LUNCH; // 689 → 11:30
    if (m < REOPEN - 1) return REOPEN - 1; // 690..778 → 12:59（跳过午休停留）
    if (m === REOPEN - 1) return REOPEN; // 779 → 13:00
    if (m < CLOSE - 1) return CLOSE - 1; // 780..898 → 14:59
    return CLOSE; // 899 → 15:00
  }

  /**
   * 收盘小结的倒计时（08 §4.4 / 07 §5.4）。停留到 fast_forward_at 自动快进；文案说的是
   * “进入第 N+1 个交易日 9:30”，即 next_event.at（kind=open）。
   *   opts.now：当前时刻（ms）；opts.total_ms：小结打开时的剩余（用于进度条，缺省取当前剩余）。
   * 返回 { paused, remain_ms, open_in_ms, progress(0..1), done, text }：
   *   paused → text “已暂停，可继续查看”（remain/open 为 null）；done（剩余 ≤ 0）→ “正在进入下一交易日…”。
   */
  function closeTimer(c, opts = {}) {
    const now = opts.now != null ? opts.now : Date.now();
    if (c.paused) return { paused: true, remain_ms: null, open_in_ms: null, progress: 0, done: false, text: "已暂停，可继续查看" };
    // fast_forward_at 缺失（旧后端）时由 next_event.at 反推：到 9:30 前一个 tick 即快进
    const ff = c.fast_forward_at != null ? c.fast_forward_at : c.next_event.at != null ? c.next_event.at - (c.ms_per_minute || 0) : null;
    const openAt = c.next_event.at != null ? c.next_event.at : ff != null ? ff + (c.ms_per_minute || 0) : null;
    const remain = ff != null ? Math.max(0, ff - now) : 0;
    const openIn = openAt != null ? Math.max(0, openAt - now) : 0;
    const total = Math.max(opts.total_ms > 0 ? opts.total_ms : remain, 1);
    const done = remain <= 0;
    const nextDay = SS.fmt.dayNo(c.trading_day + 1);
    return {
      paused: false,
      remain_ms: remain,
      open_in_ms: openIn,
      progress: clamp01(1 - remain / total),
      done,
      text: done ? "正在进入下一交易日…" : `${formatCountdown(openIn)}后进入第 ${nextDay} 个交易日 9:30`,
    };
  }

  /**
   * 下单被拒（不在交易时段）时的提示文案（07 §7.4 第 7 条）。trading 为真时返回 ""。
   * v1 沿用“当前不在交易时段”；v2 按时段说明（午休 / 收盘 / 开盘前）。
   */
  function untradableText(c) {
    if (c.trading) return "";
    if (!isV2(c.rules)) return "当前不在交易时段";
    switch (c.phase) {
      case "lunch":
        return "11:30–13:00 午休不接单";
      case "closed":
        return "15:00 后不接单，次日 9:30 可下单";
      case "pre_open":
        return "9:30 开盘前不接单";
      default:
        return "当前不在交易时段";
    }
  }

  /**
   * Clock2 → TradeBarView（状态栏要显示的全部文案，见 08 §4.1 表）。
   * state: live|paused|dwell|closed|pre|manual；action: null|"resume"|"skip"（actionLabel 为按钮文字）。
   */
  function view(c, opts = {}) {
    const now = opts.now != null ? opts.now : Date.now();
    const fmt = SS.fmt;
    const v2 = isV2(c.rules);
    const n = gap(c.minute, c.next_event.minute);
    const remain = c.next_event.at != null ? Math.max(0, c.next_event.at - now) : null;
    const real = remain != null ? formatReal(remain) : c.ms_per_minute ? formatReal(n * c.ms_per_minute) : "";
    const realText = real ? `现实约 ${real.replace(/^约 /, "")}` : "";
    const dayNo = fmt.dayNo(c.trading_day);

    const out = {
      state: "live",
      statusText: STATUS_TEXT.live,
      classic: !v2,
      dayText: `${v2 ? `第 ${dayNo} 个交易日` : `D${dayNo}`} · ${PHASE_TEXT[c.phase] || ""}`,
      timeText: fmt.clock(c.minute),
      nextMain: "",
      nextSub: "",
      progress: progress(c.minute),
      countdown_ms: null,
      action: null,
      actionLabel: "",
    };

    // 各时段的主/副文案（暂停时主文案同样显示）
    let skipLabel = "跳到开盘";
    switch (c.phase) {
      case "morning":
        out.nextMain = n <= 1 ? "即将午休" : `距午休 ${n} 分钟`;
        out.nextSub = realText;
        break;
      case "afternoon":
        out.nextMain = n <= 1 ? "即将收盘" : `距收盘 ${n} 分钟`;
        out.nextSub = realText;
        break;
      case "lunch":
        out.state = "dwell";
        skipLabel = "跳到下午开盘";
        if (v2) {
          out.nextMain = "午间休市";
          out.nextSub = `${formatCountdown(remain)}后下午开盘`;
          out.countdown_ms = remain;
        } else {
          out.nextMain = `距下午开盘 ${n} 分钟`;
          out.nextSub = realText;
          out.action = "skip";
        }
        break;
      case "closed":
        out.state = "closed";
        if (v2) {
          out.nextMain = "已收盘";
          out.nextSub = `${formatCountdown(remain)}后进入第 ${fmt.dayNo(c.trading_day + 1)} 个交易日`;
          out.countdown_ms = remain;
        } else {
          out.nextMain = `距明日开盘 ${n} 分钟`;
          out.nextSub = realText;
          out.action = "skip";
        }
        break;
      default: // pre_open
        out.state = "pre";
        if (v2) {
          out.nextMain = "即将开盘";
          out.nextSub = `${formatCountdown(remain)}后开盘`;
          out.countdown_ms = remain;
        } else {
          out.nextMain = `距开盘 ${n} 分钟`;
          out.nextSub = realText;
          out.action = "skip";
        }
    }
    // 跳过目标为空或就是当前分钟（12:59、9:29、11:40 夜猫窗口末段）时不显示按钮，与后端 skip 的 0 tick 一致
    const tgt = skipTargetOf(c.minute);
    if (out.action === "skip" && (tgt == null || tgt === c.minute)) out.action = null;
    if (out.action === "skip") out.actionLabel = skipLabel;

    if (c.ms_per_minute === null) {
      // 手动推进的存档（挑战停顿、复盘）：文案由 overlay 提供
      return { ...out, state: "manual", statusText: STATUS_TEXT.manual, nextMain: "", nextSub: "", countdown_ms: null, action: null, actionLabel: "" };
    }
    if (c.paused) {
      return { ...out, state: "paused", statusText: STATUS_TEXT.paused, nextSub: "行情已暂停", countdown_ms: null, action: "resume", actionLabel: "继续" };
    }
    out.statusText = STATUS_TEXT[out.state];
    return out;
  }

  SS.clockModel = {
    phaseOf,
    tradingOf,
    nextEventOf,
    gap,
    skipTargetOf,
    skipTargetV2,
    stepV2,
    msUntilV2,
    closeTimer,
    untradableText,
    DWELL_V2,
    progress,
    normalize,
    view,
    speedOf,
    dayMinutes,
    formatReal,
    formatCountdown,
    SPEEDS_V1,
    SPEEDS_V2,
    SPEED_IDS,
    SPEED_LABEL,
    PHASE_TEXT,
    TRADING_MINUTES,
  };
})();
