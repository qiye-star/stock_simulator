/**
 * 极简 hash 路由：#/market、#/stock/600519、#/portfolio、#/me、#/chain?focus=有色。
 * 页面对象约定：{ tab?: string, render(view, params) → cleanup? }
 *   - tab：所属底部导航项（market/news/portfolio/play/me）；为空表示二级页（隐藏 Dock）
 *   - render 返回的函数在离开页面时调用（取消订阅、清定时器）
 *   - params：路径参数 + params.query（hash 中 ? 之后的参数对象，没有则 {}）
 * 同一 pattern 先注册者生效（如 /pm/records 必须在 /pm/:id 之前）。
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
    const path = location.hash.replace(/^#/, "") || "/market"; // 含 query，作为滚动记忆键
    const q = path.indexOf("?");
    const pathname = q < 0 ? path : path.slice(0, q);
    const query = Object.fromEntries(new URLSearchParams(q < 0 ? "" : path.slice(q + 1)));
    for (const r of routes) {
      const m = pathname.match(r.re);
      if (m) return { route: r, params: { ...Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])), query }, path };
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

  /** 替换当前历史项（如产业链切换焦点，不刷历史）；hash 变化会触发 go() */
  function replace(path) {
    location.replace("#" + path);
  }

  /** 拼链接：href("/chain", {focus: "有色"}) → "#/chain?focus=%E6%9C%89%E8%89%B2" */
  function href(path, query) {
    const qs = Object.entries(query || {})
      .filter(([, v]) => v != null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    return `#${path}${qs ? "?" + qs : ""}`;
  }

  /** 返回：有历史就后退，否则回行情 */
  function back() {
    if (visits > 1) history.back();
    else navigate("/market");
  }

  SS.router = {
    add,
    navigate,
    replace,
    back,
    start() {
      window.addEventListener("hashchange", go);
      go();
    },
  };
  SS.href = href;
})();
