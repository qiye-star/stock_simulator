// SS.clockModel 纯函数测试。默认导出 (SS, assert, t)：t(name, fn) 注册用例。
export default function (SS, assert, t) {
  const M = SS.clockModel;
  const T0 = Date.parse("2026-10-26T10:00:00Z");
  const iso = (ms) => new Date(ms).toISOString();
  const v1 = (minute, extra = {}) => ({ paused: false, tick: 100, trading_day: 11, clock_minute: minute, session: "trading", ...extra });
  const norm = (raw, o = {}) => M.normalize(raw, { now: T0, refresh_rate_ms: 3000, ...o });

  t("phaseOf：v1 闭区间端点", () => {
    const e = { 569: "pre_open", 570: "morning", 689: "morning", 690: "morning", 691: "lunch", 779: "lunch", 780: "afternoon", 899: "afternoon", 900: "afternoon", 901: "closed" };
    for (const [m, p] of Object.entries(e)) assert.equal(M.phaseOf(+m, "v1"), p, `v1 ${m}`);
  });
  t("phaseOf：v2 半开区间端点", () => {
    const e = { 569: "pre_open", 570: "morning", 689: "morning", 690: "lunch", 691: "lunch", 779: "lunch", 780: "afternoon", 899: "afternoon", 900: "closed", 901: "closed" };
    for (const [m, p] of Object.entries(e)) assert.equal(M.phaseOf(+m, "v2"), p, `v2 ${m}`);
  });
  t("tradingOf：v1 在 11:30/15:00 仍可交易，v2 不可", () => {
    assert.equal(M.tradingOf(690, "v1"), true);
    assert.equal(M.tradingOf(900, "v1"), true);
    assert.equal(M.tradingOf(690, "v2"), false);
    assert.equal(M.tradingOf(900, "v2"), false);
    assert.equal(M.tradingOf(785, "v2"), true);
  });
  t("nextEventOf", () => {
    assert.deepEqual(M.nextEventOf("pre_open"), { kind: "open", minute: 570 });
    assert.deepEqual(M.nextEventOf("morning"), { kind: "lunch", minute: 690 });
    assert.deepEqual(M.nextEventOf("lunch"), { kind: "reopen", minute: 780 });
    assert.deepEqual(M.nextEventOf("afternoon"), { kind: "close", minute: 900 });
    assert.deepEqual(M.nextEventOf("closed"), { kind: "open", minute: 570 });
  });
  t("gap 跨日取模", () => {
    assert.equal(M.gap(635, 690), 55);
    assert.equal(M.gap(901, 570), 1109);
    assert.equal(M.gap(900, 570), 1110);
    assert.equal(M.gap(570, 570), 0);
  });
  t("progress", () => {
    assert.deepEqual(M.progress(500), { am: 0, pm: 0 });
    assert.equal(M.progress(630).am, 0.5);
    assert.deepEqual(M.progress(700), { am: 1, pm: 0 });
    assert.equal(M.progress(840).pm, 0.5);
    assert.deepEqual(M.progress(1000), { am: 1, pm: 1 });
  });
  t("formatReal / formatCountdown 边界", () => {
    assert.equal(M.formatReal(59999), "不到 1 分钟");
    assert.equal(M.formatReal(60000), "约 1 分钟");
    assert.equal(M.formatReal(165000), "约 3 分钟");
    assert.equal(M.formatReal(3600000), "约 1 小时");
    assert.equal(M.formatReal(3600000 + 25 * 60000), "约 1 小时 25 分");
    assert.equal(M.formatCountdown(-5), "0 秒");
    assert.equal(M.formatCountdown(8000), "8 秒");
    assert.equal(M.formatCountdown(7200), "8 秒");
    assert.equal(M.formatCountdown(59001), "1:00");
    assert.equal(M.formatCountdown(125000), "2:05");
    assert.equal(M.formatCountdown(3600000), "1:00:00");
    assert.equal(M.formatCountdown(3725000), "1:02:05");
  });
  t("dayMinutes / speedOf", () => {
    assert.deepEqual([1000, 3000, 5000].map(M.dayMinutes), [4, 12, 20]);
    assert.deepEqual([2500, 5000, 7500].map(M.dayMinutes), [10, 20, 30]);
    assert.equal(M.speedOf("v1", { refresh_rate_ms: 1000 }), "fast");
    assert.equal(M.speedOf("v1", { refresh_rate_ms: 3000 }), "normal");
    assert.equal(M.speedOf("v1", { refresh_rate_ms: 4600 }), "slow");
    assert.equal(M.speedOf("v1", {}), "normal");
    assert.equal(M.speedOf("v2", { clock_speed: "slow" }), "slow");
    assert.equal(M.speedOf("v2", {}), "normal");
  });

  t("normalize：v1 缺字段按刷新间隔推算", () => {
    const c = norm(v1(635));
    assert.equal(c.rules, "v1");
    assert.equal(c.phase, "morning");
    assert.equal(c.trading, true);
    assert.equal(c.ms_per_minute, 3000);
    assert.equal(c.next_event.kind, "lunch");
    assert.equal(c.next_event.at, T0 + 55 * 3000);
    assert.equal(c.derived, true);
    assert.equal(norm(v1(635), { refresh_rate_ms: 1000 }).ms_per_minute, 1000);
    assert.equal(norm(v1(635), { refresh_rate_ms: 0 }).ms_per_minute, 3000);
  });
  t("normalize：v1 非交易分钟也按刷新间隔走（15:01 → 次日 9:30）", () => {
    const c = norm(v1(901));
    assert.equal(c.phase, "closed");
    assert.equal(c.next_event.at, T0 + 1109 * 3000);
  });
  t("normalize：v2 字段优先，server_time 校正偏差", () => {
    const recv = T0;
    const serverAhead = 5000; // 服务端比本机快 5 秒
    const raw = {
      paused: false, tick: 1, trading_day: 3, clock_minute: 690, session: "closed",
      clock_rules: "v2", phase: "lunch", trading: false,
      next_event: { kind: "reopen", minute: 780, at: iso(T0 + serverAhead + 10000) },
      ms_per_minute: 5000, next_tick_at: null, fast_forward_at: iso(T0 + serverAhead + 5000),
      server_time: iso(T0 + serverAhead),
    };
    const c = M.normalize(raw, { now: T0 + 1000, received_at: recv, refresh_rate_ms: 3000 });
    assert.equal(c.rules, "v2");
    assert.equal(c.phase, "lunch");
    assert.equal(c.trading, false);
    assert.equal(c.offset_ms, serverAhead);
    assert.equal(c.next_event.at, T0 + 10000);
    assert.equal(c.fast_forward_at, T0 + 5000);
    assert.equal(c.next_tick_at, null);
    assert.equal(c.ms_per_minute, 5000);
    assert.equal(c.derived, false);
  });
  t("normalize：_offset_ms 优先；save_rules 作为规则回退；非法时间 → null", () => {
    const raw = { clock_minute: 600, trading_day: 0, paused: false, _offset_ms: 2000, next_event: { kind: "lunch", minute: 690, at: iso(T0 + 7000) } };
    const c = norm(raw, { save_rules: "v2" });
    assert.equal(c.rules, "v2");
    assert.equal(c.ms_per_minute, 5000);
    assert.equal(c.next_event.at, T0 + 5000);
    const bad = norm({ ...raw, next_event: { kind: "lunch", minute: 690, at: "garbage" } });
    assert.equal(bad.next_event.at, T0 + 90 * 3000); // 退回推算
  });
  t("normalize：WS 的 minute 字段、暂停时 at 为 null 不推算", () => {
    const c = norm({ minute: 600, paused: true, trading_day: 0 });
    assert.equal(c.minute, 600);
    assert.equal(c.next_event.at, null);
  });
  t("normalize：ms_per_minute=null → manual（不推算 at）", () => {
    const c = norm({ ...v1(600), clock_rules: "v2", ms_per_minute: null, paused: true });
    assert.equal(c.ms_per_minute, null);
    assert.equal(c.next_event.at, null);
    assert.equal(M.view(c, { now: T0 }).state, "manual");
    const c2 = norm({ ...v1(600), clock_rules: "v2", ms_per_minute: null });
    assert.equal(c2.next_event.at, null);
  });
  t("normalize：空输入不抛错", () => {
    const c = norm(null);
    assert.equal(c.phase, "morning");
    assert.equal(c.minute, 570);
  });

  t("view：v1 上午盘（mock 起点 10:35 / 3 秒）", () => {
    const c = norm({ ...v1(635), trading_day: 48 });
    const v = M.view(c, { now: T0 });
    assert.equal(v.state, "live");
    assert.equal(v.statusText, "交易中");
    assert.equal(v.classic, true);
    assert.equal(v.dayText, "D49 · 上午盘");
    assert.equal(v.timeText, "10:35");
    assert.equal(v.nextMain, "距午休 55 分钟");
    assert.equal(v.nextSub, "现实约 3 分钟");
    assert.equal(v.action, null);
    assert.equal(v.countdown_ms, null);
    assert.ok(Math.abs(v.progress.am - 65 / 120) < 1e-9);
    assert.equal(v.progress.pm, 0);
  });
  t("view：下午盘与“即将”", () => {
    assert.equal(M.view(norm(v1(840)), { now: T0 }).nextMain, "距收盘 60 分钟");
    assert.equal(M.view(norm(v1(899)), { now: T0 }).nextMain, "即将收盘");
    assert.equal(M.view(norm(v1(689)), { now: T0 }).nextMain, "即将午休");
  });
  t("view：v1 午休/收盘/盘前 → 可跳过", () => {
    const lunch = M.view(norm(v1(720)), { now: T0 });
    assert.equal(lunch.state, "dwell");
    assert.equal(lunch.nextMain, "距下午开盘 60 分钟");
    assert.equal(lunch.nextSub, "现实约 3 分钟");
    assert.equal(lunch.action, "skip");
    assert.equal(lunch.actionLabel, "跳到下午开盘");
    const closed = M.view(norm(v1(901)), { now: T0 });
    assert.equal(closed.state, "closed");
    assert.equal(closed.nextMain, "距明日开盘 1109 分钟");
    assert.equal(closed.nextSub, "现实约 55 分钟");
    assert.equal(closed.action, "skip");
    const pre = M.view(norm(v1(500)), { now: T0 });
    assert.equal(pre.state, "pre");
    assert.equal(pre.nextMain, "距开盘 70 分钟");
    assert.equal(pre.action, "skip");
    assert.equal(M.view(norm(v1(1000)), { now: T0 }).nextSub.startsWith("现实约 "), true);
    // 跳过目标就是当前分钟（12:59、9:29）或夜猫窗口末段（11:40）时不给按钮
    assert.equal(M.view(norm(v1(779)), { now: T0 }).action, null);
    assert.equal(M.view(norm(v1(569)), { now: T0 }).action, null);
    assert.equal(M.view(norm(v1(700)), { now: T0 }).action, null);
    assert.equal(M.view(norm(v1(695)), { now: T0 }).action, "skip");
  });
  t("skipTargetOf：与后端 skip_target_minutes 端点一致", () => {
    const e = { 569: 569, 570: 689, 689: null, 690: null, 691: 694, 694: 694, 695: 699, 698: 699, 699: null, 700: null, 701: 779, 779: 779, 780: 899, 899: null, 900: null, 901: 569, 1439: 569 };
    for (const [m, t] of Object.entries(e)) assert.equal(M.skipTargetOf(+m), t, `skip ${m}`);
  });
  t("view：暂停（任意相位）→ 继续", () => {
    const v = M.view(norm(v1(635, { paused: true })), { now: T0 });
    assert.equal(v.state, "paused");
    assert.equal(v.statusText, "已暂停");
    assert.equal(v.nextMain, "距午休 55 分钟");
    assert.equal(v.nextSub, "行情已暂停");
    assert.equal(v.action, "resume");
    assert.equal(v.actionLabel, "继续");
    const vc = M.view(norm(v1(901, { paused: true })), { now: T0 });
    assert.equal(vc.action, "resume");
    assert.equal(vc.state, "paused");
  });
  const v2raw = (minute, phase, ev, extra = {}) => ({
    paused: false, tick: 9, trading_day: 11, clock_minute: minute, session: "closed",
    clock_rules: "v2", phase, trading: phase === "morning" || phase === "afternoon",
    next_event: ev, ms_per_minute: 5000, server_time: iso(T0), ...extra,
  });
  t("view：v2 午休 11:30 停留倒计时", () => {
    const c = norm(v2raw(690, "lunch", { kind: "reopen", minute: 780, at: iso(T0 + 8000) }));
    const v = M.view(c, { now: T0 });
    assert.equal(v.state, "dwell");
    assert.equal(v.classic, false);
    assert.equal(v.dayText, "第 12 个交易日 · 午休");
    assert.equal(v.nextMain, "午间休市");
    assert.equal(v.nextSub, "8 秒后下午开盘");
    assert.equal(v.countdown_ms, 8000);
    assert.equal(v.action, null);
    const later = M.view(c, { now: T0 + 3000 });
    assert.equal(later.nextSub, "5 秒后下午开盘");
    assert.equal(M.view(c, { now: T0 + 99999 }).countdown_ms, 0);
  });
  t("view：v2 收盘 / 9:29 盘前 / 交易时段用 at", () => {
    const closed = M.view(norm(v2raw(900, "closed", { kind: "open", minute: 570, at: iso(T0 + 20000) })), { now: T0 });
    assert.equal(closed.state, "closed");
    assert.equal(closed.nextMain, "已收盘");
    assert.equal(closed.nextSub, "20 秒后进入第 13 个交易日");
    assert.equal(closed.countdown_ms, 20000);
    assert.equal(closed.action, null);
    const pre = M.view(norm(v2raw(569, "pre_open", { kind: "open", minute: 570, at: iso(T0 + 5000) })), { now: T0 });
    assert.equal(pre.state, "pre");
    assert.equal(pre.nextMain, "即将开盘");
    assert.equal(pre.nextSub, "5 秒后开盘");
    const live = M.view(norm(v2raw(642, "morning", { kind: "lunch", minute: 690, at: iso(T0 + 240000) })), { now: T0 });
    assert.equal(live.nextMain, "距午休 48 分钟");
    assert.equal(live.nextSub, "现实约 4 分钟");
    assert.equal(live.timeText, "10:42");
    assert.equal(live.countdown_ms, null);
  });
  t("view：v2 缺 next_event.at 时按 gap × ms_per_minute 估算", () => {
    const c = norm(v2raw(642, "morning", { kind: "lunch", minute: 690, at: null }));
    assert.equal(c.next_event.at, T0 + 48 * 5000);
    assert.equal(c.derived, true);
  });
  t("view：v2 暂停清空倒计时", () => {
    const v = M.view(norm(v2raw(900, "closed", { kind: "open", minute: 570, at: null }, { paused: true })), { now: T0 });
    assert.equal(v.state, "paused");
    assert.equal(v.countdown_ms, null);
    assert.equal(v.action, "resume");
  });
}
