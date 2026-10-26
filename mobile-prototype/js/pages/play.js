/**
 * 玩法（#/play）—— hub 页：各玩法通过 SS.slots.register("play", {id, order, mount}) 注册自己的分区。
 *   - 已知分区 challenge(10) 每日挑战 / pm(20) 预测市场 / replay(30) 真实复盘；
 *     没有注册 provider 的分区显示“即将开放”占位，已注册的由 provider 自己渲染（⑦⑧⑨）；
 *   - 分区容器用 flex + style.order 排序，占位与 provider 按 order 穿插。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  const SECTIONS = [
    { id: "challenge", order: 10, title: "每日挑战", desc: "全服同一份行情和事件，每天几轮，大家同时预测、交易，晚上统一结算排名。" },
    { id: "pm", order: 20, title: "预测市场", desc: "用积分买卖，价格就是全服的判断" },
    { id: "replay", order: 30, title: "真实复盘", desc: "回到真实历史，股票名已隐去" },
  ];

  function render(view) {
    SS.mount(view, html`<header class="topbar"><h1 class="topbar__title">玩法</h1></header><div class="play-sections" data-role="sections"></div>`);
    const host = SS.$('[data-role="sections"]', view);
    const unmount = SS.slots.mount("play", host);
    for (const s of SECTIONS) {
      if (SS.slots.has("play", s.id)) continue;
      const el = SS.el(html`<section class="play-section" style="order:${s.order}" data-section="${s.id}">${SS.soonCardHtml({ title: s.title, desc: s.desc })}</section>`);
      host.appendChild(el);
    }
    return unmount;
  }

  SS.pages = SS.pages || {};
  SS.pages.play = { tab: "play", render };
})();
