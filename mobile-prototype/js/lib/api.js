/**
 * 真实后端 REST 客户端（同源 /api/v1，Cookie 会话 `session`）+ 运行模式开关。
 *
 * 模式：
 *   - 真实模式（默认）：store.real.js 经本文件请求 /api/v1/*；
 *   - 假数据模式：URL 带 `?mock=1`（写入 localStorage `ss.mock`，持续生效），`?mock=0` 关闭；
 *     以 file:// 直接打开时也自动进入假数据模式（没有后端可连）。
 * 错误：非 2xx 解析 {code, params} 抛 SS.ApiError；网络失败抛 code=NETWORK；401 触发 SS.api.onUnauthorized。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  // ---------- 模式 ----------
  const qs = new URLSearchParams(location.search);
  try {
    if (qs.has("mock")) {
      if (qs.get("mock") === "0") localStorage.removeItem("ss.mock");
      else localStorage.setItem("ss.mock", "1");
    }
  } catch (_) {
    /* 隐私模式下 localStorage 不可用：仅本次有效 */
  }
  let flag = qs.get("mock") === "1";
  try {
    flag = flag || (qs.get("mock") !== "0" && localStorage.getItem("ss.mock") === "1");
  } catch (_) {}
  SS.isMock = location.protocol === "file:" || flag;

  // ---------- 错误 ----------
  class ApiError extends Error {
    constructor(code, status = 0, params = {}) {
      super(code);
      this.name = "ApiError";
      this.code = code;
      this.status = status;
      this.params = params;
    }
  }
  SS.ApiError = ApiError;

  const BASE = "/api/v1";

  function url(path, query) {
    const u = new URL(BASE + path, location.origin);
    if (query) for (const [k, v] of Object.entries(query)) if (v != null && v !== "") u.searchParams.set(k, String(v));
    return u.pathname + u.search;
  }

  async function send(method, path, { body, query, headers = {}, raw = false } = {}) {
    const init = { method, credentials: "same-origin", headers: { Accept: "application/json", ...headers } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url(path, query), init);
    } catch (_) {
      throw new ApiError("NETWORK", 0);
    }
    if (res.status === 204) return null;
    if (res.ok && raw) return res.blob();
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const code = typeof data?.code === "string" ? data.code : `HTTP_${res.status}`;
      const err = new ApiError(code, res.status, data?.params && typeof data.params === "object" ? data.params : {});
      // 登录/注册本身的 401（凭据错误）不算会话过期
      if (res.status === 401 && !path.startsWith("/auth/")) api.onUnauthorized && api.onUnauthorized(err);
      throw err;
    }
    return data;
  }

  /** WebSocket 地址：/api/v1/ws/saves/{id}，随页面协议选 ws/wss，同源（由 dev-server / nginx 转发） */
  const wsUrl = (path) => `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}${BASE}${path}`;

  const api = {
    BASE,
    get: (p, o) => send("GET", p, o),
    post: (p, o) => send("POST", p, o),
    put: (p, o) => send("PUT", p, o),
    patch: (p, o) => send("PATCH", p, o),
    del: (p, o) => send("DELETE", p, o),
    blob: (p) => send("GET", p, { raw: true }),
    wsUrl,
    /** 由 app.js 注入：会话失效时跳登录页 */
    onUnauthorized: null,
  };
  SS.api = api;
})();
