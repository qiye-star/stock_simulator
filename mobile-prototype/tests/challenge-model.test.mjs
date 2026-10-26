/** js/features/challenge/model.js：倒计时与阶段推导、回合条、主按钮状态机、排行行、计分展示、承诺解析；并校验 mock 的承诺哈希 */
import crypto from "node:crypto";

export default function (SS, assert, t) {
  const M = SS.challengeModel;
  const T0 = Date.parse("2026-10-26T01:30:00Z"); // 北京时间 09:30
  const at = (ms) => new Date(ms).toISOString();

  t("formatDuration：分:秒 / 时:分:秒 / 天", () => {
    assert.equal(M.formatDuration(0), "0:00");
    assert.equal(M.formatDuration(59_000), "0:59");
    assert.equal(M.formatDuration(4 * 60_000 + 59_000), "4:59");
    assert.equal(M.formatDuration((2 * 3600 + 14 * 60 + 5) * 1000), "2:14:05");
    assert.equal(M.formatDuration(26 * 3600_000), "1 天 2:00:00");
    assert.equal(M.formatDuration(-5000), "0:00", "负数按 0");
  });

  t("skewOf：server_time − 本机时间；非法为 0", () => {
    assert.equal(M.skewOf(at(T0 + 5000), T0), 5000);
    assert.equal(M.skewOf("not-a-date", T0), 0);
    assert.equal(M.skewOf(undefined, T0), 0);
  });

  t("countdown：经 skew 换算到服务端时刻；已到 done；缺目标返回 null", () => {
    const c1 = M.countdown(at(T0 + 60_000), 0, T0);
    assert.equal(c1.ms, 60_000);
    assert.equal(c1.text, "1:00");
    assert.equal(c1.done, false);
    // 本机比服务端慢 30 秒（skew=+30000）：服务端此刻是 T0+30s，目标 T0+60s 还剩 30 秒
    assert.equal(M.countdown(at(T0 + 60_000), 30_000, T0).ms, 30_000);
    // 目标已过
    const c2 = M.countdown(at(T0 + 10_000), 0, T0 + 20_000);
    assert.equal(c2.done, true);
    assert.equal(c2.ms, 0);
    assert.equal(c2.text, "0:00");
    assert.equal(M.countdown(null, 0, T0).ms, null);
  });

  t("clockText / ymdText：北京时间 HH:mm 与 “M 月 D 日”", () => {
    assert.equal(M.clockText("2026-10-26T01:30:00Z"), "09:30");
    assert.equal(M.clockText("2026-10-25T16:05:00Z"), "00:05", "UTC 16:05 即北京次日 00:05");
    assert.equal(M.ymdText("2026-10-25"), "10 月 25 日");
    assert.equal(M.ymdText("bad"), "");
  });

  t("roundBar：缺失回合为 pending；状态映射到 is-done / is-live / is-pending", () => {
    const bar = M.roundBar([{ round_index: 1, state: "resolved" }, { round_index: 2, state: "open" }], 4);
    assert.deepEqual(bar.map((s) => s.cls), ["is-done", "is-live", "is-pending", "is-pending"]);
    assert.deepEqual(M.roundBar([{ round_index: 3, state: "burst" }], 4).map((s) => s.cls), ["is-pending", "is-pending", "is-live", "is-pending"]);
    assert.equal(M.roundBar([{ round_index: 1, state: "closed" }]).length, 4, "默认 4 段");
  });

  const rounds = [
    { round_index: 1, state: "resolved", closes_at: at(T0 - 3600_000) },
    { round_index: 2, state: "open", closes_at: at(T0 + 2 * 3600_000 + 14 * 60_000) },
    { round_index: 3, state: "pending", closes_at: at(T0 + 4 * 3600_000) },
    { round_index: 4, state: "pending", closes_at: at(T0 + 6 * 3600_000) },
  ];
  const running = {
    id: "c1", status: "running", phase: "hold", round_index: 2, rounds_total: 4, challenge_date: "2026-10-26",
    next_change_at: at(T0 + 2 * 3600_000 + 14 * 60_000 + 5000), server_time: at(T0), rounds, my_entry: null,
    entry_closes_at: at(T0 + 4 * 3600_000), starts_at: at(T0 - 3 * 3600_000),
  };

  t("timeline：hold 阶段的文案、回合、下一时刻与本轮截止倒计时", () => {
    const tl = M.timeline(running, 0, T0);
    assert.equal(tl.phaseText, "行情已暂停");
    assert.equal(tl.roundText, "第 2 轮 / 4");
    assert.equal(tl.nextLabel, "距行情继续");
    assert.equal(tl.next.text, "2:14:05");
    assert.equal(tl.closes.text, "2:14:00");
    assert.deepEqual(tl.bar.map((s) => s.cls), ["is-done", "is-live", "is-pending", "is-pending"]);
  });

  t("timeline：burst 阶段的下一时刻是本轮停顿；无 open 回合则没有截止倒计时", () => {
    const tl = M.timeline({ ...running, phase: "burst", next_change_at: at(T0 + 90_000) }, 0, T0);
    assert.equal(tl.phaseText, "快放中");
    assert.equal(tl.nextLabel, "距本轮停顿");
    assert.equal(tl.next.text, "1:30");
    const tl2 = M.timeline({ ...running, rounds: [{ round_index: 2, state: "resolved", closes_at: at(T0) }] }, 0, T0);
    assert.equal(tl2.closes, null);
  });

  t("timeline：未开赛倒计时到 starts_at", () => {
    const tl = M.timeline({ ...running, status: "scheduled", phase: "before", round_index: null, starts_at: at(T0 + 90_000) }, 0, T0);
    assert.equal(tl.nextLabel, "距开赛");
    assert.equal(tl.next.text, "1:30");
    assert.equal(tl.closes, null);
  });

  t("timeline：已结算 / 已作废没有倒计时", () => {
    const s = M.timeline({ ...running, status: "settled", phase: "ended", next_change_at: null, round_index: null }, 0, T0);
    assert.equal(s.phaseText, "已结算");
    assert.equal(s.nextLabel, "");
    assert.equal(s.next.ms, null);
    assert.equal(M.timeline({ ...running, status: "void" }, 0, T0).phaseText, "已作废");
  });

  t("primaryAction：scheduled 禁用并显示开赛时刻", () => {
    const a = M.primaryAction({ ...running, status: "scheduled", starts_at: at(T0 + 3600_000) }, { now: T0, skew: 0 });
    assert.equal(a.kind, "disabled");
    assert.equal(a.label, "10:30 开赛");
  });

  t("primaryAction：未参加且未截止报名 → 参加；截止后 → 已停止报名", () => {
    assert.deepEqual(M.primaryAction(running, { now: T0, skew: 0 }), { label: "参加挑战", kind: "enter" });
    const late = M.primaryAction(running, { now: T0 + 5 * 3600_000, skew: 0 });
    assert.equal(late.label, "已停止报名");
    assert.equal(late.kind, "disabled");
  });

  t("primaryAction：已参加、当前回合 open 且未答 → 进入第 k 轮；已答 → 去交易", () => {
    const entered = { ...running, my_entry: { answered_rounds: 1 } };
    assert.deepEqual(M.primaryAction(entered, { now: T0, skew: 0, cards: [] }), { label: "进入第 2 轮", kind: "nav", to: "/challenge" });
    const answered = [{ round_index: 2, my_answers: [{ qid: "dir" }] }];
    assert.deepEqual(M.primaryAction(entered, { now: T0, skew: 0, cards: answered }), { label: "去交易", kind: "nav", to: "/market" });
  });

  t("primaryAction：结算后 → 查看复盘；未生成 → kind none；作废 → 禁用", () => {
    assert.deepEqual(M.primaryAction({ ...running, status: "settled", id: "X" }, {}), { label: "查看复盘", kind: "nav", to: "/challenge/X/review" });
    assert.equal(M.primaryAction(null).kind, "none");
    assert.equal(M.primaryAction({ ...running, status: "void" }, {}).kind, "disabled");
  });

  t("signed / pctText：带符号整数与基点百分比，0 为中性", () => {
    assert.equal(M.signed(41), "+41");
    assert.equal(M.signed(-3), "-3");
    assert.equal(M.signed(0), "0");
    assert.equal(M.signed(null), "—");
    assert.equal(M.pctText(310), "+3.10%");
    assert.equal(M.pctText(-120), "-1.20%");
    assert.equal(M.toneOf(0), "");
    assert.equal(M.toneOf(5), "up");
  });

  const rows = [
    { rank: 1, username: "锂电老韭菜", equipped_title: "chain_reader", total_score: 96, forecast_score: 52, trade_score: 44, return_bp: 680, days_played: null, is_me: false },
    { rank: 4, username: "小鹿炒股", equipped_title: null, total_score: 80, forecast_score: 30, trade_score: 50, return_bp: -120, days_played: 3, is_me: false },
    { rank: null, username: "新人", equipped_title: null, total_score: 0, forecast_score: 0, trade_score: 0, return_bp: 0, days_played: null, is_me: true },
  ];

  t("boardRows：日榜第三列随 board，收益率带涨跌色；名次 null 显示 —；我的行标记", () => {
    const total = M.boardRows(rows, "day", "total");
    assert.equal(total[0].c3, "+96");
    assert.equal(total[0].c4, "+6.80%");
    assert.equal(total[0].c4Tone, "up");
    assert.equal(total[1].c4Tone, "down");
    assert.equal(M.boardRows(rows, "day", "forecast")[0].c3, "+52");
    assert.equal(M.boardRows(rows, "day", "trade")[1].c3, "+50");
    assert.equal(total[2].rankText, "—");
    assert.equal(total[2].isMe, true);
    assert.equal(total[0].title, "chain_reader");
  });

  t("boardRows：周榜与总榜第三、四列为总分 / 参赛天数，不带收益色", () => {
    const w = M.boardRows(rows, "week", "total");
    assert.equal(w[1].c3, "+80");
    assert.equal(w[1].c4, "3");
    assert.equal(w[0].c4, "—", "缺参赛天数显示 —");
    assert.equal(w[1].c4Tone, "");
    assert.deepEqual(M.boardHeaders("week", "total"), { c3: "总分", c4: "参赛天数" });
    assert.deepEqual(M.boardHeaders("day", "forecast"), { c3: "预测分", c4: "仓位收益" });
  });

  t("resultStats：名次、积分与交易收益；无成绩为 null", () => {
    assert.equal(M.resultStats(null), null);
    const s = M.resultStats({ total_score: 57, forecast_score: 41, return_bp: 312, rank: 37, eligible_count: 402, points_awarded: 60 });
    assert.equal(s.total, "+57");
    assert.equal(s.trade, "+3.12%");
    assert.equal(s.tradeTone, "up");
    assert.equal(s.rank, "第 37 名 / 402 人");
    assert.equal(s.points, "+60");
    const z = M.resultStats({ total_score: 0, forecast_score: 0, return_bp: -50, rank: null, eligible_count: 5, points_awarded: 0 });
    assert.equal(z.rank, "未入榜");
    assert.equal(z.points, "0");
    assert.equal(z.tradeTone, "down");
  });

  const dirQ = { qid: "dir", kind: "bucket", edges_bp: [-240, -80, 80, 240] };
  const rankQ = { qid: "rank", kind: "rank", k: 3, exclude: "有色", candidates: ["新能源", "电力", "化工"] };
  const card = {
    questions: [rankQ, dirQ],
    my_answers: [{ qid: "dir", probs: [7, 8, 10, 65, 10] }, { qid: "rank", order: ["新能源", "电力", "化工"] }],
    results: [
      { qid: "dir", resolved: true, outcome_bucket: 3, change_bp: 412, score: 81 },
      { qid: "rank", resolved: true, true_top: ["新能源", "化工"], score: 92 },
    ],
  };

  t("answerLines：按题型排序（dir 在前）；把握取所选档的概率；无答案为未作答", () => {
    const lines = M.answerLines(card);
    assert.equal(lines[0].qid, "dir");
    const label = SS.predictMath.bucketLabels(dirQ.edges_bp)[3];
    assert.equal(lines[0].text, `${label} · 把握 65%`);
    assert.equal(lines[1].text, "新能源、电力、化工");
    assert.equal(M.answerLines({ questions: [dirQ], my_answers: [] })[0].text, "未作答");
  });

  t("resultLines：已判定给出实际结果与得分；未判定为等待判定", () => {
    const lines = M.resultLines(card);
    assert.equal(lines[0].resolved, true);
    assert.equal(lines[0].score, 81);
    assert.ok(lines[0].text.includes("+4.12%"), lines[0].text);
    assert.equal(lines[1].text, "实际前三：新能源、化工");
    const open = M.resultLines({ questions: [dirQ], results: [] });
    assert.equal(open[0].resolved, false);
    assert.equal(open[0].text, "等待判定");
    assert.equal(open[0].score, null);
  });

  t("crowdText：取全服均值最大的档；无数据为 null；usedText 文案", () => {
    const c = { questions: [dirQ], crowd: { by_qid: { dir: { mean_probs: [9, 14, 31, 33, 13] } } } };
    const label = SS.predictMath.bucketLabels(dirQ.edges_bp)[3];
    assert.equal(M.crowdText(c), `全服均值最可能 ${label} · 33%`);
    assert.equal(M.crowdText({ questions: [dirQ] }), null);
    assert.equal(M.usedText("peer"), "同伴分");
    assert.equal(M.usedText("baseline"), "基线分（参与人数不足）");
    assert.equal(M.usedText(null), "");
  });

  t("shortHash：64 位 hex 显示前 8 与后 8；短串原样", () => {
    const hex = "3f9a1c07aa00bb11cc22dd33ee44ff5566778899aabbccddeeff00112233be52";
    assert.equal(M.shortHash(hex), "3f9a1c07…2233be52");
    assert.equal(M.shortHash("abc"), "abc");
    assert.equal(M.shortHash(null), "");
  });

  const input = "stocksim-challenge|v1|2026-10-25|ruleset=2|clock=2|seed=3482910573829104657|salt=5c1e8a7f2b9d4036e1f0a2c3d4b5e6f7";

  t("parseCommitmentInput：按 03 §1.4 的格式拆字段；格式不对返回 null", () => {
    assert.deepEqual(M.parseCommitmentInput(input), {
      date: "2026-10-25", ruleset: "2", clock: "2", seed: "3482910573829104657", salt: "5c1e8a7f2b9d4036e1f0a2c3d4b5e6f7",
    });
    assert.equal(M.parseCommitmentInput("stocksim-challenge|v1|2026-10-25|ruleset=2"), null);
    assert.equal(M.parseCommitmentInput("other|v1|x"), null);
    assert.equal(M.commitmentInputOf({ commitment_input: "nope" }), null);
  });

  t("digestMatches：忽略大小写与首尾空白；缺失为 false；种子与承诺原文一致性", () => {
    const hex = crypto.createHash("sha256").update(input).digest("hex");
    assert.equal(M.digestMatches(hex, hex.toUpperCase()), true);
    assert.equal(M.digestMatches(hex, `  ${hex}\n`), true);
    assert.equal(M.digestMatches(hex, "0".repeat(64)), false);
    assert.equal(M.digestMatches(hex, null), false);
    assert.equal(M.seedMatches({ commitment_input: input, market_seed: "3482910573829104657" }), true);
    assert.equal(M.seedMatches({ commitment_input: input, market_seed: "1" }), false);
  });

  t("mock 的承诺哈希与承诺原文一致（sha256 由 node:crypto 独立计算）", () => {
    const mk = SS.mockFeatures.challenge;
    const rv = mk.reveal(mk.DAY_ID);
    const hex = crypto.createHash("sha256").update(rv.commitment_input).digest("hex");
    assert.equal(hex, rv.seed_commitment);
    assert.equal(M.digestMatches(hex, rv.seed_commitment) && M.seedMatches(rv), true);
    assert.equal(mk.view(mk.DAY_ID).seed_commitment, rv.seed_commitment, "ChallengeOut 与 reveal 的承诺一致");
    const todayRv = mk.view(mk.TODAY_ID).seed_commitment;
    assert.equal(todayRv.length, 64);
  });

  t("timeline：burst 期 next_change_at 为 null → 大字“快放中”、副文案不给倒计时（停顿时刻保密）", () => {
    const tl = M.timeline({ ...running, phase: "burst", next_change_at: null }, 0, T0);
    assert.equal(tl.fast, true);
    assert.equal(tl.next.ms, null);
    assert.equal(tl.nextLabel, "");
    assert.equal(tl.big, "快放中");
    assert.equal(tl.hint, "停顿时间保密");
    assert.equal(tl.phaseText, "快放中");
  });

  t("timeline：final 期 next 为 null → 结算时刻只给 settle_expected_at 的上界", () => {
    // settle_expected_at 为北京 23:10（UTC 15:10）：只说“最迟”，不倒计时
    const tl = M.timeline({ ...running, phase: "final", next_change_at: null, settle_expected_at: "2026-10-26T15:10:00Z" }, 0, T0);
    assert.equal(tl.fast, true);
    assert.equal(tl.big, "最后一段");
    assert.equal(tl.hint, "最迟 23:10 结算");
  });

  t("timeline：hold 有 next_change_at 时仍是倒计时（fast=false），大字与副文案同源", () => {
    const tl = M.timeline(running, 0, T0);
    assert.equal(tl.fast, false);
    assert.equal(tl.big, "2:14:05");
    assert.equal(tl.hint, "距行情继续 2:14:05");
  });

  t("timeline：已结算 / 未开赛的大字与副文案", () => {
    const done = M.timeline({ ...running, status: "settled", phase: "ended", round_index: null, next_change_at: null }, 0, T0);
    assert.equal(done.big, "已结算");
    assert.equal(done.hint, "");
    assert.equal(done.fast, false);
    const pre = M.timeline({ ...running, status: "scheduled", phase: "before", round_index: null, next_change_at: null, starts_at: at(T0 + 61_000) }, 0, T0);
    assert.equal(pre.big, "1:01");
    assert.equal(pre.hint, "距开赛 1:01");
  });

  t("refreshDue：到点节流 3 秒；快放段（fast）节流 5 秒轮询；其它不拉", () => {
    const hold = M.timeline(running, 0, T0);
    assert.equal(M.refreshDue(hold, T0, T0 + 1000), false);
    const due = M.timeline(running, 0, T0 + 2 * 3600_000 + 14 * 60_000 + 5_000);
    assert.equal(due.next.done, true);
    assert.equal(M.refreshDue(due, T0 - 10_000, T0 + 2 * 3600_000 + 14 * 60_000 + 5_000), true);
    const nowDue = T0 + 2 * 3600_000 + 14 * 60_000 + 5_000;
    assert.equal(M.refreshDue(due, nowDue - 1000, nowDue), false, "3 秒内不重复拉");
    const fast = M.timeline({ ...running, phase: "burst", next_change_at: null }, 0, T0);
    assert.equal(M.refreshDue(fast, T0 - 4000, T0), false);
    assert.equal(M.refreshDue(fast, T0 - 6000, T0), true);
    assert.equal(M.refreshDue(null, 0, T0), false);
  });
}
