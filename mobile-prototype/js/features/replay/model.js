/**
 * 真实复盘（⑨ E）的纯函数层：SS.replayModel。无 DOM、无 store，tests/ 在 vm 里加载。
 *
 * 时间坐标：pos = day_idx * 4 + 阶段序号（pre_open 0 / open 1 / close 2 / post_close 3）。day_idx 从游戏第 0 日起为 0，回看期为负。
 * 关卡包（mock 与真实共用的形状，见 mock.js）：
 *   { lookback_days, play_days, reveal_days, calendar[], stocks[{key, real_code, real_name, industry, alias_code, alias_name, mask_scale_ppm}],
 *     bars{key: [[o,h,l,c,v], …]} 与 calendar 对齐（真实价，分）, benchmark{name, closes[]}, events[], questions[] }
 * 价格：关卡包里是真实价；匿名模式对价格乘 mask_scale_ppm（ppm）。页面只显示服务端返回的价格，这里的函数用于 mock 与单测。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  const PHASES = ["pre_open", "open", "close", "post_close"];
  const PHASE_LABEL = { pre_open: "盘前", open: "开盘", close: "收盘", post_close: "盘后" };
  const LOT = 100;
  const MASK_RANGE = [1000, 5000]; // 前收缩放后落在 10–50 元（05 §1.7）
  const FAKE_BASE = Date.UTC(2001, 0, 1); // 假日历从 2001-01-01（周一）起连续排工作日，不留节假日空档

  // ---------- 阶段与位置 ----------
  const phaseIdx = (phase) => PHASES.indexOf(phase);
  const posOf = (day, phase) => day * 4 + phaseIdx(phase);
  const dayOf = (pos) => Math.floor(pos / 4);
  const phaseOf = (pos) => PHASES[pos - Math.floor(pos / 4) * 4];
  const lastPos = (playDays) => posOf(playDays - 1, "post_close");
  const isTradable = (phase) => phase === "open" || phase === "close";
  /** 当前能否下单：阶段可交易且股票未停牌（quote.suspended 来自 StockMarketOut，任何阶段都可能停牌） */
  const canTrade = (phase, quote) => isTradable(phase) && !(quote && quote.suspended);
  /** 成交价口径（05 §1.3）：开盘阶段按开盘价，收盘阶段按收盘价，其它阶段不能成交 */
  const priceBasis = (phase) => (phase === "open" ? "open" : phase === "close" ? "close" : null);
  const basisText = (phase) => (priceBasis(phase) === "open" ? "开盘价" : priceBasis(phase) === "close" ? "收盘价" : "");
  /** 不能交易时的说明（页面展示用） */
  const blockedText = (phase) => (phase === "pre_open" ? "盘前不能交易，进入开盘后可下单" : phase === "post_close" ? "盘后不能交易，进入下一天后可下单" : "");
  /**
   * 卖出按钮置灰时的行内原因（空串 = 可卖）。顺序：停牌 > 阶段不能交易 > 未持有 > 当日买入未解冻（T+1）。
   * holding 为 null 表示未持有；sellable 为可卖股数。
   */
  function sellBlockedText(phase, quote, holding, sellable) {
    if (quote && quote.suspended) return "停牌";
    if (!isTradable(phase)) return phase === "pre_open" ? "盘前不能卖" : "盘后不能卖";
    if (!holding) return "未持有";
    if (!(sellable > 0)) return "今日买入，明日可卖";
    return "";
  }

  /**
   * 推进目标（05 §1.3）：next_phase 走到下一位置；next_day 走到下一日盘前；
   * 已在最后一个盘后时再推进即结算（settle = true，位置停在最后一个盘后）。
   */
  function targetPos(pos, to, playDays) {
    const last = lastPos(playDays);
    if (pos >= last) return { target: last, settle: true };
    if (to === "next_day") {
      const d = dayOf(pos);
      if (d >= playDays - 1) return { target: last, settle: true };
      return { target: posOf(d + 1, "pre_open"), settle: false };
    }
    const t = pos + 1;
    return t > last ? { target: last, settle: true } : { target: t, settle: false };
  }

  /**
   * 推进时的预测题检查。qs: [{ id, opens, closes, resolves（位置）, answered }]。
   *   - 离开位置 [pos, target) 内仍未答的题：next_phase 直接 blocked（REPLAY_PREDICTION_PENDING）；skip=true 时记为 skip（记 0 分）。
   *   - next_day 途中（含到达点）遇到开放或截止的题：stop 在该位置，reason = question_open / question_due（05 §5.8 stopped_reason）。
   */
  function checkQuestions(qs, pos, target, to, skipPending) {
    const leaving = qs.filter((q) => !q.answered && q.closes >= pos && q.closes < target);
    if (to === "next_day") {
      let best = null;
      for (const q of qs) {
        if (q.opens > pos && q.opens <= target && (!best || q.opens < best.pos)) best = { pos: q.opens, reason: "question_open" };
        if (!q.answered && q.closes > pos && q.closes <= target && (!best || q.closes < best.pos)) best = { pos: q.closes, reason: "question_due" };
      }
      if (best) return { blocked: [], skip: [], stop: best };
    }
    if (leaving.length && !skipPending) return { blocked: leaving.map((q) => q.id), skip: [], stop: null };
    return { blocked: [], skip: leaving.map((q) => q.id), stop: null };
  }

  /** 题目状态（02/05 的 ReplayQuestionOut.status）：有结果 → scored；跳过 → skipped；已答 → answered；截止未答 → closed；其它 → open */
  function questionStatus(pos, closesPos, st) {
    if (st.result) return "scored";
    if (st.skipped) return "skipped";
    if (st.answer) return "answered";
    return pos > closesPos ? "closed" : "open";
  }

  // ---------- 假日历与日期 ----------
  const FAKE_DAYS = (() => {
    const out = [];
    let t = FAKE_BASE;
    while (out.length < 1400) {
      const wd = new Date(t).getUTCDay();
      if (wd !== 0 && wd !== 6) out.push(new Date(t).toISOString().slice(0, 10));
      t += 86400000;
    }
    return out;
  })();
  /** 假日历下标 day（可负）→ ISO 日期；day 0 落在第 1000 个工作日，保证负数不越界 */
  const fakeIso = (day) => FAKE_DAYS[day + 1000];
  /** 匿名模式的日期文案：T+3 / T-2（05 §1.2） */
  const tLabel = (day) => (day < 0 ? `T-${-day}` : `T+${day}`);
  const dateLabelOf = (pack, day, masked) => (masked ? tLabel(day) : pack.calendar[day + pack.lookback_days]);
  const isoOf = (pack, day, masked) => (masked ? fakeIso(day) : pack.calendar[day + pack.lookback_days]);

  // ---------- 价格缩放 ----------
  const scalePrice = (realCents, ppm) => Math.round((realCents * ppm) / 1e6);
  const unscalePrice = (maskedCents, ppm) => Math.round((maskedCents * 1e6) / ppm);
  /** 由前收与目标前收求缩放系数（ppm）：让第 0 日前收落在 MASK_RANGE 内 */
  const pickScalePpm = (prevCloseCents, targetCents) => Math.round((targetCents * 1e6) / prevCloseCents);
  const inMaskRange = (cents) => cents >= MASK_RANGE[0] && cents <= MASK_RANGE[1];

  // ---------- 计分（与 B 的 RPS / NDCG 同式，见 predict/model.js） ----------
  /** 方向题：probs 为整数百分比（合计 100），outcome 为真实档位下标；RPS 映射为 0–100 */
  function rpsScore(probs, outcome) {
    const K = probs.length;
    let cp = 0;
    let s = 0;
    for (let k = 0; k < K - 1; k++) {
      cp += probs[k] / 100;
      const co = outcome <= k ? 1 : 0;
      s += (cp - co) * (cp - co);
    }
    return Math.round(100 * (1 - s / (K - 1)));
  }
  /** 排序题：order 为作答顺序（候选代码），rel 为相关度（真实前几名 3/2/1），NDCG@k 映射为 0–100 */
  function ndcgScore(order, rel, k = 3) {
    const gain = (r) => 2 ** r - 1;
    const dcg = order.slice(0, k).reduce((a, c, i) => a + gain(rel[c] || 0) / Math.log2(i + 2), 0);
    const ideal = Object.values(rel).sort((a, b) => b - a).slice(0, k);
    const idcg = ideal.reduce((a, r, i) => a + gain(r) / Math.log2(i + 2), 0);
    return idcg ? Math.round((100 * dcg) / idcg) : 0;
  }

  // ---------- 方向题档位（05 §3.2） ----------
  const round50 = (x) => Math.sign(x) * Math.round(Math.abs(x) / 50) * 50;
  /**
   * 档位边界：σ 为回看期日收益率标准差（bp），s = σ·√h；边界 [-1.0s, -0.3s, +0.3s, +1.0s] 四舍五入到 50bp，
   * ±0.3s 至少 ±50bp，且四个边界严格递增。
   */
  function autoEdges(returnsBp, horizon) {
    const n = returnsBp.length;
    const mean = returnsBp.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(returnsBp.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (n - 1));
    const s = sd * Math.sqrt(horizon);
    const lo1 = Math.min(-50, round50(-0.3 * s));
    const lo0 = Math.min(lo1 - 50, round50(-1.0 * s));
    const hi1 = Math.max(50, round50(0.3 * s));
    const hi0 = Math.max(hi1 + 50, round50(1.0 * s));
    return [lo0, lo1, hi1, hi0];
  }
  /** 档位下标（左闭右开）：ret < e0 → 0；e0 ≤ ret < e1 → 1 …；ret ≥ e3 → 4 */
  const bucketOf = (retBp, edges) => edges.filter((e) => retBp >= e).length;
  const pctText = (bp) => {
    const v = Math.abs(bp) / 100;
    return (bp < 0 ? "−" : "") + String(Number(v.toFixed(2)));
  };
  /** 5 档 ReplayBucketOut：[{label, lo_bp, hi_bp}] */
  function bucketsOf(edges) {
    const e = edges;
    return [
      { label: `≤${pctText(e[0])}%`, lo_bp: null, hi_bp: e[0] },
      { label: `${pctText(e[0])}~${pctText(e[1])}%`, lo_bp: e[0], hi_bp: e[1] },
      { label: `${pctText(e[1])}~${pctText(e[2])}%`, lo_bp: e[1], hi_bp: e[2] },
      { label: `${pctText(e[2])}~${pctText(e[3])}%`, lo_bp: e[2], hi_bp: e[3] },
      { label: `≥${pctText(e[3])}%`, lo_bp: e[3], hi_bp: null },
    ];
  }

  // ---------- 订单 ----------
  /** 下单预览（与服务端口径一致的近似）：金额、手续费、合计（买入含费，卖出扣费） */
  function estimateOrder({ side, quantity, price_cents, buy_fee_rate = 0.0003, sell_fee_rate = 0.0013 }) {
    const amount = Math.round(price_cents * quantity);
    const fee = Math.round(amount * (side === "buy" ? buy_fee_rate : sell_fee_rate));
    return { amount_cents: amount, fee_cents: fee, total_cents: side === "buy" ? amount + fee : amount - fee };
  }
  /** 现金能买的最大整手数 */
  const maxBuyQty = (cashCents, priceCents, buyFeeRate = 0.0003) => Math.max(0, Math.floor(cashCents / (priceCents * (1 + buyFeeRate)) / LOT) * LOT);
  /** 封板（05 §1.4）：买入时价格已到涨停、卖出时已到跌停，不可成交 */
  const isLocked = (side, priceCents, limitUpCents, limitDownCents) => (side === "buy" ? priceCents >= limitUpCents : priceCents <= limitDownCents);

  // ---------- 关卡包读取（只读） ----------
  /** 日 K（真实价）：day 为游戏日（可负）；越界返回 null */
  function barAt(pack, key, day) {
    const arr = pack.bars[key];
    const j = day + pack.lookback_days;
    if (!arr || j < 0 || j >= arr.length) return null;
    const [o, h, l, c, v] = arr[j];
    return { day, o, h, l, c, v };
  }
  const stockOf = (pack, key) => pack.stocks.find((s) => s.key === key) || null;
  /** 匿名 / 实名的代码与名称、行业 */
  const identityOf = (pack, key, masked) => {
    const s = stockOf(pack, key);
    return masked ? { code: s.alias_code, name: s.alias_name, industry: s.industry } : { code: s.real_code, name: s.real_name, industry: s.industry };
  };
  const keyOfCode = (pack, code, masked) => {
    const s = pack.stocks.find((x) => (masked ? x.alias_code : x.real_code) === code);
    return s ? s.key : null;
  };
  const scaler = (pack, key, masked) => {
    if (!masked) return (v) => v;
    const ppm = stockOf(pack, key).mask_scale_ppm;
    return (v) => scalePrice(v, ppm);
  };

  /**
   * 位置 pos 时对玩家可见的那根日 K（真实价）。
   * 过去的日子全部可见；今天：盘前不可见，开盘只露出开盘价（H=L=C=O、量 0），收盘与盘后完整。未来不可见。
   */
  function seenBar(pack, key, day, pos) {
    const cur = dayOf(pos);
    const ph = phaseOf(pos);
    if (day > cur) return null;
    if (day < cur) return barAt(pack, key, day);
    if (ph === "pre_open") return null;
    const b = barAt(pack, key, day);
    if (!b) return null;
    if (ph === "open") return { day, o: b.o, h: b.o, l: b.o, c: b.o, v: 0 };
    return b;
  }

  /**
   * 报价（QuoteOut 形状）：盘前现价 = 前收；开盘 = 开盘价（量 0）；收盘与盘后 = 收盘价。
   * masked 时价格按 mask_scale_ppm 缩放，代码与名称用别名。
   */
  function quoteOf(pack, key, pos, masked) {
    const cur = dayOf(pos);
    const ph = phaseOf(pos);
    const id = identityOf(pack, key, masked);
    const sc = scaler(pack, key, masked);
    const prev = sc(barAt(pack, key, cur - 1).c);
    const today = barAt(pack, key, cur);
    let o, h, l, c, v;
    if (ph === "pre_open") {
      o = h = l = c = prev;
      v = 0;
    } else if (ph === "open") {
      o = h = l = c = sc(today.o);
      v = 0;
    } else {
      o = sc(today.o);
      h = sc(today.h);
      l = sc(today.l);
      c = sc(today.c);
      v = today.v;
    }
    return {
      code: id.code,
      name: id.name,
      industry: id.industry,
      price_cents: c,
      prev_close_cents: prev,
      open_cents: o,
      high_cents: h,
      low_cents: l,
      volume: v,
      change_bp: Math.round(((c - prev) * 10000) / prev),
      limit_up_cents: Math.round(prev * 1.1),
      limit_down_cents: Math.round(prev * 0.9),
      circuit_breaker_active: false,
      watchlisted: false,
    };
  }

  /** 可见日 K（CandleOut 形状），按日升序；匿名日期用假日历 */
  function candlesAt(pack, key, pos, masked) {
    const out = [];
    const sc = scaler(pack, key, masked);
    for (let d = -pack.lookback_days; d <= dayOf(pos); d++) {
      const b = seenBar(pack, key, d, pos);
      if (!b) continue;
      out.push({
        trading_day: d,
        date: isoOf(pack, d, masked),
        open_cents: sc(b.o),
        high_cents: sc(b.h),
        low_cents: sc(b.l),
        close_cents: sc(b.c),
        volume: b.v,
      });
    }
    return out;
  }

  /** 事件可见的位置：盘前事件在盘前可见；盘中事件在收盘后可见（09:30–15:00 发布）；盘后事件在盘后可见 */
  const eventPos = (ev) => posOf(ev.day_idx, ev.slot === "intraday" ? "close" : ev.slot === "post_close" ? "post_close" : "pre_open");

  /** 快讯条目（NewsOut 形状的子集，与 A 的字段同名）；masked 用匿名标题与正文 */
  function feedItemOf(pack, ev, masked) {
    const codes = (ev.stock_keys || []).map((k) => identityOf(pack, k, masked));
    const first = codes[0] || null;
    return {
      news_id: ev.id,
      event_id: ev.id,
      stage: "publish",
      kind: ev.kind,
      subtype: null,
      scope: ev.scope,
      major: ev.importance >= 3,
      sentiment: null,
      title: masked ? ev.title_masked : ev.title,
      body: masked ? ev.body_masked : ev.body,
      industry: (ev.industries || [])[0] || null,
      code: first ? first.code : null,
      stock_name: first ? first.name : null,
      targets: codes.map((c) => c.code),
      trading_day: ev.day_idx,
      trading_tick: eventPos(ev),
      tick: eventPos(ev),
      day_offset: ev.day_idx,
      clock_minute: ev.slot === "pre_open" ? 540 : ev.slot === "intraday" ? 570 : 960,
      slot: ev.slot,
      time_label: ev.local_time ? ev.local_time.slice(11, 16) : null,
      date_label: dateLabelOf(pack, ev.day_idx, masked),
      importance: ev.importance,
      source: ev.source,
      url: null,
    };
  }

  /** 可见事件（新的在前）；masked 时隐藏 hide_in_masked 的条目 */
  function eventsAt(pack, pos, masked) {
    return pack.events
      .filter((e) => eventPos(e) <= pos && !(masked && e.hide_in_masked))
      .sort((a, b) => eventPos(b) - eventPos(a) || (a.id < b.id ? 1 : -1))
      .map((e) => feedItemOf(pack, e, masked));
  }

  /** 题目在包里的位置（opens / closes / resolves 为 pos） */
  function questionPositions(q) {
    return { opens: posOf(q.opens.day, q.opens.phase), closes: posOf(q.closes.day, q.closes.phase), resolves: posOf(q.resolves.day, q.resolves.phase) };
  }

  /** 预测题的 ReplayQuestionOut 形状（不含答案字段；result 只在 scored 后给） */
  function questionOf(pack, q, pos, st, masked) {
    const p = questionPositions(q);
    const codes = q.kind === "rank" ? q.stock_keys.map((k) => identityOf(pack, k, masked).code) : [identityOf(pack, q.stock_key, masked).code];
    const pos2 = (x) => ({ day_idx: x.day, phase: x.phase });
    const nameOf = (k) => identityOf(pack, k, masked);
    const isRank = q.kind === "rank";
    const name = isRank ? null : nameOf(q.stock_key).name;
    const prompt = masked && q.prompt_masked ? q.prompt_masked.replace("{name}", name || "") : q.prompt;
    const result = st.result
      ? isRank
        ? { returns_bp: Object.fromEntries(Object.entries(st.result.returns_bp).map(([k, v]) => [nameOf(k).code, v])), true_top: st.result.true_top.map((k) => nameOf(k).code), score: st.result.score, points: st.result.points }
        : { outcome_bucket: st.result.outcome_bucket, return_bp: st.result.return_bp, score: st.result.score, points: st.result.points }
      : null;
    return {
      id: q.id,
      kind: q.kind,
      prompt,
      codes,
      buckets: isRank ? null : bucketsOf(q.edges_bp),
      top_k: isRank ? q.top_k : null,
      opens: pos2(q.opens),
      closes: pos2(q.closes),
      resolves: pos2(q.resolves),
      status: questionStatus(pos, p.closes, st),
      my_answer: st.answer ? (isRank ? { order: st.answer.order.map((k) => nameOf(k).code) } : { probs: st.answer.probs.slice() }) : null,
      result,
    };
  }

  /**
   * 把 ReplayQuestionOut 适配成预测卡的一张“卡”（供 SS.predictionCard.render/bind 复用，见 08 §5.9）。
   * nameOf(code) 返回展示名（候选芯片与标题用）；只支持 5 档方向题与 top_k=3 的排序题。
   */
  function predictionCardOf(q, saveId, nameOf) {
    const id = `${saveId}:${q.id}`;
    const from = q.opens ? q.opens.day_idx : 0;
    const to = q.resolves ? q.resolves.day_idx : from;
    const answers = [];
    if (q.my_answer && q.my_answer.probs) answers.push({ qid: "dir", probs: q.my_answer.probs });
    if (q.my_answer && q.my_answer.order) answers.push({ qid: "rank", order: q.my_answer.order.map(nameOf) });
    const base = { id, status: "open", event: { title: "真实复盘预测" }, opened_trading_day: from, answers };
    if (q.kind === "rank") {
      return { ...base, questions: [{ qid: "rank", k: q.top_k, title: q.prompt, candidates: q.codes.map(nameOf), from_day: from, to_day: to, at_day: to }] };
    }
    const edges = (q.buckets || []).slice(0, 4).map((b) => b.hi_bp);
    return { ...base, questions: [{ qid: "dir", title: q.prompt, edges_bp: edges, target_kind: "stock", target_name: "", from_day: from, to_day: to }] };
  }

  /**
   * 揭示页的代码 → 真实名称。揭示后题目里的代码（codes、true_top、returns_bp 的键）是真实代码，
   * 而 my_answer 与 stocks[].code 是会话内的别名代码：两种都认。找不到时原样返回。
   */
  const revealNameOf = (stocks) => (code) => {
    const x = (stocks || []).find((y) => y.code === code || y.real_code === code);
    return x ? x.real_name : code;
  };

  /** 按 ReplaySessionOut 的时间字段生成展示用的日期与阶段文案 */
  const posText = (pos, playDays) => ({ day: dayOf(pos) + 1, total: playDays, phase: phaseOf(pos), phaseText: PHASE_LABEL[phaseOf(pos)] });

  /** 推进按钮文案 */
  function nextActionLabel(pos, playDays) {
    if (pos >= lastPos(playDays)) return "结束并揭晓";
    return { pre_open: "进入开盘", open: "进入收盘", close: "进入盘后", post_close: "进入下一天" }[phaseOf(pos)];
  }

  /** 难度 1–3 → 文案 */
  const DIFF_TEXT = { 1: "低", 2: "中", 3: "高" };
  const difficultyText = (d) => `难度 ${DIFF_TEXT[d] || "—"}`;
  const starsText = (d) => "★".repeat(d) + "☆".repeat(Math.max(0, 3 - d));

  SS.replayModel = {
    PHASES,
    PHASE_LABEL,
    LOT,
    MASK_RANGE,
    phaseIdx,
    posOf,
    dayOf,
    phaseOf,
    lastPos,
    isTradable,
    canTrade,
    priceBasis,
    basisText,
    blockedText,
    sellBlockedText,
    targetPos,
    checkQuestions,
    questionStatus,
    fakeIso,
    tLabel,
    dateLabelOf,
    isoOf,
    scalePrice,
    unscalePrice,
    pickScalePpm,
    inMaskRange,
    rpsScore,
    ndcgScore,
    round50,
    autoEdges,
    bucketOf,
    bucketsOf,
    estimateOrder,
    maxBuyQty,
    isLocked,
    barAt,
    stockOf,
    identityOf,
    keyOfCode,
    seenBar,
    quoteOf,
    candlesAt,
    eventPos,
    feedItemOf,
    eventsAt,
    questionPositions,
    questionOf,
    predictionCardOf,
    revealNameOf,
    posText,
    nextActionLabel,
    difficultyText,
    starsText,
  };
})();
