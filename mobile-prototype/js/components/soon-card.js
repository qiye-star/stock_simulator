/**
 * “即将开放”占位卡：功能尚未上线（占位页）或后端接口不存在（FEATURE_UNAVAILABLE）时使用。
 *
 *   SS.soonCardHtml({ title, desc }) → SafeHtml    同步版，用于拼进模板
 *   SS.soonCard(host, { title, desc })              渲染到容器
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  SS.soonCardHtml = ({ title = "", desc = "" } = {}) => html`<section class="soon-card">
    <div class="soon-card__head"><h2 class="soon-card__title">${title}</h2><span class="tag">即将开放</span></div>
    ${desc ? html`<p class="soon-card__desc t2 sm">${desc}</p>` : ""}
  </section>`;

  SS.soonCard = (host, opts) => SS.mount(host, SS.soonCardHtml(opts));
})();
