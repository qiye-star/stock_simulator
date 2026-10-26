// v2 时钟：调度表（07 §5.2）、skip 目标（07 §6.5）、收盘小结倒计时（08 §4.4）、不可交易文案、server_time 偏差。
export default function (SS, assert, t) {
  const M = SS.clockModel;
  const MS = 5000;
  const DW = { lunch: 5000, close: 15000 };
  const T0 = Date.parse("2026-10-26T10:00:00Z");
  const iso = (ms) => new Date(ms).toISOString();

  t("stepV2：11:30 停留 → 12:59；15:00 停留 → 次日 9:29", () => {
    assert.deepEqual(M.stepV2(690, MS, DW), { kind: "jump", dur: 5000, to: 779, minutes: 89 });
    assert.deepEqual(M.stepV2(900, MS, DW), { kind: "jump", dur: 15000, to: 569, minutes: 1109 });
  });
  t("stepV2：交易分钟之间 tick；12:59→13:00、9:29→9:30 也是 tick", () => {
    assert.deepEqual(M.stepV2(689, MS, DW), { kind: "tick", dur: MS, to: 690, minutes: 1 });
    assert.deepEqual(M.stepV2(779, MS, DW), { kind: "tick", dur: MS, to: 780, minutes: 1 });
    assert.deepEqual(M.stepV2(899, MS, DW), { kind: "tick", dur: MS, to: 900, minutes: 1 });
    assert.deepEqual(M.stepV2(569, MS, DW), { kind: "tick", dur: MS, to: 570, minutes: 1 });
  });
  t("stepV2：非交易分钟立即跳到下一个 12:59 或 9:29", () => {
    assert.deepEqual(M.stepV2(700, MS, DW), { kind: "jump", dur: 0, to: 779, minutes: 79 });
    assert.deepEqual(M.stepV2(100, MS, DW), { kind: "jump", dur: 0, to: 569, minutes: 469 });
  });
  t("msUntilV2：到 9:30 / 12:59 / 13:00 的毫秒数含停留", () => {
    assert.equal(M.msUntilV2(690, 780, MS, DW), 10000);
    assert.equal(M.msUntilV2(900, 570, MS, DW), 20000);
    assert.equal(M.msUntilV2(570, 690, MS, DW), 120 * MS);
    assert.equal(M.msUntilV2(689, 780, MS, DW), 15000);
  });
  t("skipTargetV2：从 9:30 连按 8 次走完一个交易日（07 §6.5）", () => {
    const seq = [570];
    let m = 570;
    for (let i = 0; i < 8; i++) seq.push((m = M.skipTargetV2(m)));
    assert.deepEqual(seq, [570, 689, 690, 779, 780, 899, 900, 569, 570]);
  });
  t("skipTargetV2：收盘后与盘前跳到次日 9:29", () => {
    assert.equal(M.skipTargetV2(1000), 569);
    assert.equal(M.skipTargetV2(0), 569);
  });

  const v2 = (over = {}) => ({ paused: false, tick: 10, trading_day: 11, clock_minute: 900, clock_rules: "v2", phase: "closed", trading: false, ms_per_minute: MS, ...over });

  t("closeTimer：停留中剩余 8 秒 → 进度与文案（到 9:30 为 13 秒）", () => {
    const now = T0;
    const c = v2({ fast_forward_at: iso(now + 8000), next_event: { kind: "open", minute: 570, at: iso(now + 13000) } });
    const r = M.closeTimer(M.normalize(c, { now }), { now, total_ms: 20000 });
    assert.equal(r.paused, false);
    assert.equal(r.remain_ms, 8000);
    assert.equal(r.open_in_ms, 13000);
    assert.equal(r.progress, 0.6);
    assert.equal(r.done, false);
    assert.equal(r.text, "13 秒后进入第 13 个交易日 9:30");
  });
  t("closeTimer：没有 total 时首次进度为 0；剩余为 0 → 正在进入", () => {
    const now = T0;
    const c = v2({ fast_forward_at: iso(now + 8000), next_event: { kind: "open", minute: 570, at: iso(now + 13000) } });
    assert.equal(M.closeTimer(M.normalize(c, { now }), { now }).progress, 0);
    const done = M.closeTimer(M.normalize(v2({ fast_forward_at: iso(now - 1), next_event: { kind: "open", minute: 570, at: iso(now + 4000) } }), { now }), { now, total_ms: 9000 });
    assert.equal(done.done, true);
    assert.equal(done.remain_ms, 0);
    assert.equal(done.text, "正在进入下一交易日…");
  });
  t("closeTimer：暂停 → 已暂停文案，无倒计时", () => {
    const r = M.closeTimer(M.normalize(v2({ paused: true, fast_forward_at: null, next_event: { kind: "open", minute: 570, at: null } }), { now: T0 }), { now: T0 });
    assert.equal(r.paused, true);
    assert.equal(r.remain_ms, null);
    assert.equal(r.text, "已暂停，可继续查看");
  });
  t("closeTimer：缺 fast_forward_at（旧后端）时由 next_event.at 反推", () => {
    const now = T0;
    const r = M.closeTimer(M.normalize(v2({ fast_forward_at: null, next_event: { kind: "open", minute: 570, at: iso(now + 5000 + MS) } }), { now }), { now, total_ms: 10000 });
    assert.equal(r.remain_ms, 5000);
  });
  t("closeTimer：server_time 偏差经 normalize 校正后仍对齐本机倒计时", () => {
    const serverAhead = 3000; // 服务器比本机快 3 秒
    const raw = v2({
      server_time: iso(T0 + serverAhead),
      fast_forward_at: iso(T0 + serverAhead + 8000),
      next_event: { kind: "open", minute: 570, at: iso(T0 + serverAhead + 13000) },
    });
    const c = M.normalize(raw, { now: T0, received_at: T0 });
    const r = M.closeTimer(c, { now: T0 });
    assert.equal(r.remain_ms, 8000);
    assert.equal(r.text, "13 秒后进入第 13 个交易日 9:30");
  });

  t("untradableText：可交易为空串；v2 各时段；v1 沿用旧文案", () => {
    assert.equal(M.untradableText({ rules: "v2", phase: "morning", trading: true }), "");
    assert.equal(M.untradableText({ rules: "v2", phase: "lunch", trading: false }), "11:30–13:00 午休不接单");
    assert.equal(M.untradableText({ rules: "v2", phase: "closed", trading: false }), "15:00 后不接单，次日 9:30 可下单");
    assert.equal(M.untradableText({ rules: "v2", phase: "pre_open", trading: false }), "9:30 开盘前不接单");
    assert.equal(M.untradableText({ rules: "v1", phase: "lunch", trading: false }), "当前不在交易时段");
  });

  t("normalize：v2 午休停留（服务端字段）→ dwell 倒计时，暂停时 at 为 null 且不推算", () => {
    const raw = { paused: false, clock_minute: 690, trading_day: 3, clock_rules: "v2", phase: "lunch", trading: false, ms_per_minute: MS, server_time: iso(T0), next_tick_at: null, fast_forward_at: iso(T0 + 5000), next_event: { kind: "reopen", minute: 780, at: iso(T0 + 10000) } };
    const v = M.view(M.normalize(raw, { now: T0 }), { now: T0 });
    assert.equal(v.state, "dwell");
    assert.equal(v.countdown_ms, 10000);
    assert.equal(v.nextSub, "10 秒后下午开盘");
    const p = M.normalize({ ...raw, paused: true, next_event: { kind: "reopen", minute: 780, at: null }, fast_forward_at: null }, { now: T0 });
    assert.equal(p.next_event.at, null);
    assert.equal(M.view(p, { now: T0 }).state, "paused");
  });
  t("stepV2 与 normalize 的 phase 一致（端点 689/690/779/780/899/900）", () => {
    for (const [m, ph] of [[689, "morning"], [690, "lunch"], [779, "lunch"], [780, "afternoon"], [899, "afternoon"], [900, "closed"]]) {
      assert.equal(M.phaseOf(m, "v2"), ph, String(m));
    }
  });
}
