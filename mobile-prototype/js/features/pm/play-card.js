/**
 * 玩法页的预测市场分区（slot play:pm，order 20）：SS.pmPlayCard.mount(host) → cleanup。
 *   标题“预测市场”+“用积分买卖，价格就是全服的判断”；进行中的合约最多 2 张（市场卡）；
 *   最近一张已结算（取 /me/prediction-settlements 第一条，显示结果与盈亏）；“全部市场 ›”→ #/pm。
 *   没有进行中的市场：今日尚无市场 → “今日挑战开始后开市”；已有市场但都已结束 → “今日市场已结束，暂无进行中的合约”；后端没有接口 → “即将开放”。
 * 只拉一次，不订阅 WS（列表页与详情页才连接全服推送）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;
  const DESC = "用积分买卖，价格就是全服的判断，功能即将开放。";

  function mount(host) {
    let alive = true;
    SS.mount(
      host,
      html`<section class="pm-section" data-role="pm-section">
        <div class="pm-section__head">
          <h2 class="pm-section__title">预测市场</h2>
          <span class="t2 xs">用积分买卖，价格就是全服的判断</span>
        </div>
        <div class="pm-section__body" data-role="body"><div class="skeleton" style="height:96px;border-radius:18px"></div></div>
      </section>`
    );
    const body = SS.$('[data-role="body"]', host);

    async function load() {
      try {
        const [page, settle] = await Promise.all([SS.store.listPredictionMarkets({ status: "all", limit: 20 }), SS.store.listMyPredictionSettlements()]);
        if (!alive) return;
        const items = page.items;
        const open = items
          .filter((m) => m.status === "open" || m.status === "closed")
          .sort((a, b) => b.open_tt - a.open_tt)
          .slice(0, 2);
        const last = (settle.items || [])[0] || null;
        const more = html`<a class="pm-more" href="${SS.href("/pm")}">全部市场 ›</a>`;
        if (!open.length && !last) {
          // 今日有市场但都已停止/结算：不再说“开市”；还没有任何市场时才是开赛前的文案
          const text = SS.pmModel.emptyText(items);
          return SS.mount(body, html`<p class="t2 sm pm-section__empty">${text}</p>${more}`);
        }
        SS.mount(
          body,
          html`${open.map((m) => SS.pmUi.cardHtml(m))}${last ? SS.pmUi.settledCardHtml(last) : ""}${more}`
        );
      } catch (err) {
        if (!alive) return;
        if (err && err.code === "FEATURE_UNAVAILABLE") return SS.soonCard(host, { title: "预测市场", desc: DESC });
        SS.mount(body, html`<p class="t2 sm">${SS.store.errorText(err && err.code)}</p>`);
      }
    }
    load();
    return () => {
      alive = false;
    };
  }

  SS.pmPlayCard = { mount };
})();
