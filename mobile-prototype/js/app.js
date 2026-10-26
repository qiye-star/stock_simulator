/**
 * 启动入口：注册路由、挂载 Dock、启动行情。
 * 必须最后加载（依赖 lib/ mock/ components/ pages/ features/ 中注册到 SS 的全部模块）。
 *
 * 路由注册顺序（同 pattern 先注册者生效）：先各玩法 features（SS.features.*.routes），再核心页面，最后“即将开放”占位
 * ——某玩法上线后注册了同路由，占位自动失效，本文件不用再改。
 * 各 feature 的 init()（注册 slot/guard、订阅 WS）在进入就绪态后、首个页面渲染前只调用一次。
 *
 * 真实模式启动流程：骨架屏 → store.init()（/me、/saves、行情、持仓…）
 *   - 401：跳 #/login，登录成功后 SS.enter() 重新 init；
 *   - 其它失败（网络/后端挂了）：整页错误提示 + 重试按钮，不白屏；
 *   - 运行中任何接口 401（会话过期）：停止实时流并跳 #/login。
 */
(function () {
  const SS = window.SS;
  const P = SS.pages;
  const { html } = SS;

  // 1. 各玩法 feature 的路由
  Object.values(SS.features).forEach((f) => (f.routes || []).forEach(([pattern, page]) => SS.router.add(pattern, page)));
  // 2. 核心页面
  SS.router.add("/market", P.market);
  SS.router.add("/stock/:code", P.stock);
  SS.router.add("/portfolio", P.portfolio);
  SS.router.add("/play", P.play);
  SS.router.add("/me", P.me);
  SS.router.add("/auto", P.auto); // 二级页，入口在“我的”
  SS.router.add("/login", P.login);
  // 3. 占位（feature 已注册同路由时本条不会命中）
  SS.router.add("/news", P.comingSoon({ tab: "news", title: "快讯", desc: "开启事件模式的存档会在这里显示公告、新闻、政策与传闻。" }));

  let featuresInited = false;
  function initFeatures() {
    if (featuresInited) return;
    featuresInited = true;
    SS.closeSummary.watch(); // 收盘小结是全局层（v2 收盘自动弹出），与 features 同一时机挂载一次
    for (const [name, f] of Object.entries(SS.features)) {
      try {
        f.init && f.init();
      } catch (e) {
        console.warn(`feature ${name} 初始化失败`, e);
      }
    }
  }

  SS.dock.mount(SS.$("#dock"));
  const view = () => SS.$("#view");
  let started = false;

  function startRouter() {
    if (started) return SS.router.navigate(location.hash.replace(/^#/, "") || "/market");
    started = true;
    SS.router.start();
  }

  // 页面隐藏时暂停实时流，省电；回到前台会先补一次行情
  document.addEventListener("visibilitychange", () => {
    if (SS.store.mode === "real" && !SS.ready) return;
    document.hidden ? SS.store.stop() : SS.store.start();
  });

  if (SS.isMock) {
    SS.ready = true;
    initFeatures();
    startRouter();
    SS.store.start();
    return;
  }

  // ---------- 真实模式 ----------
  SS.ready = false;
  SS.api.onUnauthorized = () => {
    if (!SS.ready) return;
    SS.ready = false;
    SS.store.stop();
    SS.toast && SS.toast("登录已过期，请重新登录", { icon: null, duration: 2000 });
    location.hash = "#/login";
  };

  /** 登录成功后调用：拉全量数据 → 启动实时流 → 进入行情页 */
  SS.enter = async function () {
    await SS.store.init();
    SS.booted = true; // 行情页跳过假的 650ms 骨架
    SS.ready = true;
    initFeatures();
    SS.store.start();
    if (location.hash === "#/market") startRouter();
    else location.hash = "#/market";
  };

  function loading() {
    SS.mount(
      view(),
      html`<div class="topbar"><h1 class="topbar__title">行情</h1></div>
        <div style="padding:0 var(--gutter,16px)">
          <div class="skeleton" style="height:120px;border-radius:16px;margin-top:8px"></div>
          ${Array.from({ length: 6 }).map(() => html`<div class="skeleton" style="height:44px;margin-top:14px"></div>`)}
        </div>`
    );
    SS.dock.setActive(null);
  }

  function failed(err) {
    SS.mount(
      view(),
      html`<div class="empty" style="padding-top:30vh">
        <div class="empty__title">${SS.store.errorText(err && err.code)}</div>
        <p class="t3 sm">无法连接服务，请确认后端已启动</p>
        <button type="button" class="btn btn-sm btn-primary" data-role="retry">重试</button>
      </div>`
    );
    SS.$('[data-role="retry"]', view()).addEventListener("click", boot);
  }

  async function boot() {
    loading();
    try {
      await SS.store.init();
    } catch (err) {
      if (err && err.status === 401) {
        if (location.hash !== "#/login") location.hash = "#/login";
        startRouter();
      } else failed(err);
      return;
    }
    SS.booted = true;
    SS.ready = true;
    initFeatures();
    if (location.hash === "#/login") location.hash = "#/market";
    startRouter();
    SS.store.start();
  }
  boot();
})();
