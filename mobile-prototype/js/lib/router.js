/**
 * 极简 hash 路由：#/market、#/stock/600519、#/portfolio、#/auto、#/me。
 * 页面对象约定：{ tab?: string, render(view, params) → cleanup? }
 *   - tab：所属底部导航项；为空表示二级页（隐藏 Dock）
 *   - render 返回的函数在离开页面时调用（取消订阅、清定时器）
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const routes = [];
  let cleanup = null;
  const scrollMemo = {}; // 记住一级页的滚动位置，返回时还原

  function add(pattern, page) {
    const keys = [];
    const re = new RegExp(
      "^" + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "$"
    );
    routes.push({ re, keys, page, pattern });
  }

  function resolve() {
    const path = location.hash.replace(/^#/, "") || "/market";
    for (const r of routes) {
      const m = path.match(r.re);
      if (m) return { route: r, params: Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])), path };
    }
    return null;
  }

  let current = null;
  let visits = 0; // 应用内导航次数，用于判断能否 history.back()
  function go() {
    const view = SS.$("#view");
    const hit = resolve();
    if (!hit) {
      location.replace("#/market");
      return;
    }
    if (current) scrollMemo[current] = view.scrollTop;
    if (typeof cleanup === "function") cleanup();
    SS.sheet && SS.sheet.closeAll();
    view.classList.remove("view-enter");
    void view.offsetWidth; // 重新触发入场动画
    view.classList.add("view-enter");
    view.dataset.page = hit.route.pattern;
    cleanup = hit.route.page.render(view, hit.params) || null;
    view.scrollTop = hit.route.page.tab ? scrollMemo[hit.path] || 0 : 0;
    current = hit.path;
    visits++;
    SS.dock && SS.dock.setActive(hit.route.page.tab || null);
  }

  function navigate(path) {
    if (location.hash === "#" + path) go();
    else location.hash = path;
  }

  /** 返回：有历史就后退，否则回行情 */
  function back() {
    if (visits > 1) history.back();
    else navigate("/market");
  }

  SS.router = {
    add,
    navigate,
    back,
    start() {
      window.addEventListener("hashchange", go);
      go();
    },
  };
})();
