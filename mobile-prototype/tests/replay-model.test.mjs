/** js/features/replay/model.js + mock.js：阶段推进、题目截止、价格缩放、计分、档位、可见性、下单预览（真实复盘 ⑨） */
export default function (SS, assert, t) {
  const R = SS.replayModel;
  const P = (day, phase) => R.posOf(day, phase);

  t("位置换算：day*4+阶段序，负日（回看期）也可往返", () => {
    assert.equal(P(0, "pre_open"), 0);
    assert.equal(P(2, "open"), 9);
    assert.equal(R.dayOf(P(2, "post_close")), 2);
    assert.equal(R.phaseOf(P(2, "post_close")), "post_close");
    assert.equal(R.phaseOf(-1), "post_close");
    assert.equal(R.dayOf(-1), -1);
    assert.equal(R.phaseOf(P(-3, "close")), "close");
  });

  t("next_phase 依次经过四个阶段，最后一个盘后再推进即结算", () => {
    const seen = [];
    let pos = 0;
    for (let i = 0; i < 3; i++) {
      const r = R.targetPos(pos, "next_phase", 2);
      assert.equal(r.settle, false);
      pos = r.target;
      seen.push(R.phaseOf(pos));
    }
    assert.deepEqual(seen, ["open", "close", "post_close"]);
    assert.equal(pos, R.lastPos(2) - 4); // 第 1 日盘后
    pos = R.targetPos(pos, "next_phase", 2).target; // 第 2 日盘前
    pos = R.targetPos(pos, "next_phase", 2).target; // 第 2 日开盘
    pos = R.targetPos(pos, "next_phase", 2).target; // 第 2 日收盘
    const last = R.targetPos(pos, "next_phase", 2);
    assert.equal(last.target, R.lastPos(2));
    assert.equal(last.settle, false);
    assert.equal(R.targetPos(last.target, "next_phase", 2).settle, true);
  });

  t("next_day 推到下一日盘前；最后一日再推进即结算", () => {
    assert.deepEqual(R.targetPos(P(0, "open"), "next_day", 3), { target: P(1, "pre_open"), settle: false });
    assert.deepEqual(R.targetPos(P(1, "pre_open"), "next_day", 3), { target: P(2, "pre_open"), settle: false });
    assert.equal(R.targetPos(P(2, "close"), "next_day", 3).settle, true);
    assert.equal(R.targetPos(P(2, "post_close"), "next_day", 3).settle, true);
  });

  t("可交易只在开盘与收盘；成交价口径对应", () => {
    assert.deepEqual(["pre_open", "open", "close", "post_close"].map(R.isTradable), [false, true, true, false]);
    assert.equal(R.priceBasis("open"), "open");
    assert.equal(R.priceBasis("close"), "close");
    assert.equal(R.priceBasis("pre_open"), null);
    assert.equal(R.basisText("open"), "开盘价");
    assert.equal(R.blockedText("pre_open"), "盘前不能交易，进入开盘后可下单");
  });

  t("题目截止：next_phase 越过未答题返回 blocked；答了或 skip 则放行", () => {
    const pos = P(1, "pre_open");
    const qs = [{ id: "q1", opens: P(1, "pre_open"), closes: P(1, "pre_open"), resolves: P(5, "close"), answered: false }];
    const tgt = R.targetPos(pos, "next_phase", 8).target;
    assert.deepEqual(R.checkQuestions(qs, pos, tgt, "next_phase", false), { blocked: ["q1"], skip: [], stop: null });
    assert.deepEqual(R.checkQuestions(qs, pos, tgt, "next_phase", true), { blocked: [], skip: ["q1"], stop: null });
    qs[0].answered = true;
    assert.deepEqual(R.checkQuestions(qs, pos, tgt, "next_phase", false), { blocked: [], skip: [], stop: null });
  });

  t("next_day 途中遇到题目开放或截止则停下，reason 与 05 §5.8 一致", () => {
    const qs = [
      { id: "a", opens: P(3, "pre_open"), closes: P(3, "pre_open"), resolves: P(6, "close"), answered: false },
      { id: "b", opens: P(0, "pre_open"), closes: P(1, "pre_open"), resolves: P(5, "close"), answered: false },
    ];
    // 从第 0 日开盘推到第 1 日盘前：题 b 在第 1 日盘前截止且未答 → 停在截止点
    const r = R.checkQuestions(qs, P(0, "open"), P(1, "pre_open"), "next_day", false);
    assert.deepEqual(r.stop, { pos: P(1, "pre_open"), reason: "question_due" });
    // 从第 0 日盘后推到第 3 日盘前：先遇到题 a 开放（第 3 日盘前）
    const r2 = R.checkQuestions([qs[0]], P(0, "post_close"), P(3, "pre_open"), "next_day", false);
    assert.deepEqual(r2.stop, { pos: P(3, "pre_open"), reason: "question_open" });
  });

  t("题目状态：scored > skipped > answered > closed/open", () => {
    assert.equal(R.questionStatus(P(9, "close"), P(1, "pre_open"), { result: { score: 1 } }), "scored");
    assert.equal(R.questionStatus(P(2, "close"), P(1, "pre_open"), { skipped: true }), "skipped");
    assert.equal(R.questionStatus(P(1, "pre_open"), P(1, "pre_open"), { answer: { probs: [20, 20, 20, 20, 20] } }), "answered");
    assert.equal(R.questionStatus(P(2, "pre_open"), P(1, "pre_open"), {}), "closed");
    assert.equal(R.questionStatus(P(1, "pre_open"), P(1, "pre_open"), {}), "open");
  });

  t("价格缩放：前收落入 10–50 元，还原误差不超过 2 分", () => {
    const ppm = R.pickScalePpm(1720, 1248);
    assert.equal(R.scalePrice(1720, ppm), 1248);
    assert.ok(R.inMaskRange(R.scalePrice(3380, R.pickScalePpm(3380, 3960))));
    for (const real of [1, 999, 1234, 56789, 2000000]) {
      const back = R.unscalePrice(R.scalePrice(real, ppm), ppm);
      assert.ok(Math.abs(back - real) <= Math.ceil(1e6 / ppm) + 1, `real=${real} back=${back}`);
    }
    assert.equal(R.inMaskRange(999), false);
    assert.equal(R.inMaskRange(5000), true);
  });

  t("RPS 计分与 B 的示例一致：[7,7,8,70,8] → 98/77/45；[20,80] → 96/36", () => {
    assert.equal(R.rpsScore([7, 7, 8, 70, 8], 3), 98);
    assert.equal(R.rpsScore([7, 7, 8, 70, 8], 4), 77);
    assert.equal(R.rpsScore([7, 7, 8, 70, 8], 0), 45);
    assert.equal(R.rpsScore([20, 80], 1), 96);
    assert.equal(R.rpsScore([20, 80], 0), 36);
  });

  t("NDCG@3 与 B 的示例一致：[A,C,B] → 97，[B,A,X] → 79", () => {
    const rel = { A: 3, B: 2, C: 1, X: 0 };
    assert.equal(R.ndcgScore(["A", "C", "B"], rel, 3), 97);
    assert.equal(R.ndcgScore(["B", "A", "X"], rel, 3), 79);
  });

  t("方向题档位：边界严格递增，最小 ±50bp；档位左闭右开", () => {
    const calm = R.autoEdges(Array(19).fill(0).map((_, i) => (i % 2 ? 3 : -3)), 5);
    assert.ok(calm.every((e, i) => i === 0 || e > calm[i - 1]), JSON.stringify(calm));
    assert.equal(calm[1], -50);
    assert.equal(calm[2], 50);
    const wild = R.autoEdges(Array(19).fill(0).map((_, i) => (i % 2 ? 400 : -400)), 5);
    assert.ok(wild[0] < wild[1] && wild[1] < wild[2] && wild[2] < wild[3]);
    assert.ok(wild[3] > calm[3]);
    const e = [-200, -50, 50, 200];
    assert.equal(R.bucketOf(-201, e), 0);
    assert.equal(R.bucketOf(-200, e), 1); // 左闭
    assert.equal(R.bucketOf(0, e), 2);
    assert.equal(R.bucketOf(200, e), 4);
    const bk = R.bucketsOf(e);
    assert.equal(bk.length, 5);
    assert.equal(bk[1].lo_bp, -200);
    assert.equal(bk[1].hi_bp, -50);
    assert.equal(bk[0].lo_bp, null);
    assert.equal(bk[4].hi_bp, null);
  });

  t("下单预览：买入含费、卖出扣费；可买整手数不超现金", () => {
    assert.deepEqual(R.estimateOrder({ side: "buy", quantity: 300, price_cents: 1000 }), { amount_cents: 300000, fee_cents: 90, total_cents: 300090 });
    assert.deepEqual(R.estimateOrder({ side: "sell", quantity: 100, price_cents: 1000 }), { amount_cents: 100000, fee_cents: 130, total_cents: 99870 });
    const q = R.maxBuyQty(98520 * 100, 1248, 0.0003);
    assert.equal(q % 100, 0);
    assert.ok(q * 1248 * 1.0003 <= 98520 * 100);
    assert.ok((q + 100) * 1248 * 1.0003 > 98520 * 100);
    assert.equal(R.maxBuyQty(100, 1248), 0);
  });

  t("封板：买入在涨停不可成交，卖出在跌停不可成交", () => {
    assert.equal(R.isLocked("buy", 1100, 1100, 900), true);
    assert.equal(R.isLocked("buy", 1099, 1100, 900), false);
    assert.equal(R.isLocked("sell", 900, 1100, 900), true);
    assert.equal(R.isLocked("sell", 901, 1100, 900), false);
  });

  t("假日历：从周一起连续工作日，跳过周末；T 标签", () => {
    assert.equal(R.fakeIso(0 - 0 + 0), R.fakeIso(0));
    assert.equal(new Date(R.fakeIso(0)).getUTCDay() % 6 !== 0, true);
    for (let d = -5; d < 5; d++) {
      const w = new Date(R.fakeIso(d)).getUTCDay();
      assert.ok(w !== 0 && w !== 6, R.fakeIso(d));
    }
    assert.equal(R.tLabel(3), "T+3");
    assert.equal(R.tLabel(-2), "T-2");
  });

  t("下一步按钮文案：盘前→开盘→收盘→盘后→下一天；最后一个盘后→结束并揭晓", () => {
    assert.equal(R.nextActionLabel(P(2, "pre_open"), 8), "进入开盘");
    assert.equal(R.nextActionLabel(P(2, "open"), 8), "进入收盘");
    assert.equal(R.nextActionLabel(P(2, "close"), 8), "进入盘后");
    assert.equal(R.nextActionLabel(P(2, "post_close"), 8), "进入下一天");
    assert.equal(R.nextActionLabel(R.lastPos(8), 8), "结束并揭晓");
    assert.equal(R.posText(P(2, "open"), 8).day, 3);
  });

  const pack = () => SS.mockFeatures.replayPack("stamp-duty-2023");

  t("关卡包确定性：同一 slug 返回同一对象；每只股票前收缩放后落在 10–50 元，方向题边界严格递增", () => {
    const p = pack();
    assert.equal(p, pack());
    for (const s of p.stocks) {
      const prev = R.barAt(p, s.key, -1).c;
      assert.ok(R.inMaskRange(R.scalePrice(prev, s.mask_scale_ppm)), s.key);
    }
    const q1 = p.questions.find((q) => q.id === "q1");
    assert.ok(q1.edges_bp.every((e, i) => i === 0 || e > q1.edges_bp[i - 1]));
    assert.equal(p.calendar.length, p.lookback_days + p.play_days + p.reveal_days);
    assert.equal(p.bars.s1.length, p.calendar.length);
  });

  t("报价口径：盘前=前收、开盘只露开盘价（量 0）、收盘=收盘价；匿名时价格为缩放后的别名", () => {
    const p = pack();
    const pre = R.quoteOf(p, "s1", P(0, "pre_open"), false);
    assert.equal(pre.price_cents, R.barAt(p, "s1", -1).c);
    assert.equal(pre.change_bp, 0);
    const op = R.quoteOf(p, "s1", P(1, "open"), false);
    assert.equal(op.price_cents, R.barAt(p, "s1", 1).o);
    assert.equal(op.high_cents, op.open_cents);
    assert.equal(op.volume, 0);
    const cl = R.quoteOf(p, "s1", P(1, "close"), false);
    assert.equal(cl.price_cents, R.barAt(p, "s1", 1).c);
    assert.equal(cl.change_bp, Math.round(((cl.price_cents - cl.prev_close_cents) * 10000) / cl.prev_close_cents));
    const masked = R.quoteOf(p, "s1", P(0, "pre_open"), true);
    assert.equal(masked.code, "990001");
    assert.equal(masked.name, "股票 A");
    assert.equal(masked.prev_close_cents, 1248);
    assert.equal(R.quoteOf(p, "s1", P(0, "pre_open"), false).code, "600100");
  });

  t("可见性：未来 K 线不可见；今日盘前不可见；开盘只露一根开盘价线", () => {
    const p = pack();
    assert.equal(R.seenBar(p, "s1", 2, P(1, "close")), null);
    assert.equal(R.seenBar(p, "s1", 1, P(1, "pre_open")), null);
    assert.equal(R.seenBar(p, "s1", 0, P(1, "pre_open")).c, R.barAt(p, "s1", 0).c);
    const cs = R.candlesAt(p, "s1", P(1, "open"), true);
    assert.equal(cs[cs.length - 1].trading_day, 1);
    assert.equal(cs[cs.length - 1].close_cents, cs[cs.length - 1].open_cents);
    assert.ok(cs.every((c) => c.date.startsWith("20")) && cs.some((c) => c.date.startsWith("20")));
    assert.equal(R.candlesAt(p, "s1", P(1, "open"), false).length, p.lookback_days + 2);
  });

  t("事件可见性：盘前事件盘前可见，盘中事件收盘后可见；匿名隐藏 hide_in_masked；新的在前", () => {
    const p = pack();
    const at = (pos, masked) => R.eventsAt(p, pos, masked).map((e) => e.event_id);
    assert.ok(at(P(0, "pre_open"), true).includes("e0003"));
    assert.equal(at(P(0, "pre_open"), true).includes("e0005"), false);
    assert.equal(at(P(1, "open"), true).includes("e0005"), false);
    assert.equal(at(P(1, "close"), true).includes("e0005"), true);
    assert.equal(at(P(3, "close"), false).includes("e0007"), false);
    assert.equal(at(P(3, "post_close"), false).includes("e0007"), true);
    assert.equal(at(P(3, "post_close"), true).includes("e0007"), false);
    const ids = at(P(1, "close"), true);
    assert.equal(ids[0], "e0005");
    const feed = R.eventsAt(p, P(0, "pre_open"), true).find((e) => e.event_id === "e0003");
    assert.equal(feed.title, "财税部门：自下一交易日起证券交易印花税减半征收（假数据）");
    assert.equal(feed.date_label, "T+0");
  });

  t("预测题视图：状态、匿名题干、截止日；预测卡适配的候选芯片与答案回写", () => {
    const p = pack();
    const q1 = p.questions.find((q) => q.id === "q1");
    const v = R.questionOf(p, q1, P(1, "pre_open"), {}, true);
    assert.equal(v.status, "open");
    assert.equal(v.prompt, "从昨收到 5 个交易日后收盘，股票 A 的涨跌幅落在哪一档？");
    assert.equal(v.buckets.length, 5);
    assert.deepEqual(v.closes, { day_idx: 1, phase: "pre_open" });
    const vAns = R.questionOf(p, q1, P(1, "pre_open"), { answer: { probs: [10, 20, 40, 20, 10] } }, true);
    assert.equal(vAns.status, "answered");
    assert.deepEqual(vAns.my_answer, { probs: [10, 20, 40, 20, 10] });

    const q2 = p.questions.find((q) => q.id === "q2");
    const v2 = R.questionOf(p, q2, P(3, "pre_open"), { answer: { order: ["s2", "s1", "s3"] } }, true);
    assert.deepEqual(v2.my_answer.order, ["990002", "990001", "990003"]);
    const names = (code) => p.stocks.find((s) => s.alias_code === code).alias_name;
    const card = R.predictionCardOf(v2, "save-1", names);
    assert.equal(card.questions[0].qid, "rank");
    assert.equal(card.questions[0].k, 3);
    assert.equal(card.questions[0].candidates.length, 5);
    assert.deepEqual(card.answers, [{ qid: "rank", order: ["股票 B", "股票 A", "股票 C"] }]);
    const dcard = R.predictionCardOf(vAns, "save-1", names);
    assert.equal(dcard.questions[0].qid, "dir");
    assert.equal(dcard.questions[0].edges_bp.length, 4);
    assert.deepEqual(dcard.answers, [{ qid: "dir", probs: [10, 20, 40, 20, 10] }]);
  });

  t("题目结果：在结算后（scored）显示真实档位与得分；排序题结果按代码映射", () => {
    const p = pack();
    const q1 = p.questions.find((q) => q.id === "q1");
    const v = R.questionOf(p, q1, P(6, "close"), { answer: { probs: [20, 20, 20, 20, 20] }, result: { outcome_bucket: 2, return_bp: 120, score: 80, points: 80 } }, false);
    assert.equal(v.status, "scored");
    assert.equal(v.result.outcome_bucket, 2);
    assert.equal(v.result.points, 80);
    assert.equal(v.codes[0], "600100");
  });

  t("揭示页代码映射：别名与真实代码都能查到真实名称，查不到原样返回", () => {
    const stocks = [
      { code: "990001", real_code: "600001", real_name: "测试甲" },
      { code: "990002", real_code: "300001", real_name: "测试乙" },
    ];
    const nameOf = R.revealNameOf(stocks);
    assert.equal(nameOf("990001"), "测试甲"); // my_answer / stocks[].code（别名）
    assert.equal(nameOf("300001"), "测试乙"); // codes / true_top / returns_bp 的键（真实代码）
    assert.equal(nameOf("000001"), "000001");
    assert.equal(R.revealNameOf(undefined)("990001"), "990001");
  });

  t("canTrade：阶段可交易且未停牌才可下单（停牌任何阶段都不能买卖）", () => {
    assert.equal(R.canTrade("open", { suspended: false }), true);
    assert.equal(R.canTrade("close", undefined), true);
    assert.equal(R.canTrade("open", { suspended: true }), false);
    assert.equal(R.canTrade("pre_open", { suspended: false }), false);
    assert.equal(R.canTrade("post_close", { suspended: false }), false);
  });

  t("卖出置灰原因：停牌 > 阶段不能交易 > 未持有 > T+1，可卖为空串", () => {
    const H = { quantity: 100, sellable_quantity: 0 };
    assert.equal(R.sellBlockedText("open", { suspended: true }, H, 0), "停牌");
    assert.equal(R.sellBlockedText("pre_open", {}, H, 0), "盘前不能卖");
    assert.equal(R.sellBlockedText("post_close", {}, null, 0), "盘后不能卖");
    assert.equal(R.sellBlockedText("close", {}, null, 0), "未持有");
    assert.equal(R.sellBlockedText("close", {}, H, 0), "今日买入，明日可卖");
    assert.equal(R.sellBlockedText("open", {}, { quantity: 100, sellable_quantity: 100 }, 100), "");
  });
}
