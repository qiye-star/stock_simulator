/** js/features/predict/model.js：计分镜像（02 §5 示例）、结算表、为什么这样走、校准几何、tab 过滤 */
export default function (SS, assert, t) {
  const M = SS.predictModel;

  t("RPS 得分与 02 §5.1 示例一致", () => {
    assert.equal(M.rpsScore([7, 7, 8, 70, 8], 3), 98);
    assert.equal(M.rpsScore([7, 7, 8, 70, 8], 4), 77);
    assert.equal(M.rpsScore([7, 7, 8, 70, 8], 0), 45);
    assert.equal(M.rpsScore([20, 80], 1), 96);
    assert.equal(M.rpsScore([20, 80], 0), 36);
  });

  t("均匀分布基准分：K=5 为 70/85/90/85/70，K=2 为 75", () => {
    assert.deepEqual([0, 1, 2, 3, 4].map((o) => M.uniformRpsScore(5, o)), [70, 85, 90, 85, 70]);
    assert.equal(M.uniformRpsScore(2, 0), 75);
    assert.equal(M.uniformRpsScore(2, 1), 75);
  });

  t("基线分：相对瞎猜，+87 / +23 / −36", () => {
    assert.equal(M.baselineScore(98, 85), 87);
    assert.equal(M.baselineScore(77, 70), 23);
    assert.equal(M.baselineScore(45, 70), -36);
    assert.equal(M.baselineScore(70, 100), -30);
    assert.equal(M.baselineScore(100, 100), 0);
  });

  t("NDCG@3：[A,C,B]→97，[B,A,X]→79（真前三 A3 B2 C1）", () => {
    const rel = { A: 3, B: 2, C: 1, X: 0 };
    assert.equal(M.ndcgScore(["A", "C", "B"], rel, 3), 97);
    assert.equal(M.ndcgScore(["B", "A", "X"], rel, 3), 79);
  });

  t("rdiv 半数向外取整", () => {
    assert.equal(M.rdiv(5, 2), 3);
    assert.equal(M.rdiv(-5, 2), -3);
    assert.equal(M.rdiv(4, 3), 1);
  });

  const rankCard = {
    questions: [{ qid: "rank", kind: "rank", k: 3, exclude: "有色", candidates: ["新能源", "新能源汽车", "化工", "电力"], at_day: 48 }],
    answers: [{ qid: "rank", order: ["新能源", "电力", "化工"] }],
    results: [{ qid: "rank", resolved: true, true_top: ["新能源", "新能源汽车", "化工"], candidate_change_bp: { 新能源: -552, 新能源汽车: -288, 化工: 310, 电力: null } }],
  };

  t("settleRows：实际前三在前，用户选了但不在前三的排在后面（实际排名 —）", () => {
    const rows = M.settleRows(rankCard);
    assert.deepEqual(
      rows.map((r) => [r.name, r.actual, r.mine]),
      [["新能源", 1, 1], ["新能源汽车", 2, null], ["化工", 3, 3], ["电力", null, 2]]
    );
    assert.equal(rows[3].change_bp, null);
  });

  t("rankHits：用户前三命中实际前三的个数", () => {
    assert.equal(M.rankHits(["新能源", "电力", "化工"], ["新能源", "新能源汽车", "化工"]), 2);
    assert.equal(M.rankHits(["新能源", "新能源汽车", "化工"], ["化工", "新能源", "新能源汽车"]), 3);
  });

  t("whyBullets：源/下游方向、滞后、传闻被证实，最多 3 条", () => {
    const card = { questions: [] };
    const detail = {
      trading_day: 47,
      rumor_status: "confirmed",
      propagation: [
        { industry: "有色", hop: 0, relation: null, arrived_trading_day: 47, change_bp: 844 },
        { industry: "新能源", hop: 1, relation: "supply", arrived_trading_day: 48, change_bp: -440 },
      ],
    };
    assert.deepEqual(M.whyBullets(card, detail), [
      "有色涨、新能源跌。",
      "上游供给变化对上游是利好，对下游是成本。",
      "新能源晚 1 天才明显跌。",
    ]);
    assert.deepEqual(M.whyBullets(card, null), []);
  });

  t("calibrationPoints：只取 n>0 的档；样本不足 3 档时 ready=false", () => {
    const bins = [
      { lo_pct: 40, hi_pct: 50, n: 3, hits: 1, avg_claimed_pct: 45, hit_rate_pct: 33 },
      { lo_pct: 50, hi_pct: 60, n: 0, hits: 0, avg_claimed_pct: null, hit_rate_pct: null },
      { lo_pct: 70, hi_pct: 80, n: 6, hits: 5, avg_claimed_pct: 74, hit_rate_pct: 83 },
    ];
    const g = M.calibrationPoints(bins, 320, 150);
    assert.equal(g.pts.length, 2);
    assert.equal(g.ready, false);
    const full = M.calibrationPoints(bins.concat([{ lo_pct: 90, hi_pct: 100, n: 1, hits: 1, avg_claimed_pct: 95, hit_rate_pct: 100 }]), 320, 150);
    assert.equal(full.ready, true);
    assert.ok(full.pts[1].r > full.pts[0].r);
  });

  t("errorText：bp → 一位小数百分比", () => {
    assert.equal(M.errorText(630), "6.3%");
    assert.equal(M.errorText(null), "—");
  });

  t("revealDay / tabFilter / countOpen", () => {
    const card = { questions: [{ qid: "dir", from_day: 47, to_day: 49 }, { qid: "rank", at_day: 49 }] };
    assert.equal(M.revealDay(card), 49);
    assert.equal(M.revealDay({ questions: [{ qid: "rumor" }] }), null);
    assert.equal(M.tabFilter("open", { status: "open" }), true);
    assert.equal(M.tabFilter("pending", { status: "answered" }), true);
    assert.equal(M.tabFilter("settled", { status: "expired" }), true);
    assert.equal(M.tabFilter("settled", { status: "answered" }), false);
    assert.equal(M.countOpen([{ status: "open" }, { status: "answered" }, { status: "open" }]), 2);
  });

  t("shortTitle 取前 8 字；targetLabel / windowDays", () => {
    assert.equal(M.shortTitle("华中某锂矿区因环保督察全面停产整改"), "华中某锂矿区因环…");
    assert.equal(M.shortTitle("央行降准"), "央行降准");
    assert.equal(M.targetLabel({ target_kind: "industry", target_name: "有色" }), "有色板块");
    assert.equal(M.targetLabel({ target_kind: "market" }), "全市场");
    assert.equal(M.windowDays({ from_day: 47, to_day: 49 }), 3);
  });

  t("leadSplit：第一个句号前为引导句；无正文或无句号返回 null", () => {
    assert.deepEqual(M.leadSplit("有色涨、下游跌。上游减产对上游是利好。"), { lead: "有色涨、下游跌。", rest: "上游减产对上游是利好。" });
    assert.equal(M.leadSplit("传闻被辟谣。"), null);
    assert.equal(M.leadSplit("没有句号的一句"), null);
    assert.equal(M.leadSplit(""), null);
  });
}
