/**
 * 登录 / 注册（#/login）—— 对应 POST /auth/login|register（Cookie 会话，httpOnly，无需前端存 token）。
 *   - 无 Dock（tab: null）；会话过期（任意接口 401）会被 app.js 重定向到这里；
 *   - 成功后调用 store.init() 拉取全部数据，再进入行情页。
 * 仅真实模式使用；localStorage 只记住上次的用户名（ss.lastUser）。
 */
(function () {
  const SS = (window.SS = window.SS || {});
  const { html } = SS;

  function render(view) {
    const store = SS.store;
    let mode = "login"; // login | register
    let last = "";
    try {
      last = localStorage.getItem("ss.lastUser") || "";
    } catch (_) {}

    function paint() {
      const reg = mode === "register";
      SS.mount(
        view,
        html`<div class="login">
          <div class="login__brand"><span class="shiny-text">股市模拟器</span></div>
          <p class="t3 sm login__sub">${reg ? "创建账号，开始你的模拟交易" : "登录后继续你的模拟交易"}</p>
          <form class="login__form" data-role="form" autocomplete="on" novalidate>
            <label class="field"><span class="field__label"><span>用户名</span></span>
              <input class="input" data-role="user" name="username" autocomplete="username" autocapitalize="off" spellcheck="false" value="${last}" /></label>
            <label class="field"><span class="field__label"><span>密码</span></span>
              <input class="input" data-role="pass" name="password" type="password" autocomplete="${reg ? "new-password" : "current-password"}" /></label>
            <div class="order__error" data-role="error" role="alert"></div>
            <button type="submit" class="btn btn-primary btn-block btn-lg" data-role="submit">${reg ? "注册并登录" : "登录"}</button>
            <button type="button" class="btn btn-ghost btn-block" data-role="toggle">${reg ? "已有账号？去登录" : "没有账号？去注册"}</button>
          </form>
        </div>`
      );
      const $ = (r) => SS.$(`[data-role="${r}"]`, view);
      $("toggle").addEventListener("click", () => {
        last = $("user").value;
        mode = reg ? "login" : "register";
        paint();
      });
      $("form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const u = $("user").value.trim();
        const p = $("pass").value;
        if (!u || !p) {
          $("error").textContent = "请输入用户名和密码";
          return;
        }
        const btn = $("submit");
        btn.disabled = true;
        btn.textContent = "请稍候…";
        $("error").textContent = "";
        try {
          await (reg ? store.register(u, p) : store.login(u, p));
          try {
            localStorage.setItem("ss.lastUser", u);
          } catch (_) {}
          await SS.enter(); // app.js：init → 启动实时流 → 跳行情
        } catch (err) {
          $("error").textContent = store.errorText(err && err.code);
          btn.disabled = false;
          btn.textContent = reg ? "注册并登录" : "登录";
        }
      });
      if (!last || reg) $("user").focus();
    }
    paint();
  }

  SS.pages = SS.pages || {};
  SS.pages.login = { tab: null, render };
})();
