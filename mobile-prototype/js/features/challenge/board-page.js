/**
 * 挑战排行榜（#/challenge/board?scope=day|week|all&board=total|forecast|trade，SS.pages.challengeBoard）：
 *   顶部三段 今日 / 本周 / 总榜（scope 来自 query，缺省本周）；今日再加综合 / 预测 / 交易（board）；
 *   我的一行（.board-me，名次用 --accent）；表头 + 行（.board-row，48px，≥44px 触控）；游标“加载更多”；
 *   底部公平性卡（今日种子承诺，结算后可验证）。
 * 今日未结算（CHALLENGE_NOT_SETTLED）：提示“今晚结算后公布今日排名”，并默认切到本周。
 * 数据：day → GET /challenges/{今日id}/leaderboard；week|all → GET /challenge-leaderboard。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const store = () => SS.store;
  const M = () => SS.challengeModel;
  const UI = () => SS.challengeUi;
  const SCOPES = [
    ["day", "今日"],
    ["week", "本周"],
    ["all", "总榜"],
  ];
  const BOARDS = [
    ["total", "综合"],
    ["forecast", "预测"],
    ["trade", "交易"],
  ];

  function render(view, params) {
    const q = params.query || {};
    // 缺省“今日”；今日未结算时 load() 会自动切到“本周”（CHALLENGE_NOT_SETTLED）
    let scope = SCOPES.some((x) => x[0] === q.scope) ? q.scope : "day";
    let board = BOARDS.some((x) => x[0] === q.board) ? q.board : "total";
    let items = [];
    let me = null;
    let next = null;
    let eligible = null;
    let dayPending = false;
    let seq = 0;
    let today = null;
    let alive = true;

    SS.mount(
      view,
      html`<header class="topbar topbar--sub">
          <button type="button" class="icon-btn" data-role="back" aria-label="返回">${SS.icon("back")}</button>
          <h1 class="topbar__title topbar__title--sub">挑战排行榜</h1>
        </header>
        <div class="ch-page">
          <div class="seg seg--3 seg--inline-full" data-role="scopes">
            <span class="seg__thumb" aria-hidden="true"></span>
            ${SCOPES.map(([v, t]) => html`<button type="button" data-value="${v}">${t}</button>`)}
          </div>
          <div class="seg seg--3 seg--mini ch-board-seg" data-role="boards" hidden>
            <span class="seg__thumb" aria-hidden="true"></span>
            ${BOARDS.map(([v, t]) => html`<button type="button" data-value="${v}">${t}</button>`)}
          </div>
          <p class="t2 xs ch-notice" data-role="notice" hidden></p>
          <section class="card board-me" data-role="me"></section>
          <div class="board-list" data-role="list"></div>
          <button type="button" class="btn btn-ghost btn-block btn-lg" data-role="more" hidden>加载更多</button>
          <div data-role="fair"></div>
        </div>`
    );
    const $ = (r) => SS.$(`[data-role="${r}"]`, view);
    SS.$('[data-role="back"]', view).addEventListener("click", () => SS.router.back());

    // 切换经路由（hashchange 重新渲染本页并带上新的 query），不在这里直接请求
    const scopeSeg = SS.segmented($("scopes"), (v) => SS.router.replace(`/challenge/board?scope=${v}${v === "day" ? `&board=${board}` : ""}`));
    const boardSeg = SS.segmented($("boards"), (v) => SS.router.replace(`/challenge/board?scope=day&board=${v}`));

    function drawMe() {
      const el = $("me");
      if (!me) {
        return SS.mount(el, html`<span class="t2 sm">${scope === "day" ? "今晚结算后可见你的今日名次" : "你还没有上榜成绩"}</span>`);
      }
      const r = M().boardRows([me], scope, board)[0];
      const sub = scope === "day" ? `已答 ${me.answered_rounds == null ? "—" : me.answered_rounds}/4 轮` : `参赛 ${me.days_played == null ? "—" : me.days_played} 天`;
      const h = M().boardHeaders(scope, board);
      SS.mount(
        el,
        html`<div class="board-me__row">
          <span class="num board-me__rank">${r.rankText}</span>
          <div class="board-me__who"><span class="board-me__name">你</span><span class="t2 xs">${sub}</span></div>
          <div class="board-me__vals">
            <span class="num">${r.c3}</span><span class="t2 xs">${h.c3}</span>
          </div>
          <div class="board-me__vals">
            <span class="num ${r.c4Tone || ""}">${r.c4}</span><span class="t2 xs">${h.c4}</span>
          </div>
        </div>`
      );
    }

    function drawList() {
      const el = $("list");
      const h = M().boardHeaders(scope, board);
      const rows = M().boardRows(items, scope, board);
      SS.mount(
        el,
        html`${UI().boardHeadHtml(h)}${rows.length ? rows.map((r) => UI().boardRowHtml(r)) : html`<div class="empty-inline t2 sm">还没有人上榜</div>`}`
      );
      $("more").hidden = !next;
    }

    function drawNotice() {
      const el = $("notice");
      el.hidden = !dayPending;
      el.textContent = dayPending ? "今日排名今晚结算后公布，先看本周。" : "";
    }

    async function drawFair() {
      const el = $("fair");
      if (!today) return SS.mount(el, "");
      SS.mount(el, UI().fairnessHtml({ seedCommitment: today.seed_commitment, settled: today.status === "settled" }));
      UI().bindVerify(el, () => store().loadChallengeReveal(today.id));
    }

    function syncSegs() {
      scopeSeg.set(scope);
      $("boards").hidden = scope !== "day";
      if (scope === "day") boardSeg.set(board);
    }

    async function load(reset) {
      const my = ++seq;
      if (reset) {
        items = [];
        next = null;
      }
      syncSegs();
      drawNotice();
      try {
        let out;
        if (scope === "day") {
          if (!today) today = await store().loadTodayChallenge();
          out = await store().loadChallengeLeaderboard(today.id, { board, cursor: reset ? undefined : next });
        } else {
          out = await store().loadChallengeBoards({ scope, cursor: reset ? undefined : next });
        }
        if (!alive || my !== seq) return;
        items = reset ? out.items : items.concat(out.items);
        me = out.me || null;
        next = out.next_cursor || null;
        eligible = out.eligible_count;
        drawMe();
        drawList();
        drawFair();
      } catch (err) {
        if (!alive || my !== seq) return;
        if (err && err.code === "CHALLENGE_NOT_SETTLED" && scope === "day") {
          dayPending = true;
          scope = "week";
          SS.toast("今晚结算后公布今日排名", { icon: null, duration: 1800 });
          return load(true);
        }
        if (err && err.code === "FEATURE_UNAVAILABLE") {
          // 后端没有挑战接口：整页换成占位（不留分段与加载按钮）
          SS.mount(SS.$(".ch-page", view), SS.soonCardHtml({ title: "挑战排行榜", desc: "全服排名在挑战结算后公布，功能即将开放。" }));
          return;
        }
        store().notifyError(err);
      }
    }

    $("more").addEventListener("click", () => {
      if (next) load(false);
    });

    load(true);
    return () => {
      alive = false;
    };
  }

  SS.pages = SS.pages || {};
  SS.pages.challengeBoard = { tab: null, render };
})();
