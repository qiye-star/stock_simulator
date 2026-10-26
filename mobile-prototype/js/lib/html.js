/**
 * DOM 小工具（全局命名空间 SS）。
 *
 * 之所以不用 ES 模块：原型要支持直接双击 index.html（file://）打开，
 * 而浏览器在 file:// 下会拦截 <script type="module">。因此所有脚本都是经典脚本，
 * 按 index.html 中的顺序加载，通过 window.SS 共享。
 *
 * 与主前端 frontend/src/ui/html.js 的约定一致：拼 HTML 一律用 html`` 模板，插值默认转义，
 * 只有显式 SS.raw() 包裹的片段（来自其它 html`` 结果或内部 SVG 生成器）才原样输出。
 */
(function () {
  const SS = (window.SS = window.SS || {});

  class SafeHtml {
    constructor(str) {
      this.__html = str;
    }
    toString() {
      return this.__html;
    }
  }

  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const escape = (v) => String(v).replace(/[&<>"']/g, (c) => ESC[c]);

  function render(v) {
    if (v == null || v === false) return "";
    if (v instanceof SafeHtml) return v.__html;
    if (Array.isArray(v)) return v.map(render).join("");
    return escape(v);
  }

  /** 转义插值的模板标签，返回 SafeHtml */
  SS.html = function html(strings, ...values) {
    let out = strings[0];
    for (let i = 0; i < values.length; i++) out += render(values[i]) + strings[i + 1];
    return new SafeHtml(out);
  };

  /** 标记可信片段（仅用于内部生成的 SVG 等） */
  SS.raw = (str) => new SafeHtml(String(str));

  /** 把 SafeHtml 写入元素 */
  SS.mount = (el, safe) => {
    el.innerHTML = render(safe);
    return el;
  };

  /** 由 SafeHtml 创建单个元素 */
  SS.el = (safe) => {
    const t = document.createElement("template");
    t.innerHTML = render(safe).trim();
    return t.content.firstElementChild;
  };

  SS.$ = (sel, root = document) => root.querySelector(sel);
  SS.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /** 是否偏好减少动态效果（实时读取，用户切换系统设置后立即生效） */
  const rm = window.matchMedia("(prefers-reduced-motion: reduce)");
  SS.reducedMotion = () => rm.matches;

  /** 触感反馈：支持的设备上轻震动 */
  SS.haptic = (ms = 8) => {
    try {
      if (!SS.reducedMotion() && navigator.vibrate) navigator.vibrate(ms);
    } catch (_) {
      /* 忽略 */
    }
  };

  /** 线性图标（stroke 跟随 currentColor，不引入颜色） */
  const ICONS = {
    market:
      '<path d="M3 17l5-5 4 4 8-8"/><path d="M14 8h6v6"/>',
    portfolio:
      '<rect x="3" y="7" width="18" height="13" rx="2.5"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7"/><path d="M3 12.5h18"/>',
    auto:
      '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6L13 3z"/>',
    me:
      '<circle cx="12" cy="8.5" r="3.8"/><path d="M4.5 20c1.2-3.6 4-5.4 7.5-5.4s6.3 1.8 7.5 5.4"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    chevron: '<path d="M9 5l7 7-7 7"/>',
    star: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    sort: '<path d="M8 4v16M4 8l4-4 4 4M16 20V4M12 16l4 4 4-4"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 6.1A9.4 9.4 0 0 1 12 6c6 0 9.5 6 9.5 6a16 16 0 0 1-3 3.6M6.6 7.1A15.6 15.6 0 0 0 2.5 12S6 18 12 18a9 9 0 0 0 4.2-1"/>',
    trash: '<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 2.5 14.4 0 17M12 3.5c-2.5 2.6-2.5 14.4 0 17"/>',
    moon: '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5M20 20v-4h-4"/>',
    download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14"/>',
    logout: '<path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14M10 16l-4-4 4-4M6 12h10"/>',
    pause: '<path d="M9 5v14M15 5v14"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    swap: '<path d="M7 7h12l-3-3M17 17H5l3 3"/>',
    // 5 tab Dock 与玩法页新增（取自画板）
    news: '<rect x="5" y="4" width="14" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    pie: '<circle cx="12" cy="12" r="8"/><path d="M12 4v8l6 4"/>',
    games: '<path d="M12 3l2.6 5.6 6 .7-4.5 4.1 1.2 6L12 16.6 6.7 19.4l1.2-6L3.4 9.3l6-.7z"/>',
    chain: '<circle cx="5.5" cy="12" r="2.5"/><circle cx="18.5" cy="6.5" r="2.5"/><circle cx="18.5" cy="17.5" r="2.5"/><path d="M8 11l8-3.3M8 13l8 3.3"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  };
  SS.icon = (name, cls = "") =>
    SS.raw(
      `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`
    );
})();
