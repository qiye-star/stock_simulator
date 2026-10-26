/**
 * 预测卡共用的纯数学（无 DOM、不读 SS.store，tests/ 可直接加载）：
 *   probsFromPick(pick, confPct, k)  “档位 + 把握”→ 整数百分比分布（02 §5.2，与后端 domain 同算法）
 *   argmaxPick(probs)                唯一最大值的下标，并列返回 null
 *   confRange(k)                     把握滑块的范围与默认值（02 §4：CONF_MIN_PCT / CONF_MAX / STEP / DEFAULT）
 *   bucketLabels(edgesBp)            5 档按钮文案，如 ["<−6%","−6~−2","−2~2","2~6","≥6%"]
 *   bucketRangeText(i, edgesBp)      结算页“第 N 档（区间）”，如 "2%~6%"
 * 放在 lib/ 而不是 features/predict/：E（真实复盘）也要用同一套分档与分布。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const MINUS = "−";

  /** “档位 + 把握”→ 分布：pick 得 conf，其余 100−conf 平分；余数按“离 pick 近优先、同距下标小优先”逐个 +1 */
  function probsFromPick(pick, confPct, k) {
    const rest = 100 - confPct;
    const others = k - 1;
    const base = Math.floor(rest / others);
    let extra = rest - base * others;
    const probs = Array.from({ length: k }, (_, i) => (i === pick ? confPct : base));
    const order = [];
    for (let i = 0; i < k; i++) if (i !== pick) order.push(i);
    order.sort((a, b) => Math.abs(a - pick) - Math.abs(b - pick) || a - b);
    for (const i of order) {
      if (extra <= 0) break;
      probs[i] += 1;
      extra -= 1;
    }
    return probs;
  }

  /** 唯一最大值的下标；并列最大返回 null（与 domain.scoring.argmax_pick 一致） */
  function argmaxPick(probs) {
    let best = -1;
    let idx = null;
    let tie = false;
    probs.forEach((p, i) => {
      if (p > best) {
        best = p;
        idx = i;
        tie = false;
      } else if (p === best) tie = true;
    });
    return tie ? null : idx;
  }

  /** 把握滑块：k=5（方向题）20–100，k=2（传闻题）50–100，步长 5，默认 50 / 70 */
  function confRange(k) {
    return { min: k === 5 ? 20 : 50, max: 100, step: 5, def: k === 5 ? 50 : 70 };
  }

  /** 基点 → 带符号的百分数字符串（去尾零）：-600 → "−6"，250 → "2.5" */
  function num(bp) {
    const v = Math.abs(bp) / 100;
    return (bp < 0 ? MINUS : "") + String(Number(v.toFixed(2)));
  }

  function bucketLabels(e) {
    const [a, b, c, d] = e;
    return [`<${num(a)}%`, `${num(a)}~${num(b)}`, `${num(b)}~${num(c)}`, `${num(c)}~${num(d)}`, `≥${num(d)}%`];
  }

  function bucketRangeText(i, e) {
    const p = (bp) => `${num(bp)}%`;
    if (i <= 0) return `<${p(e[0])}`;
    if (i >= 4) return `≥${p(e[3])}`;
    return `${p(e[i - 1])}~${p(e[i])}`;
  }

  SS.predictMath = { MINUS, probsFromPick, argmaxPick, confRange, bucketLabels, bucketRangeText };
})();
