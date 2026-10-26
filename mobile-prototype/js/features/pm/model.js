/**
 * 预测市场（⑧ D）的纯函数（无 DOM、不读 SS.store；tests/ 在 vm 里加载）。
 *   LMSR（04 §4.2 同一公式，浮点）：costOf / pricesPpm / buyPoints / sellPoints / quoteOf / maxSharesForBudget
 *     只用于 mock 报价与 mock 的成交模拟；真实模式的报价与成交永远以服务端为准（04 §4.3 整数规则在服务端）。
 *   限额与滑点（04 §5.4、§5.5）：slippageLimit / netCostCap
 *   展示文案：formatProb / outcomeLabels / questionText / statusText / closeText / leadingIndex
 *   曲线与推送：curvePaths（按 SVG viewBox 生成 path）、applyTick（只接受 seq 更大的推送）
 *   持仓：positionOf（按 idx 从稀疏的 my.outcomes 取值）、holdingValue
 * 依赖 SS.predictMath.bucketLabels（js/lib/predict-math.js，先于本文件加载）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const PPM = 1000000;
  const SHARE_POINTS = 100; // 每份兑付（04 §3.4）
  const MAX_SHARES = 200; // 单笔份额上限（04 §4.3）
  const SLIP = 0.02; // 默认滑点容差（04 §5.4，客户端按此计算 max_cost / min_proceeds）
  const EPS = 1e-9;
  const RUMOR_LABELS = ["会被辟谣", "会被证实"]; // deny, confirm（与 04 §3.2 选项序一致）
  const STATUS_TEXT = { open: "进行中", closed: "待结算", resolved: "已结算", voided: "已作废" };

  // ---------- LMSR（浮点，仅 mock 与预估）----------
  /** C(q)·/100 的积分形式：100·(m + b·ln Σ exp((q_i − m)/b))，b = bMilli/1000 */
  function costOf(q, bMilli) {
    const b = bMilli / 1000;
    const m = Math.max(...q);
    let s = 0;
    for (const x of q) s += Math.exp((x - m) / b);
    return SHARE_POINTS * (m + b * Math.log(s));
  }

  /** 各选项概率（浮点，和为 1） */
  function pricesOf(q, bMilli) {
    const b = bMilli / 1000;
    const m = Math.max(...q);
    const e = q.map((x) => Math.exp((x - m) / b));
    const s = e.reduce((a, c) => a + c, 0);
    return e.map((v) => v / s);
  }

  /** 整数 ppm，和恰为 1e6（最大余数法；余数相同取小下标，与 04 §4.1 prices_ppm 一致） */
  function pricesPpm(q, bMilli) {
    const exact = pricesOf(q, bMilli).map((x) => x * PPM);
    const base = exact.map((x) => Math.floor(x));
    let rest = PPM - base.reduce((a, c) => a + c, 0);
    const order = exact.map((_, i) => i).sort((i, j) => exact[j] - base[j] - (exact[i] - base[i]) || i - j);
    for (const i of order) {
      if (rest <= 0) break;
      base[i] += 1;
      rest -= 1;
    }
    return base;
  }

  const withDelta = (q, i, d) => {
    const out = q.slice();
    out[i] += d;
    return out;
  };

  /** 买入 n 份的花费（积分，向上取整，至少 1）；n ≤ 0 为 0 */
  function buyPoints(q, bMilli, i, n) {
    if (n <= 0) return 0;
    const x = costOf(withDelta(q, i, n), bMilli) - costOf(q, bMilli);
    return Math.max(1, Math.ceil(x - EPS));
  }

  /** 卖出 n 份的回款（积分，向下取整，可为 0） */
  function sellPoints(q, bMilli, i, n) {
    if (n <= 0) return 0;
    const y = costOf(q, bMilli) - costOf(withDelta(q, i, -n), bMilli);
    return Math.max(0, Math.floor(y + EPS));
  }

  /** 报价（与 PmQuoteOut 同形）：avg_price_ppm = 花费·10000 / 份额（100 积分 = 1e6 ppm） */
  function quoteOf(q, bMilli, side, i, shares) {
    const sell = side === "sell";
    const points = sell ? sellPoints(q, bMilli, i, shares) : buyPoints(q, bMilli, i, shares);
    const after = withDelta(q, i, sell ? -shares : shares);
    return {
      side,
      outcome: i,
      shares,
      points,
      avg_price_ppm: shares > 0 ? Math.round((points * 10000) / shares) : 0,
      price_before_ppm: pricesPpm(q, bMilli)[i],
      prices_after_ppm: pricesPpm(after, bMilli),
    };
  }

  /** 预算内能买的最大份额（花费单调不减，二分；≤ cap 且 ≤ MAX_SHARES） */
  function maxSharesForBudget(q, bMilli, i, budget, cap = MAX_SHARES) {
    let lo = 0;
    let hi = Math.min(cap, MAX_SHARES);
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (buyPoints(q, bMilli, i, mid) <= budget) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  // ---------- 限额与滑点 ----------
  /** 滑点保护：买入给最多花费（ceil·(1+tol)），卖出给最少回款（floor·(1−tol)） */
  function slippageLimit(points, side, tol = SLIP) {
    return side === "sell" ? Math.floor(points * (1 - tol) + EPS) : Math.ceil(points * (1 + tol) - EPS);
  }

  /** 单市场净投入上限 max(200, S // 4)（04 §5.5） */
  const netCostCap = (subsidyPoints) => Math.max(200, Math.floor(subsidyPoints / 4));

  // ---------- 展示 ----------
  /** 概率：ppm → “62.0%”，不足 0.1% 显示 “<0.1%”；空值显示 “—” */
  function formatProb(ppm) {
    if (ppm == null || Number.isNaN(Number(ppm))) return "—";
    const v = Number(ppm) / 10000;
    if (v > 0 && v < 0.1) return "<0.1%";
    return `${v.toFixed(1)}%`;
  }

  /** 选项宽度（百分比，0–100），给概率条用 */
  const barPct = (ppm) => Math.max(0, Math.min(100, Number(ppm || 0) / 10000));

  /** 选项文案：bucket 用 02 的分档边界（bucketLabels），rumor 固定 deny/confirm */
  function outcomeLabels(m) {
    if (!m) return [];
    if (m.kind === "rumor") return RUMOR_LABELS.slice();
    return SS.predictMath.bucketLabels((m.question && m.question.edges_bp) || [-600, -200, 200, 600]);
  }

  function subjectOf(q) {
    if (!q) return "";
    if (q.scope === "industry") return `${q.industry || ""}板块`;
    if (q.scope === "stock") return q.stock_name || q.code || "该股票";
    return "全市场";
  }

  /** 问题句：bucket “{主体} N 个交易日后累计涨跌幅落在哪一档？”；rumor “{事件标题}——会被辟谣吗？” */
  function questionText(m) {
    if (m.kind === "rumor") {
      const title = (m.event && m.event.title) || "这条传闻";
      return `${title}——会被辟谣吗？`;
    }
    const q = m.question || {};
    const days = q.from_day != null && q.to_day != null ? q.to_day - q.from_day + 1 : 3;
    return `${subjectOf(q)} ${days} 个交易日后累计涨跌幅落在哪一档？`;
  }

  const statusText = (status) => STATUS_TEXT[status] || "";

  /**
   * 关闭说明（04 §3.3）：bucket 在窗口最后一个交易日开盘停止交易（question.to_day 为 0 起的序号，展示 +1）；
   * rumor 的关闭时点保密，写“揭晓前停止交易”。已停止交易后改写状态文案。
   */
  function closeText(m) {
    if (m.status === "resolved") return "已结算";
    if (m.status === "voided") return "已作废";
    if (m.status === "closed") return m.kind === "rumor" ? "已停止交易，揭晓后结算" : "已停止交易，等待结算";
    if (m.kind === "rumor") return "揭晓前停止交易";
    const to = m.question && m.question.to_day;
    return to == null ? "" : `第 ${to + 1} 个交易日开盘前停止交易`;
  }

  /** 概率最高的选项下标（并列取小下标） */
  function leadingIndex(prices) {
    let best = 0;
    prices.forEach((p, i) => {
      if (p > prices[best]) best = i;
    });
    return best;
  }

  // ---------- 曲线 ----------
  /**
   * 单选项概率曲线的 SVG path（viewBox W×H，概率 0–1 映射到纵向 [pad, H−pad]）。
   * points：概率数组（0–1，按时间升序）。返回 { line, area, last:{x,y}|null }；空数组全为空串。
   */
  function curvePaths(points, W = 320, H = 90, pad = 6) {
    const n = points.length;
    if (!n) return { line: "", area: "", last: null };
    const y = (p) => pad + (1 - Math.min(1, Math.max(0, p))) * (H - 2 * pad);
    const x = (i) => (n === 1 ? W : (i / (n - 1)) * W);
    const pts = points.map((p, i) => [x(i), y(p)]);
    const line = pts.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)} ${b.toFixed(1)}`).join(" ");
    const area = `${line} L${W} ${H} L0 ${H} Z`;
    const last = pts[n - 1];
    return { line, area, last: { x: Number(last[0].toFixed(1)), y: Number(last[1].toFixed(1)) } };
  }

  /**
   * 推送合并（04 §8.1 pm_tick）：只接受 seq 更大的推送（或状态变化）；返回新对象，不改入参。
   * msg: { id, seq, status, prices_ppm, volume_shares }
   */
  function applyTick(m, msg) {
    if (!m || !msg || msg.id !== m.id) return m;
    const stale = msg.seq != null && msg.seq <= (m.trade_seq || 0) && (msg.status == null || msg.status === m.status);
    if (stale) return m;
    const prices = Array.isArray(msg.prices_ppm) ? msg.prices_ppm : null;
    return {
      ...m,
      status: msg.status || m.status,
      trade_seq: msg.seq != null ? msg.seq : m.trade_seq,
      volume_shares: msg.volume_shares != null ? msg.volume_shares : m.volume_shares,
      outcomes: m.outcomes.map((o, i) => ({ ...o, price_ppm: prices && prices[i] != null ? prices[i] : o.price_ppm })),
    };
  }

  /**
   * 我的某选项持仓（PmMyPositionOut.outcomes 是稀疏列表，只含有过持仓的选项，按 idx 取值，不能按数组下标）。
   * 返回 {shares, cost_points, value_points}；没有记录时全为 0。
   */
  function positionOf(my, i) {
    const row = my && Array.isArray(my.outcomes) ? my.outcomes.find((o) => o && o.idx === i) : null;
    return {
      shares: row ? Number(row.shares) || 0 : 0,
      cost_points: row ? Number(row.cost_points) || 0 : 0,
      value_points: row ? Number(row.value_points) || 0 : 0,
    };
  }

  /** 持仓估值（积分）：Σ shares·price_ppm·100 / 1e6，四舍五入（与 PmMyPositionOut.value_points 同口径） */
  function holdingValue(shares, prices) {
    let v = 0;
    shares.forEach((n, i) => {
      v += (Number(n) || 0) * (Number(prices[i]) || 0);
    });
    return Math.round((v * SHARE_POINTS) / PPM);
  }

  /** 玩法页预测市场分区无进行中合约时的文案：一个市场都没有 → 开赛前；有过市场但都已结束 → 已结束 */
  function emptyText(items) {
    return (items || []).length ? "今日市场已结束，暂无进行中的合约" : "今日挑战开始后开市";
  }

  SS.pmModel = {
    emptyText,
    SHARE_POINTS,
    MAX_SHARES,
    SLIP,
    RUMOR_LABELS,
    costOf,
    pricesOf,
    pricesPpm,
    buyPoints,
    sellPoints,
    quoteOf,
    maxSharesForBudget,
    slippageLimit,
    netCostCap,
    formatProb,
    barPct,
    outcomeLabels,
    questionText,
    statusText,
    closeText,
    leadingIndex,
    curvePaths,
    applyTick,
    holdingValue,
    positionOf,
  };
})();
