/**
 * 每日挑战纯函数（无 DOM、不读 SS.store，tests/ 在 vm 里加载；依赖 SS.predictModel / SS.predictMath 时只在函数内访问）。
 *   时间：服务端 ISO（UTC）+ 客户端偏移 skew = server_time − 本机时间（取自最近一次 ChallengeOut）。倒计时与阶段文案只经本模块推导。
 *   字段口径见 docs/10.26-plan/03-每日挑战.md §10.2；页面不得自行读 Date.now() 做时段判断（传入 nowMs）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const CN_OFFSET_MS = 8 * 3600e3; // 北京时间固定 UTC+8（不依赖 tzdata）
  const COMMIT_PREFIX = "stocksim-challenge|v1|";
  const PHASE_TEXT = { before: "未开赛", burst: "快放中", hold: "行情已暂停", final: "最后一段", ended: "已收盘" };
  const NEXT_LABEL = { before: "距开赛", burst: "距本轮停顿", hold: "距行情继续", final: "距结算" };
  // 快放段（burst / final）的 next_change_at 为 null（03 §5 #8：停顿时刻与结算时刻保密），只显示阶段文案，不倒计时
  const FAST_BIG = { burst: "快放中", final: "最后一段", hold: "全服暂停" };
  const FAST_HINT = { burst: "停顿时间保密", final: "" };
  const STEP_CLS = { resolved: "is-done", closed: "is-done", open: "is-live", burst: "is-live", pending: "is-pending" };
  const BOARD_NAME = { total: "综合", forecast: "预测", trade: "交易" };

  const p2 = (x) => String(x).padStart(2, "0");
  const toMs = (iso) => (iso ? Date.parse(iso) : NaN);

  /** 服务端时钟偏移（毫秒）：server_time − 本机时间；缺失或非法时为 0 */
  function skewOf(serverIso, localNowMs) {
    const s = toMs(serverIso);
    return Number.isFinite(s) ? s - localNowMs : 0;
  }

  /** 毫秒 → "4:59"（不足 1 小时）、"2:14:05"（不足 1 天）、"1 天 2:14:05"；负数按 0 */
  function formatDuration(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const d = Math.floor(total / 86400);
    const h = Math.floor((total % 86400) / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (d > 0) return `${d} 天 ${h}:${p2(m)}:${p2(s)}`;
    if (h > 0) return `${h}:${p2(m)}:${p2(s)}`;
    return `${m}:${p2(s)}`;
  }

  /**
   * 距目标时刻的剩余时间：target 为 ISO，skew 为服务端偏移，nowMs 为本机当前毫秒。
   * 返回 { ms, text, done }；done 表示目标已到（原始差值 ≤ 0）；target 缺失时 ms 为 null。
   */
  function countdown(targetIso, skew, nowMs) {
    const t = toMs(targetIso);
    if (!Number.isFinite(t)) return { ms: null, text: "", done: false };
    const raw = t - (nowMs + (skew || 0));
    const ms = Math.max(0, raw);
    return { ms, text: formatDuration(ms), done: raw <= 0 };
  }

  /** ISO → 北京时间 "HH:mm"；非法返回 "" */
  function clockText(iso) {
    const t = toMs(iso);
    if (!Number.isFinite(t)) return "";
    const d = new Date(t + CN_OFFSET_MS);
    return `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`;
  }

  /** "2026-10-25" → "10 月 25 日"（挑战的 challenge_date，口径为北京日历日）；非法返回 "" */
  function ymdText(ymd) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(ymd || ""));
    if (!m) return "";
    return `${Number(m[2])} 月 ${Number(m[3])} 日`;
  }

  /** 回合条：total 段（默认 4），按回合卡/回合记录的 state 映射；缺失的回合为 pending */
  function roundBar(rounds, total = 4) {
    const byIdx = new Map((rounds || []).map((r) => [r.round_index, r]));
    return Array.from({ length: total }, (_, i) => {
      const r = byIdx.get(i + 1);
      const state = r ? r.state : "pending";
      return { index: i + 1, state, cls: STEP_CLS[state] || "is-pending" };
    });
  }

  /**
   * 挑战时间线（阶段、回合、倒计时）。ch 为 ChallengeOut；rounds 缺省用 ch.rounds（ChallengeRoundOut[]）。
   * 返回 { phaseText, roundText, nextLabel, next: countdown, closes: countdown|null, bar, big, hint, fast }：
   *   next = next_change_at（阶段含义见 NEXT_LABEL）；closes = 当前回合（state=open）的 closes_at；
   *   fast = 运行中但 next_change_at 为 null（burst / final，停顿或结算时刻保密），此时 next.ms 为 null，
   *   big 为大字阶段文案（“快放中”等，倒计时时即倒计时文本），hint 为一行副文案（已拼好，页面直接用）。
   *   settle_expected_at 是结算时刻的上界（不是精确时刻），final 段的 hint 用它显示“最迟 HH:mm 结算”。
   */
  function timeline(ch, skew, nowMs) {
    const total = ch.rounds_total || 4;
    const rounds = ch.rounds || [];
    const k = ch.round_index;
    const cur = k ? rounds.find((r) => r.round_index === k) || null : null;
    let phaseText = PHASE_TEXT[ch.phase] || "";
    if (ch.status === "settled") phaseText = "已结算";
    else if (ch.status === "void") phaseText = "已作废";
    const live = ch.status === "running";
    const scheduled = ch.status === "scheduled";
    let nextLabel = "";
    let next = countdown(null, 0, nowMs);
    let big = "";
    let hint = "";
    let fast = false;
    if (scheduled) {
      nextLabel = "距开赛";
      next = countdown(ch.starts_at, skew, nowMs);
      big = next.text;
      hint = `${nextLabel} ${next.text}`;
    } else if (live && ch.next_change_at) {
      nextLabel = NEXT_LABEL[ch.phase] || "";
      next = countdown(ch.next_change_at, skew, nowMs);
      big = next.text;
      hint = [nextLabel, next.text].filter(Boolean).join(" ");
    } else if (live) {
      fast = true;
      big = FAST_BIG[ch.phase] || "进行中";
      hint = FAST_HINT[ch.phase] || "";
      if (ch.phase === "final" && ch.settle_expected_at) hint = `最迟 ${clockText(ch.settle_expected_at)} 结算`;
    } else if (ch.status === "settled") {
      big = "已结算";
    } else if (ch.status === "void") {
      big = "已作废";
    }
    return {
      phaseText,
      roundText: k ? `第 ${k} 轮 / ${total}` : `共 ${total} 轮`,
      nextLabel,
      next,
      closes: cur && cur.state === "open" ? countdown(cur.closes_at, skew, nowMs) : null,
      bar: roundBar(rounds, total),
      big,
      hint,
      fast,
    };
  }

  /** 当前回合的卡（ChallengeRoundCardOut）是否已有本人答案 */
  const answeredRound = (cards, k) => {
    const c = (cards || []).find((x) => x.round_index === k);
    return !!(c && c.my_answers && c.my_answers.length);
  };

  /**
   * 挑战卡 / 入口按钮（08 §5.7 表）。ch 为 ChallengeOut 或 null（今日未生成）；
   * ctx: { now（毫秒）, skew, cards（ChallengeRoundCardOut[]，可空；缺省视为未答） }。
   * 返回 { label, kind: "enter" | "nav" | "disabled" | "none", to? }
   */
  function primaryAction(ch, ctx = {}) {
    if (!ch) return { label: "", kind: "none" };
    const now = ctx.now != null ? ctx.now : Date.now();
    const skew = ctx.skew || 0;
    if (ch.status === "void") return { label: "今日挑战已作废", kind: "disabled" };
    if (ch.status === "settled") return { label: "查看复盘", kind: "nav", to: `/challenge/${ch.id}/review` };
    if (ch.status === "scheduled") return { label: `${clockText(ch.starts_at)} 开赛`, kind: "disabled" };
    if (!ch.my_entry) {
      const open = now + skew < toMs(ch.entry_closes_at);
      return open ? { label: "参加挑战", kind: "enter" } : { label: "已停止报名", kind: "disabled" };
    }
    const k = ch.round_index;
    const cur = (ch.rounds || []).find((r) => r.round_index === k);
    if (k && cur && cur.state === "open" && !answeredRound(ctx.cards, k)) {
      return { label: `进入第 ${k} 轮`, kind: "nav", to: "/challenge" };
    }
    return { label: "去交易", kind: "nav", to: "/market" };
  }

  /** 收益率的涨跌色（行情数据用红绿；0 或缺失为中性） */
  const toneOf = (bp) => (bp > 0 ? "up" : bp < 0 ? "down" : "");

  /** 带符号的整数：+41 / −3 / 0（服务端 forecast_score、total_score 等） */
  function signed(n) {
    if (n == null) return "—";
    return n > 0 ? `+${n}` : String(n);
  }

  /** 基点 → "+3.10%"（与 SS.fmt.pctBp 同口径，tests 不依赖 format.js） */
  function pctText(bp) {
    if (bp == null) return "—";
    const v = Number(bp) / 100;
    return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  /** 排行榜表头：day 时第三列随 board（综合/预测/交易）；week/all 为总分 / 参赛天数 */
  function boardHeaders(scope, board) {
    if (scope === "day") return { c3: `${BOARD_NAME[board] || BOARD_NAME.total}分`, c4: "仓位收益" };
    return { c3: "总分", c4: "参赛天数" };
  }

  /**
   * 排行榜行（LeaderboardItemOut[] → 展示用）。scope 为 day|week|all，board 仅 day 使用。
   * 名次并列由服务端给出（rank），这里只原样显示；rank 为 null 时显示 "—"。
   */
  function boardRows(items, scope, board) {
    return (items || []).map((x) => {
      const byBoard = { total: x.total_score, forecast: x.forecast_score, trade: x.trade_score };
      return {
        rankText: x.rank == null ? "—" : String(x.rank),
        name: x.username || "",
        title: x.equipped_title || null,
        isMe: !!x.is_me,
        c3: signed(scope === "day" ? byBoard[board || "total"] : x.total_score),
        c4: scope === "day" ? pctText(x.return_bp) : x.days_played == null ? "—" : String(x.days_played),
        c4Tone: scope === "day" ? toneOf(x.return_bp) : "",
      };
    });
  }

  /** 我的成绩（EntryResultOut）的展示项：总分、预测分、交易收益、名次、积分 */
  function resultStats(result) {
    if (!result) return null;
    return {
      total: signed(result.total_score),
      forecast: signed(result.forecast_score),
      trade: pctText(result.return_bp),
      tradeTone: result.return_bp > 0 ? "up" : result.return_bp < 0 ? "down" : "flat",
      rank: result.rank == null ? "未入榜" : `第 ${result.rank} 名 / ${result.eligible_count} 人`,
      points: result.points_awarded ? `+${result.points_awarded}` : "0",
    };
  }

  const myAnswer = (card, qid) => (card.my_answers || card.answers || []).find((a) => a.qid === qid) || null;

  /**
   * 本人作答摘要（每题一行）：dir → “>5%（把握 75%）”，rank → “A、B、C”，rumor → “会被辟谣（把握 70%）”。
   * 依赖 SS.predictMath（分档文案）；未作答返回 “未作答”。
   */
  function answerLines(card) {
    const PM = SS.predictMath;
    const M = SS.predictModel;
    const qs = M.sortQuestions(card.questions || []);
    return qs.map((q) => {
      const a = myAnswer(card, q.qid);
      if (!a) return { qid: q.qid, text: "未作答" };
      if (q.qid === "dir" && a.probs) {
        const pick = PM.argmaxPick(a.probs);
        const label = pick == null ? "—" : PM.bucketLabels(q.edges_bp)[pick];
        return { qid: q.qid, text: `${label} · 把握 ${pick == null ? 0 : a.probs[pick]}%` };
      }
      if (q.qid === "rank" && a.order) return { qid: q.qid, text: a.order.join("、") };
      if (q.qid === "rumor" && a.probs) {
        const pick = PM.argmaxPick(a.probs);
        return { qid: q.qid, text: `${pick === 1 ? "会被证实" : "会被辟谣"} · 把握 ${pick == null ? 0 : a.probs[pick]}%` };
      }
      return { qid: q.qid, text: "已作答" };
    });
  }

  /**
   * 已判定题目的结果（QuestionResultOut）展示：实际结果文案与本题得分（0..100）。
   * 未判定的题返回 { resolved: false }。
   */
  function resultLines(card) {
    const PM = SS.predictMath;
    const M = SS.predictModel;
    return M.sortQuestions(card.questions || []).map((q) => {
      const r = (card.results || []).find((x) => x.qid === q.qid) || null;
      const base = { qid: q.qid, score: r && r.score != null ? r.score : null };
      if (!r || !r.resolved) return { ...base, resolved: false, text: "等待判定" };
      if (q.qid === "dir") {
        const bucket = r.outcome_bucket == null ? "—" : PM.bucketLabels(q.edges_bp)[r.outcome_bucket];
        return { ...base, resolved: true, text: `实际 ${pctText(r.change_bp)}，落在 ${bucket}` };
      }
      if (q.qid === "rank") {
        return { ...base, resolved: true, text: `实际前三：${(r.true_top || []).join("、") || "—"}` };
      }
      return { ...base, resolved: true, text: r.truth ? "传闻被证实" : "传闻被辟谣" };
    });
  }

  /** 群体均值（crowd，回合截止后才有）：dir 的最可能档位与概率；无数据返回 null */
  function crowdText(card) {
    const c = card.crowd;
    const d = c && c.by_qid && c.by_qid.dir;
    if (!d || !d.mean_probs || !d.mean_probs.length) return null;
    const probs = d.mean_probs;
    let best = 0;
    probs.forEach((p, i) => {
      if (p > probs[best]) best = i;
    });
    const q = SS.predictModel.sortQuestions(card.questions || []).find((x) => x.qid === "dir");
    const label = q ? SS.predictMath.bucketLabels(q.edges_bp)[best] : `第 ${best + 1} 档`;
    return `全服均值最可能 ${label} · ${probs[best]}%`;
  }

  /** 得分来源文案：peer 同伴分 / baseline 基线分（参与人数不足） */
  function usedText(used) {
    if (used === "peer") return "同伴分";
    if (used === "baseline") return "基线分（参与人数不足）";
    return "";
  }

  /** sha256 承诺的短显示：3f9a1c07…be52e21c */
  function shortHash(hex) {
    const s = String(hex || "");
    return s.length > 20 ? `${s.slice(0, 8)}…${s.slice(-8)}` : s;
  }

  /** reveal 中的承诺原文（03 §1.4 格式）；不是挑战承诺格式返回 null */
  function commitmentInputOf(reveal) {
    const s = reveal && reveal.commitment_input;
    return typeof s === "string" && s.startsWith(COMMIT_PREFIX) ? s : null;
  }

  /** 解析承诺原文：stocksim-challenge|v1|{date}|ruleset={r}|clock={c}|seed={seed}|salt={salt} → 字段对象；格式不对返回 null */
  function parseCommitmentInput(s) {
    if (typeof s !== "string" || !s.startsWith(COMMIT_PREFIX)) return null;
    const parts = s.slice(COMMIT_PREFIX.length).split("|");
    if (parts.length !== 5) return null;
    const kv = (x, key) => (x.startsWith(key + "=") ? x.slice(key.length + 1) : null);
    const ruleset = kv(parts[1], "ruleset");
    const clock = kv(parts[2], "clock");
    const seed = kv(parts[3], "seed");
    const salt = kv(parts[4], "salt");
    if (ruleset == null || clock == null || seed == null || salt == null) return null;
    return { date: parts[0], ruleset, clock, seed, salt };
  }

  /** 计算出的 sha256（小写 hex）与承诺是否一致；大小写与首尾空白不敏感，任一缺失为 false */
  function digestMatches(computedHex, committedHex) {
    const a = String(computedHex || "").trim().toLowerCase();
    const b = String(committedHex || "").trim().toLowerCase();
    return a.length === 64 && a === b;
  }

  /** 种子一致性：承诺原文里的 seed 必须等于 reveal.market_seed（十进制字符串） */
  function seedMatches(reveal) {
    const parsed = parseCommitmentInput(commitmentInputOf(reveal));
    return !!parsed && parsed.seed === String(reveal.market_seed);
  }

  /**
   * 是否该重拉今日挑战（flow 的轮询节流）：倒计时到点后节流 3 秒；快放段（tl.fast，停顿与结算时刻保密）每 5 秒轮询。
   * 与后端 CHALLENGE_HOLD_POLL_MS 同量级，WS 断开时也能发现停顿、恢复与结算。
   */
  function refreshDue(tl, lastAt, now) {
    if (!tl) return false;
    const gap = now - (lastAt || 0);
    if (tl.next && tl.next.done) return gap > 3000;
    if (tl.fast) return gap > 5000;
    return false;
  }

  SS.challengeModel = {
    COMMIT_PREFIX,
    refreshDue,
    PHASE_TEXT,
    skewOf,
    formatDuration,
    countdown,
    clockText,
    ymdText,
    roundBar,
    timeline,
    primaryAction,
    signed,
    pctText,
    boardHeaders,
    boardRows,
    toneOf,
    resultStats,
    answerLines,
    resultLines,
    crowdText,
    usedText,
    shortHash,
    commitmentInputOf,
    parseCommitmentInput,
    digestMatches,
    seedMatches,
  };
})();
