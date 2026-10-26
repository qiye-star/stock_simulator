/** js/features/pm/model.js：LMSR 报价（与 04 §4.4 金值一致）、限额与滑点、展示文案、曲线、推送合并；mock 成交的余额与持仓守恒 */
export default function (SS, assert, t) {
  const P = SS.pmModel;
  const B_S1000 = 6213; // 04 §4.4：S=1000，5 档均匀先验
  const UNI = [0, 0, 0, 0, 0];

  t("buyPoints 与 04 §4.4 金值（S=1000 分档，买 1/5/10 份 → 22/138/366）", () => {
    assert.equal(P.buyPoints(UNI, B_S1000, 0, 1), 22);
    assert.equal(P.buyPoints(UNI, B_S1000, 0, 5), 138);
    assert.equal(P.buyPoints(UNI, B_S1000, 0, 10), 366);
  });

  t("传闻 S=1000（b=8305，先验 0.3/0.7）买辟谣 5/10/20 份 → 185/442/1161", () => {
    const q = [0, 7]; // 服务端整数先验 q0（04 §4.4）
    assert.equal(P.buyPoints(q, 8305, 0, 5), 185);
    assert.equal(P.buyPoints(q, 8305, 0, 10), 442);
    assert.equal(P.buyPoints(q, 8305, 0, 20), 1161);
  });

  t("往返：买第 2 档 7 份花 217，立即卖回得 216（不套利）", () => {
    const buy = P.buyPoints(UNI, B_S1000, 1, 7);
    const q1 = UNI.map((x, i) => (i === 1 ? x + 7 : x));
    const sell = P.sellPoints(q1, B_S1000, 1, 7);
    assert.equal(buy, 217);
    assert.equal(sell, 216);
    assert.ok(sell <= buy);
  });

  t("概率和恰为 1e6，买入后该档上升、其余不升", () => {
    const q = [1.2, -0.4, 0.3, 2.5, -3];
    const before = P.pricesPpm(q, 12426);
    assert.equal(before.reduce((a, c) => a + c, 0), 1000000);
    const after = P.pricesPpm(q.map((x, i) => (i === 3 ? x + 2 : x)), 12426);
    assert.equal(after.reduce((a, c) => a + c, 0), 1000000);
    assert.ok(after[3] > before[3]);
    for (let i = 0; i < 5; i++) if (i !== 3) assert.ok(after[i] <= before[i]);
  });

  t("拆单不更便宜：buy(a+b) ≤ buy(a) + buy(b 在 a 之后)", () => {
    const a = 4;
    const b = 6;
    const whole = P.buyPoints(UNI, B_S1000, 2, a + b);
    const first = P.buyPoints(UNI, B_S1000, 2, a);
    const q1 = UNI.map((x, i) => (i === 2 ? x + a : x));
    const second = P.buyPoints(q1, B_S1000, 2, b);
    assert.ok(whole <= first + second + 1);
  });

  t("maxSharesForBudget：花费 ≤ 预算 < 再多一份的花费（或达到 cap）", () => {
    for (const budget of [1, 50, 194, 500, 2000]) {
      const n = P.maxSharesForBudget(UNI, B_S1000, 4, budget, 200);
      if (n > 0) assert.ok(P.buyPoints(UNI, B_S1000, 4, n) <= budget);
      if (n < 200) assert.ok(P.buyPoints(UNI, B_S1000, 4, n + 1) > budget);
    }
    assert.equal(P.maxSharesForBudget(UNI, B_S1000, 4, 10 ** 9, 30), 30);
  });

  t("quoteOf：avg_price_ppm = 花费·10000/份额，回款与花费同形", () => {
    const q = P.quoteOf(UNI, B_S1000, "buy", 0, 5);
    assert.equal(q.points, 138);
    assert.equal(q.avg_price_ppm, Math.round((138 * 10000) / 5));
    assert.equal(q.price_before_ppm, 200000);
    assert.equal(q.prices_after_ppm.length, 5);
  });

  t("滑点保护：买入 ceil(报价·1.02)，卖出 floor(报价·0.98)", () => {
    assert.equal(P.slippageLimit(194, "buy"), 198);
    assert.equal(P.slippageLimit(100, "buy"), 102);
    assert.equal(P.slippageLimit(100, "sell"), 98);
    assert.equal(P.slippageLimit(0, "sell"), 0);
  });

  t("单市场净投入上限 max(200, S//4)", () => {
    assert.equal(P.netCostCap(1000), 250);
    assert.equal(P.netCostCap(2000), 500);
    assert.equal(P.netCostCap(100), 200);
  });

  t("formatProb：1 位小数；<0.1% 与空值", () => {
    assert.equal(P.formatProb(620000), "62.0%");
    assert.equal(P.formatProb(40000), "4.0%");
    assert.equal(P.formatProb(50), "<0.1%");
    assert.equal(P.formatProb(0), "0.0%");
    assert.equal(P.formatProb(null), "—");
  });

  t("文案：bucket 分档与问句、rumor 固定选项序（deny, confirm）", () => {
    const m = { kind: "bucket", question: { scope: "industry", industry: "有色", from_day: 3, to_day: 5, edges_bp: [-320, -110, 110, 320] } };
    assert.equal(P.outcomeLabels(m).length, 5);
    assert.equal(P.questionText(m), "有色板块 3 个交易日后累计涨跌幅落在哪一档？");
    assert.equal(P.closeText({ ...m, status: "open" }), "第 6 个交易日开盘前停止交易");
    const r = { kind: "rumor", event: { title: "锂矿区“一周内复产”传闻" }, status: "open" };
    assert.deepEqual(P.outcomeLabels(r), ["会被辟谣", "会被证实"]);
    assert.equal(P.questionText(r), "锂矿区“一周内复产”传闻——会被辟谣吗？");
    assert.equal(P.closeText(r), "揭晓前停止交易");
    assert.equal(P.statusText("closed"), "待结算");
  });

  t("leadingIndex：并列取小下标", () => {
    assert.equal(P.leadingIndex([10, 62, 62, 5]), 1);
    assert.equal(P.leadingIndex([620000, 40000]), 0);
  });

  t("curvePaths：空数组为空串；有点时 path 以 M 开头，末点落在 x=W", () => {
    assert.deepEqual(P.curvePaths([]), { line: "", area: "", last: null });
    const c = P.curvePaths([0.2, 0.4, 0.62], 320, 90, 6);
    assert.ok(c.line.startsWith("M0.0 "));
    assert.equal(c.last.x, 320);
    assert.ok(c.area.endsWith("Z"));
    assert.ok(c.last.y < P.curvePaths([0.2], 320, 90, 6).last.y);
  });

  t("applyTick：只接受更新的 seq，返回新对象且不改入参", () => {
    const m = { id: "m", status: "open", trade_seq: 5, volume_shares: 10, outcomes: [{ idx: 0, price_ppm: 400000 }, { idx: 1, price_ppm: 600000 }] };
    const stale = P.applyTick(m, { id: "m", seq: 4, prices_ppm: [900000, 100000] });
    assert.equal(stale, m);
    const next = P.applyTick(m, { id: "m", seq: 6, prices_ppm: [500000, 500000], volume_shares: 12 });
    assert.notEqual(next, m);
    assert.equal(next.trade_seq, 6);
    assert.equal(next.outcomes[0].price_ppm, 500000);
    assert.equal(m.outcomes[0].price_ppm, 400000);
    assert.equal(P.applyTick(m, { id: "other", seq: 9, prices_ppm: [1, 2] }), m);
  });

  t("holdingValue：Σ shares·price·100/1e6 四舍五入", () => {
    assert.equal(P.holdingValue([8, 0], [1000000, 0]), 800);
    assert.equal(P.holdingValue([2], [620000]), 124);
  });

  // ---------- mock 成交（余额与持仓守恒）----------
  SS.ApiError = SS.ApiError || class ApiError extends Error {
    constructor(code, status = 0, params = {}) {
      super(code);
      this.code = code;
      this.status = status;
      this.params = params;
    }
  };
  const M = () => SS.mockFeatures.pm;
  const OPEN = "3f7a1c2e-0000-4000-8000-00000000d001";
  const RESOLVED = "3f7a1c2e-0000-4000-8000-00000000d003";

  t("mock 详情：my 与 limits 形状齐全，已结算的 pnl 与 04 一致（+84）", () => {
    const d = M().detail(OPEN);
    assert.equal(d.kind, "bucket");
    assert.equal(d.outcomes.length, 5);
    assert.equal(P.positionOf(d.my, 4).shares, 2);
    assert.equal(d.my.outcomes.length, 1, "持仓列表是稀疏的（只列持有过的选项）");
    assert.equal(d.my.outcomes[0].idx, 4);
    assert.equal(d.my.net_cost_points, 98);
    const r = M().detail(RESOLVED);
    assert.equal(r.my.pnl_points, 84);
    assert.equal(r.winning_outcome, 0);
  });

  t("mock 报价 → 买入：余额减少等于成交花费，持仓份额与成本同步", () => {
    const before = M().detail(OPEN);
    const q = M().quote(OPEN, { side: "buy", outcome: 1, shares: 3 });
    const res = M().trade(OPEN, { side: "buy", outcome: 1, shares: 3, max_cost_points: P.slippageLimit(q.points, "buy") });
    assert.equal(res.trade.points, q.points);
    assert.equal(res.balance_points, before.balance_points - q.points);
    assert.equal(P.positionOf(res.my, 1).shares, 3);
    assert.equal(res.my.bought_points, 98 + q.points);
  });

  t("mock 卖出：回款入账，份额不足与滑点按 04 §9.3 抛错", () => {
    const d = M().detail(OPEN);
    assert.throws(() => M().trade(OPEN, { side: "sell", outcome: 0, shares: 1 }), (e) => e.code === "PM_INSUFFICIENT_SHARES");
    assert.throws(() => M().trade(OPEN, { side: "buy", outcome: 0, shares: 1, max_cost_points: 0 }), (e) => e.code === "PM_SLIPPAGE_EXCEEDED");
    const sold = M().trade(OPEN, { side: "sell", outcome: 4, shares: 1, min_proceeds_points: 0 });
    assert.equal(sold.balance_points, d.balance_points + sold.trade.points);
    assert.equal(P.positionOf(sold.my, 4).shares, 1);
  });

  t("mock：已结算市场报价与成交返回 PM_NOT_OPEN；余额不足返回 POINTS_INSUFFICIENT", () => {
    assert.throws(() => M().quote(RESOLVED, { side: "buy", outcome: 0, shares: 1 }), (e) => e.code === "PM_NOT_OPEN");
    assert.throws(() => M().trade(OPEN, { side: "buy", outcome: 0, shares: 200 }), (e) => e.code === "POINTS_INSUFFICIENT" || e.code === "PM_POSITION_LIMIT");
  });

  t("mock 列表与结算记录：今日挑战含 3 个市场，记录按时间降序", () => {
    const page = M().list({ status: "all" });
    assert.equal(page.items.length, 3);
    const s = M().settlements().items;
    assert.ok(s.length >= 2);
    assert.ok(s[0].created_at >= s[1].created_at);
  });

  t("positionOf 按 idx 取值（稀疏列表）；无记录返回 0", () => {
    const my = { outcomes: [{ idx: 1, shares: 1, cost_points: 72, value_points: 72 }], bought_points: 72 };
    assert.equal(P.positionOf(my, 1).shares, 1);
    assert.equal(P.positionOf(my, 1).cost_points, 72);
    assert.equal(P.positionOf(my, 0).shares, 0);
    assert.equal(P.positionOf(null, 3).shares, 0);
    assert.equal(P.positionOf({ outcomes: [] }, 2).cost_points, 0);
  });

  t("emptyText：今日一个市场都没有 → 开赛前文案；有市场但都已结束 → 已结束文案", () => {
    assert.equal(P.emptyText([]), "今日挑战开始后开市");
    assert.equal(P.emptyText(null), "今日挑战开始后开市");
    assert.equal(P.emptyText([{ status: "resolved" }]), "今日市场已结束，暂无进行中的合约");
  });
}
