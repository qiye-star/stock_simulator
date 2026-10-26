/**
 * Dock —— 复刻 React Bits「Dock」（Components/Dock）的移动端版本。
 * 桌面版的“鼠标靠近放大”在触屏上没有意义，这里保留其精髓：
 *   - 胶囊面板 + 图标 + 标签；
 *   - 按下时图标弹性放大（magnification 的触屏化）；
 *   - 选中项下方的强调色指示点，以及滑动的高亮底板。
 * 5 个入口：行情 / 快讯 / 持仓 / 玩法 / 我的；二级页（如个股详情、自动交易）调用 setActive(null) 隐藏 Dock。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const ITEMS = [
    { tab: "market", label: "行情", icon: "market", path: "/market" },
    { tab: "news", label: "快讯", icon: "news", path: "/news" },
    { tab: "portfolio", label: "持仓", icon: "pie", path: "/portfolio" },
    { tab: "play", label: "玩法", icon: "games", path: "/play" },
    { tab: "me", label: "我的", icon: "me", path: "/me" },
  ];
  let root = null;

  function mount(el) {
    root = el;
    el.style.setProperty("--dock-n", ITEMS.length); // 等分列数与高亮底板宽度都读它
    SS.mount(
      el,
      SS.html`<nav class="dock__panel" aria-label="主导航">
        <span class="dock__highlight" aria-hidden="true"></span>
        ${ITEMS.map(
          (it) => SS.html`<a class="dock__item" href="#${it.path}" data-tab="${it.tab}">
            <span class="dock__icon">${SS.icon(it.icon)}</span>
            <span class="dock__label">${it.label}</span>
            <span class="dock__dot" aria-hidden="true"></span>
          </a>`
        )}
      </nav>`
    );
    el.addEventListener("click", (e) => {
      const a = e.target.closest(".dock__item");
      if (!a) return;
      SS.haptic();
      // 点当前 tab：滚回顶部
      if (a.classList.contains("is-active")) {
        e.preventDefault();
        SS.$("#view").scrollTo({ top: 0, behavior: SS.reducedMotion() ? "auto" : "smooth" });
      }
    });
  }

  function setActive(tab) {
    if (!root) return;
    root.classList.toggle("is-hidden", !tab);
    let idx = -1;
    SS.$$(".dock__item", root).forEach((a, i) => {
      const on = a.dataset.tab === tab;
      a.classList.toggle("is-active", on);
      if (on) {
        a.setAttribute("aria-current", "page");
        idx = i;
      } else a.removeAttribute("aria-current");
    });
    if (idx >= 0) root.style.setProperty("--dock-i", idx);
  }

  SS.dock = { mount, setActive };
})();
