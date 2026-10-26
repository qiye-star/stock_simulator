/**
 * 预测卡纯函数（无 DOM、不读 SS.store，tests/ 在 vm 里加载；依赖 SS.predictMath 时只在函数内访问）。
 *   题目文案 / 状态与 tab 映射 / 结算表与要点 / 校准几何 / 计分镜像（仅 mock 用，真实计分在后端）。
 * 计分镜像按 docs/10.26-plan/02-预测卡.md §5 实现，tests/predict-model.test.mjs 用其中的示例校验。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const MIN_CALIB_BINS = 3; // 校准曲线至少这么多个有样本的档才画
  const TAB_STATUS = { open: "open", pending: "answered", settled: "all" }; // 列表 tab → API status
  const QTYPE_TEXT = { dir: "涨跌档位题", rank: "传导排序题", rumor: "传闻真假题" };
  const QORDER = { dir: 0, rank: 1, rumor: 2 };
  const STATUS_TAG = { open: "待答", answered: "待揭晓", settled: "已揭晓", expired: "未作答", void: "已作废" };
  const LEVEL_TEXT = { bronze: "铜", silver: "银", gold: "金", legend: "传奇" };
  const DISCOUNT = [0, 1000000, 630930, 500000, 430677, 386853, 356207, 333333, 315464, 301030, 289064]; // round(1e6·ln2/ln(i+1))，i=1..10

  const sortQuestions = (qs) => (qs || []).slice().sort((a, b) => QORDER[a.qid] - QORDER[b.qid]);
  const qOf = (card, qid) => (card.questions || []).find((q) => q.qid === qid) || null;
  // 预测卡用 answers；挑战回合卡（ChallengeRoundCardOut）用 my_answers，同形
  const aOf = (card, qid) => (card.answers || card.my_answers || []).find((a) => a.qid === qid) || null;
  const rOf = (card, qid) => (card.results || []).find((r) => r.qid === qid) || null;

  /** 目标名：行业 → "有色板块"，个股 → 股票名，全市场 → "全市场" */
  function targetLabel(q) {
    if (q.target_kind === "market") return "全市场";
    if (q.target_kind === "stock") return q.target_name || q.target || "个股";
    return `${q.target_name || q.target}板块`;
  }
  const windowDays = (q) => q.to_day - q.from_day + 1;
  // q.title 由外部题目给出（真实复盘的题干，见 features/replay/model.js predictionCardOf）时优先；后端题目没有该字段
  const dirTitle = (q, n) => `${n}. ${q.title || `${targetLabel(q)} ${windowDays(q)} 个交易日后累计涨跌幅？`}`;
  const rankTitle = (q, n) => `${n}. ${q.title || `受影响最大的 ${q.k} 个板块，依次点选`}`;
  const rumorTitle = (n) => `${n}. 这条传闻最终会被证实吗？`;

  /** 揭晓日（用户口径的交易日序号，从 0 起）：dir 的 to_day 与 rank 的 at_day 取最大；仅传闻题时为 null */
  function revealDay(card) {
    const days = [];
    const d = qOf(card, "dir");
    const r = qOf(card, "rank");
    if (d) days.push(d.to_day);
    if (r) days.push(r.at_day);
    return days.length ? Math.max(...days) : null;
  }

  /** 事件标题的短形式（结算页头部）：前 8 字 */
  const shortTitle = (t) => {
    const s = String(t || "");
    return s.length > 8 ? `${s.slice(0, 8)}…` : s;
  };

  /** 列表 tab 过滤：open / pending(answered) / settled(settled+expired) */
  function tabFilter(tab, card) {
    if (tab === "open") return card.status === "open";
    if (tab === "pending") return card.status === "answered";
    return card.status === "settled" || card.status === "expired";
  }
  const countOpen = (cards) => (cards || []).filter((c) => c.status === "open").length;

  /** 结算表：实际前三 + 用户选了但不在前三的候选（实际排名 "—"） */
  function settleRows(card) {
    const rq = qOf(card, "rank");
    if (!rq) return [];
    const res = rOf(card, "rank");
    const ans = aOf(card, "rank");
    const mine = (ans && ans.order) || [];
    const top = (res && res.true_top) || [];
    const names = [...top, ...mine.filter((x) => !top.includes(x))];
    const cb = (res && res.candidate_change_bp) || {};
    return names.map((name) => ({
      name,
      actual: top.includes(name) ? top.indexOf(name) + 1 : null,
      mine: mine.includes(name) ? mine.indexOf(name) + 1 : null,
      change_bp: cb[name] == null ? null : cb[name],
    }));
  }

  /** 用户前三中命中实际前三的个数 */
  function rankHits(order, trueTop) {
    return (order || []).filter((x) => (trueTop || []).includes(x)).length;
  }

  /**
   * “为什么这样走”要点（最多 3 条）：公开数据（传导步骤、传闻状态）用模板生成。
   * card 为 PredictionCardOut，detail 为 EventDetailOut（可空；空则返回 []）。
   */
  function whyBullets(card, detail) {
    if (!detail) return [];
    const out = [];
    const prop = detail.propagation || [];
    const sgn = (bp) => (bp > 0 ? "涨" : bp < 0 ? "跌" : "平");
    const src = prop.find((p) => p.hop === 0);
    const down = prop.find((p) => p.hop === 1 && p.change_bp != null);
    if (src && down && src.change_bp != null) {
      out.push(`${src.industry}${sgn(src.change_bp)}、${down.industry}${sgn(down.change_bp)}。`);
      if (down.relation === "supply") out.push("上游供给变化对上游是利好，对下游是成本。");
      else if (down.relation === "demand") out.push("需求变化沿链条反向传导。");
    }
    const late = prop.find((p) => p.hop >= 1 && p.change_bp != null && p.arrived_trading_day > detail.trading_day);
    if (late) {
      const k = late.arrived_trading_day - detail.trading_day;
      out.push(`${late.industry}晚 ${k} 天才明显${sgn(late.change_bp)}。`);
      out.push("冲击沿产业链有滞后。");
    }
    const st = detail.rumor_status;
    if (qOf(card, "rumor") || st === "confirmed" || st === "denied") {
      if (st === "confirmed") out.push("传闻被证实。");
      else if (st === "denied") out.push("传闻被辟谣。");
    }
    return out.slice(0, 3);
  }

  /**
   * 校准曲线几何：bins 为 CalibrationBinOut[]；只取 n>0 的档。
   * x = 声称把握（avg_claimed_pct，缺省取档中点），y = 实际命中率（hit_rate_pct）；0–100 映射到 w×h 的内框。
   */
  function calibrationPoints(bins, w, h, pad) {
    const P = pad || { l: 34, r: 6, t: 10, b: 20 };
    const iw = w - P.l - P.r;
    const ih = h - P.t - P.b;
    const used = (bins || []).filter((b) => b.n > 0 && b.hit_rate_pct != null);
    const maxN = Math.max(1, ...used.map((b) => b.n));
    const pts = used.map((b) => {
      const claimed = b.avg_claimed_pct != null ? b.avg_claimed_pct : (b.lo_pct + b.hi_pct) / 2;
      return {
        x: P.l + (Math.min(100, Math.max(0, claimed)) / 100) * iw,
        y: P.t + ih - (Math.min(100, Math.max(0, b.hit_rate_pct)) / 100) * ih,
        r: 3 + 2 * (b.n / maxN),
        n: b.n,
      };
    });
    return { pts, ready: used.length >= MIN_CALIB_BINS, P, iw, ih };
  }

  /** 平均偏差文案：630 bp → "6.3%"；null → "—" */
  const errorText = (bp) => (bp == null ? "—" : `${(bp / 100).toFixed(1)}%`);

  // ---------- 计分镜像（仅 mock；真实计分在后端 domain/scoring.py） ----------
  /** 半数向外取整的整数除法（与后端 round_half_up_div 一致） */
  function rdiv(n, d) {
    const s = (n < 0) !== (d < 0) ? -1 : 1;
    const a = Math.abs(n);
    const b = Math.abs(d);
    return s * Math.floor((2 * a + b) / (2 * b));
  }
  /** 唯一的 RPS 得分（0..100）：probs 为整数百分比，outcome 为真实档下标 */
  function rpsScore(probs, outcome) {
    const k = probs.length;
    let cum = 0;
    let S = 0;
    for (let j = 0; j < k - 1; j++) {
      cum += probs[j];
      const cumO = j >= outcome ? 100 : 0;
      S += (cum - cumO) * (cum - cumO);
    }
    return rdiv((k - 1) * 1e6 - 100 * S, (k - 1) * 1e4);
  }
  /** 均匀分布在该结果上的 RPS 分 */
  function uniformRpsScore(k, outcome) {
    let T = 0;
    for (let j = 0; j < k - 1; j++) {
      const cumO = j >= outcome ? 100 : 0; // 累积结果分布 ∈ {0,100}
      const v = (j + 1) * 100 - cumO * k; // 与 02 §5.1 的 T 同式
      T += v * v;
    }
    return rdiv((k - 1) * 1e6 * k * k - 100 * T, (k - 1) * 1e4 * k * k);
  }
  /** NDCG@3 得分（0..100）：order 为选择的候选，relevance 为 {候选: 0..3} */
  function ndcgScore(order, relevance, k) {
    const kk = k || 3;
    const gain = (r) => Math.pow(2, r) - 1;
    let dcg = 0;
    for (let i = 0; i < Math.min(kk, order.length); i++) dcg += gain(relevance[order[i]] || 0) * DISCOUNT[i + 1];
    const ideal = Object.values(relevance).sort((a, b) => b - a).slice(0, kk);
    let idcg = 0;
    ideal.forEach((r, i) => (idcg += gain(r) * DISCOUNT[i + 1]));
    return idcg ? rdiv(100 * dcg, idcg) : 0;
  }
  /** 基线分：相对瞎猜（S 与 U 均为 0..100） */
  function baselineScore(S, U) {
    if (S >= U) return U >= 100 ? 0 : rdiv(100 * (S - U), 100 - U);
    return rdiv(100 * (S - U), U);
  }

  /** 把 bucket 分布的 pick 转成中文标签（传闻题：0 辟谣 / 1 证实） */
  const rumorPickText = (pick) => (pick === 1 ? "证实" : "辟谣");

  /** 理由条目的引导句：第一个“。”之前（含句号）为引导句，其后为正文；没有正文返回 null */
  function leadSplit(text) {
    const s = String(text || "");
    const i = s.indexOf("。");
    return i > 0 && i < s.length - 1 ? { lead: s.slice(0, i + 1), rest: s.slice(i + 1) } : null;
  }

  SS.predictModel = {
    leadSplit,
    MIN_CALIB_BINS,
    TAB_STATUS,
    QTYPE_TEXT,
    STATUS_TAG,
    LEVEL_TEXT,
    sortQuestions,
    qOf,
    aOf,
    rOf,
    targetLabel,
    windowDays,
    dirTitle,
    rankTitle,
    rumorTitle,
    revealDay,
    shortTitle,
    tabFilter,
    countOpen,
    settleRows,
    rankHits,
    whyBullets,
    calibrationPoints,
    errorText,
    rdiv,
    rpsScore,
    uniformRpsScore,
    ndcgScore,
    baselineScore,
    rumorPickText,
  };
})();
