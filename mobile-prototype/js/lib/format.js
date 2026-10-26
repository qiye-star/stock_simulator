/**
 * 统一格式化（金额一律以整数分为输入）。
 * 页面里禁止自己 toFixed 金额，统一走这里，接后端时只需保证字段仍是 *_cents。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  const group = (intStr) => intStr.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  /** 分 → "1,234.56"；opts.sign 为 true 时正数带 "+"；opts.symbol 加 "¥" */
  function yuan(cents, opts = {}) {
    const n = Math.round(Number(cents) || 0);
    const neg = n < 0;
    const abs = Math.abs(n);
    const s = group(String(Math.floor(abs / 100))) + "." + String(abs % 100).padStart(2, "0");
    const sign = neg ? "-" : opts.sign && n > 0 ? "+" : "";
    return sign + (opts.symbol ? "¥" : "") + s;
  }

  /** 分 → 紧凑表示："8,520.00" / "12.35万" / "1.20亿" */
  function yuanCompact(cents, opts = {}) {
    const y = (Number(cents) || 0) / 100;
    const abs = Math.abs(y);
    const sign = y < 0 ? "-" : opts.sign && y > 0 ? "+" : "";
    if (abs >= 1e8) return sign + (abs / 1e8).toFixed(2) + "亿";
    if (abs >= 1e5) return sign + (abs / 1e4).toFixed(2) + "万";
    return yuan(cents, opts);
  }

  /** 价格（分）→ "1,688.00"，不带符号 */
  const price = (cents) => yuan(cents);

  /** 基点 → 百分比字符串：123 → "+1.23%" */
  function pctBp(bp, opts = { sign: true }) {
    const v = (Number(bp) || 0) / 100;
    const sign = opts.sign && v > 0 ? "+" : "";
    return sign + v.toFixed(2) + "%";
  }

  /** 浮点百分比（自动交易字段，2.5 = 2.5%）→ "2.5%" */
  const pctFloat = (p) => (p == null ? "—" : `${Number(p).toFixed(2).replace(/\.?0+$/, "")}%`);

  /** 涨跌方向 → CSS 类名（红涨绿跌） */
  const trend = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

  /** 股数 → "1,200" */
  const qty = (n) => group(String(Math.round(Number(n) || 0)));

  /** 成交量（股）→ "12.3万手"（1 手 = 100 股） */
  function volume(shares) {
    const lots = (Number(shares) || 0) / 100;
    if (lots >= 1e8) return (lots / 1e8).toFixed(2) + "亿手";
    if (lots >= 1e4) return (lots / 1e4).toFixed(1) + "万手";
    return Math.round(lots) + "手";
  }

  /** 当日分钟数 → "10:35" */
  const clock = (minute) =>
    `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

  /** 交易日序号（后端从 0 起）→ 面向用户的序号（从 1 起）：所有“第 N 个交易日”“D{n}”文案一律经此函数 */
  const dayNo = (d) => (Number(d) || 0) + 1;

  /** 与后端 domain/clock.py 的 session_label 对应 */
  const SESSION_TEXT = {
    early_bird: "早盘开盘",
    night_owl: "午间休市前",
    afternoon_open: "午后开盘",
    trading: "交易中",
    closed: "已休市",
  };
  const session = (s, paused) => (paused ? "已暂停" : SESSION_TEXT[s] || s);

  /** ISO 时间 → "10-23 14:05" */
  function dateTime(iso) {
    const d = new Date(iso);
    const p = (x) => String(x).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  /** 输入框里的“元”字符串 → 分（非法返回 null） */
  function parseYuan(str) {
    const s = String(str).trim();
    if (!/^\d+(\.\d{0,2})?$/.test(s)) return null;
    const [i, f = ""] = s.split(".");
    return Number(i) * 100 + Number((f + "00").slice(0, 2));
  }

  /** 分 → 输入框用的 "12.34"（无千分位） */
  const toInput = (cents) => (Math.round(cents) / 100).toFixed(2);

  SS.fmt = { yuan, yuanCompact, price, pctBp, pctFloat, trend, qty, volume, clock, dayNo, session, dateTime, parseYuan, toInput };
})();
