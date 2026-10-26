/**
 * 占位页工厂：SS.pages.comingSoon({ tab, title, desc }) → 页面对象。
 * 用于功能尚未上线的 Dock 入口（如 ⑤ 之前的 #/news）；功能的 feature 注册了同路由时先注册者生效，占位自动失效。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  SS.pages = SS.pages || {};
  SS.pages.comingSoon = ({ tab = null, title = "", desc = "" } = {}) => ({
    tab,
    render(view) {
      SS.mount(view, html`<header class="topbar"><h1 class="topbar__title">${title}</h1></header>${SS.soonCardHtml({ title, desc })}`);
      return null;
    },
  });
})();
